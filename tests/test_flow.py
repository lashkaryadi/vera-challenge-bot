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
    test_tick_missing_merchant_returns_404()
    print("\nAll local checks passed ✅")
