"""
Local sanity test -- simulates exactly what the judge harness will do:
push context, call /v1/tick, then call /v1/reply. Runs with NO API key
needed (compose() falls back to templates), so you can validate the whole
plumbing before you ever touch an LLM key or deploy anywhere.

Run with:
    pytest -q
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_metadata():
    r = client.get("/v1/metadata")
    assert r.status_code == 200
    body = r.json()
    assert "dentist" in body["categories_supported"]
    assert "team_name" in body


def test_full_flow_spike_trigger():
    # 1. Push merchant context
    merchant_payload = {
        "scope": "merchant",
        "context_id": "m_001_drmeera",
        "version": 1,
        "payload": {
            "identity": {
                "merchant_id": "m_001_drmeera",
                "name": "Dr. Meera's Dental Clinic",
                "category": "dentist",
            },
            "performance": {"bookings_last_7d": 12},
            "offers": [{"title": "Dental Check Up", "price": "₹299"}],
        },
        "delivered_at": "2026-04-29T10:00:00Z",
    }
    r = client.post("/v1/context", json=merchant_payload)
    assert r.status_code == 200
    assert r.json()["accepted"] is True

    # 2. Push a "spike" trigger
    trigger_payload = {
        "scope": "trigger",
        "context_id": "t_001",
        "version": 1,
        "payload": {
            "kind": "spike",
            "search_volume": 190,
            "search_term": "Dental Check Up",
        },
        "delivered_at": "2026-04-29T10:00:00Z",
    }
    r = client.post("/v1/context", json=trigger_payload)
    assert r.status_code == 200

    # 3. Ask the bot to decide + compose (this is compose() end-to-end)
    r = client.post("/v1/tick", json={"merchant_id": "m_001_drmeera", "trigger_id": "t_001"})
    assert r.status_code == 200
    body = r.json()

    for field in ("message", "cta", "send_as", "suppression_key", "rationale"):
        assert field in body, f"missing '{field}' in compose() output"

    # Grounding check: the message should not be empty / should have exactly one CTA.
    assert body["message"].strip()
    assert body["message"].count("?") <= 1
    print("\ncomposed message ->", body["message"])
    print("rationale         ->", body["rationale"])


def test_official_tick_path_and_duplicate_context():
    merchant_payload = {
        "scope": "merchant",
        "context_id": "m_002_bharat_dentist_mumbai",
        "version": 1,
        "payload": {
            "merchant_id": "m_002_bharat_dentist_mumbai",
            "identity": {
                "merchant_id": "m_002_bharat_dentist_mumbai",
                "name": "Bharat Dental Care",
                "category": "dentist",
            },
            "performance": {"bookings_last_7d": 4},
            "offers": [{"title": "Dental Cleaning @ ₹299", "price": "₹299"}],
        },
        "delivered_at": "2026-04-29T10:00:00Z",
    }
    r = client.post("/v1/context", json=merchant_payload)
    assert r.status_code == 200
    assert r.json()["accepted"] is True

    trigger_payload = {
        "scope": "trigger",
        "context_id": "t_002",
        "version": 1,
        "payload": {
            "id": "t_002",
            "kind": "dip",
            "merchant_id": "m_002_bharat_dentist_mumbai",
            "metric_name": "calls",
            "metric_change": "50%",
        },
        "delivered_at": "2026-04-29T10:00:00Z",
    }
    r = client.post("/v1/context", json=trigger_payload)
    assert r.status_code == 200

    dup = client.post("/v1/context", json=trigger_payload)
    assert dup.status_code == 409
    assert dup.json()["accepted"] is False
    assert dup.json()["reason"] == "stale_version"

    tick = client.post("/v1/tick", json={"now": "2026-04-29T10:05:00Z", "available_triggers": ["t_002"]})
    assert tick.status_code == 200
    assert "actions" in tick.json()
    assert tick.json()["actions"]
    assert tick.json()["actions"][0]["body"]


def test_reply_yes():
    r = client.post(
        "/v1/reply",
        json={"merchant_id": "m_001_drmeera", "incoming_text": "yes"},
    )
    assert r.status_code == 200
    assert r.json()["intent_detected"] == "confirm"
    assert r.json()["action"] == "send"


def test_reply_objection():
    r = client.post(
        "/v1/reply",
        json={"merchant_id": "m_001_drmeera", "incoming_text": "why, does this cost extra?"},
    )
    assert r.status_code == 200
    assert r.json()["action"] in {"send", "wait", "end"}


def test_reply_auto_reply_escalation():
    conv_id = "conv_auto_test"
    auto_text = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."

    r1 = client.post("/v1/reply", json={
        "conversation_id": conv_id, "merchant_id": "m_001_drmeera",
        "from_role": "merchant", "message": auto_text, "turn_number": 2,
    })
    assert r1.status_code == 200
    assert r1.json()["action"] == "send"

    r2 = client.post("/v1/reply", json={
        "conversation_id": conv_id, "merchant_id": "m_001_drmeera",
        "from_role": "merchant", "message": auto_text, "turn_number": 3,
    })
    assert r2.status_code == 200
    assert r2.json()["action"] == "wait"

    r3 = client.post("/v1/reply", json={
        "conversation_id": conv_id, "merchant_id": "m_001_drmeera",
        "from_role": "merchant", "message": auto_text, "turn_number": 4,
    })
    assert r3.status_code == 200
    assert r3.json()["action"] == "end"


def test_reply_opt_out():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_opt_out", "merchant_id": "m_001_drmeera",
        "from_role": "merchant", "message": "Not interested. Stop messaging me.",
        "turn_number": 2,
    })
    assert r.status_code == 200
    assert r.json()["action"] == "end"


def test_reply_hostile():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_hostile", "merchant_id": "m_001_drmeera",
        "from_role": "merchant", "message": "Why are you bothering me. This is useless.",
        "turn_number": 2,
    })
    assert r.status_code == 200
    assert r.json()["action"] == "end"


def test_reply_delay_request():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_delay", "merchant_id": "m_001_drmeera",
        "from_role": "merchant", "message": "I'm busy right now, call back later",
        "turn_number": 2,
    })
    assert r.status_code == 200
    assert r.json()["action"] == "wait"
    assert r.json().get("wait_seconds", 0) > 0


def test_tick_with_category_context():
    cat = client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": {
            "slug": "dentists",
            "voice": {"tone": "peer_clinical", "taboos": ["cure", "guaranteed"]},
            "peer_stats": {"avg_rating": 4.4, "avg_ctr": 0.030},
            "digest": [{"id": "d1", "kind": "research", "title": "3-mo fluoride recall cuts caries 38%", "source": "JIDA Oct 2026, p.14"}],
            "offer_catalog": [{"title": "Dental Cleaning @ ₹299", "value": "299"}],
        },
        "delivered_at": "2026-04-29T10:00:00Z",
    })
    assert cat.status_code == 200

    trg = client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_research_001", "version": 1,
        "payload": {
            "id": "trg_research_001", "kind": "research_digest", "scope": "merchant",
            "merchant_id": "m_001_drmeera",
            "payload": {"category": "dentists", "top_item_id": "d1"},
            "suppression_key": "research:dentists:2026-W17",
        },
        "delivered_at": "2026-04-29T10:00:00Z",
    })
    assert trg.status_code == 200

    tick = client.post("/v1/tick", json={
        "now": "2026-04-29T10:05:00Z",
        "available_triggers": ["trg_research_001"],
    })
    assert tick.status_code == 200
    actions = tick.json()["actions"]
    assert len(actions) >= 1
    assert actions[0]["body"]
    assert actions[0]["send_as"] == "vera"


def test_tick_missing_merchant_returns_404():
    r = client.post("/v1/tick", json={"merchant_id": "does_not_exist"})
    assert r.status_code == 404


if __name__ == "__main__":
    test_healthz()
    test_metadata()
    test_full_flow_spike_trigger()
    test_official_tick_path_and_duplicate_context()
    test_reply_yes()
    test_reply_objection()
    test_reply_auto_reply_escalation()
    test_reply_opt_out()
    test_reply_hostile()
    test_reply_delay_request()
    test_tick_with_category_context()
    test_tick_missing_merchant_returns_404()
    print("\nAll local checks passed ✅")
