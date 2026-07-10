"""
FastAPI app exposing the 5 endpoints the judge harness calls:

  POST /v1/context   push merchant / customer / trigger / category context
  POST /v1/tick       ask the bot to decide + compose the next message
  POST /v1/reply      hand the bot an incoming reply, get the next step
  GET  /v1/healthz    liveness check
  GET  /v1/metadata   bot self-description

Run locally:
    uvicorn app.main:app --reload --port 8000

Then try:
    curl http://localhost:8000/v1/healthz
"""

import uuid
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .models import (
    ContextPush,
    ContextAck,
    TickRequest,
    ReplyRequest,
)
from .store import store
from .compose import compose
from .voice_profiles import DEFAULT_CATEGORY
from .voice_profiles import TRIGGER_PRIORITY

app = FastAPI(title="Vera Challenge Bot", version="0.1.0")
START_TIME = datetime.now(timezone.utc)


@app.get("/")
def root():
    return {"status": "ok", "message": "Vera Challenge Bot is running"}


def _stored_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _resolve_context(scope: str, context_id: str):
    entry = store.get(scope, context_id)
    if entry:
        return entry

    if scope in {"merchant", "customer", "trigger", "category"}:
        for cid, candidate in store.all_in_scope(scope).items():
            payload = candidate.get("payload", {}) if isinstance(candidate, dict) else {}
            if scope == "merchant":
                if payload.get("merchant_id") == context_id or payload.get("identity", {}).get("place_id") == context_id:
                    return candidate
            elif scope == "customer":
                if payload.get("customer_id") == context_id:
                    return candidate
            elif scope == "trigger":
                if payload.get("id") == context_id:
                    return candidate
            elif scope == "category":
                if payload.get("slug") == context_id:
                    return candidate
    return None


def _counts_by_scope() -> dict[str, int]:
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for scope in counts:
        counts[scope] = len(store.all_in_scope(scope))
    return counts


@app.get("/v1/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int((datetime.now(timezone.utc) - START_TIME).total_seconds()),
        "contexts_loaded": _counts_by_scope(),
    }


@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": "vera-challenge-bot",
        "team_members": [],
        "model": "rule-based-baseline",
        "approach": "deterministic composer with trigger routing and guardrails",
        "contact_email": "",
        "version": "0.1.0",
        "capabilities": ["context", "tick", "reply", "healthz"],
        "categories_supported": ["dentist", "salon", "restaurant", "gym", "pharmacy"],
    }


@app.post("/v1/context", response_model=ContextAck)
def push_context(ctx: ContextPush):
    stored, current_version = store.upsert(ctx.scope, ctx.context_id, ctx.version, ctx.payload, ctx.delivered_at)
    if not stored:
        return JSONResponse(
            status_code=409,
            content={
                "accepted": False,
                "reason": "stale_version",
                "current_version": current_version,
            },
        )
    return ContextAck(
        accepted=True,
        ack_id=f"ack_{uuid.uuid4().hex[:12]}",
        stored_at=_stored_at(),
    )


@app.post("/v1/tick")
def tick(req: TickRequest):
    # Official judge path: now + available_triggers -> actions[]
    if req.available_triggers or req.now is not None:
        chosen_by_merchant = {}
        for trigger_id in req.available_triggers:
            trigger_entry = _resolve_context("trigger", trigger_id)
            if not trigger_entry:
                continue
            trigger_payload = trigger_entry["payload"]
            merchant_id = trigger_payload.get("merchant_id") or req.merchant_id
            if not merchant_id:
                continue
            merchant_entry = _resolve_context("merchant", merchant_id)
            if not merchant_entry:
                continue

            merchant_payload = merchant_entry["payload"]
            category = (
                merchant_payload.get("category_slug")
                or merchant_payload.get("identity", {}).get("category")
                or trigger_payload.get("payload", {}).get("category")
                or DEFAULT_CATEGORY
            )
            customer_id = trigger_payload.get("customer_id")
            customer_entry = _resolve_context("customer", customer_id) if customer_id else None

            candidate = {
                "trigger_id": trigger_id,
                "trigger_entry": trigger_entry,
                "merchant_entry": merchant_entry,
                "category": category,
                "customer_entry": customer_entry,
            }
            existing = chosen_by_merchant.get(merchant_id)
            if not existing:
                chosen_by_merchant[merchant_id] = candidate
                continue

            existing_kind = existing["trigger_entry"]["payload"].get("kind", "")
            new_kind = trigger_payload.get("kind", "")
            existing_priority = TRIGGER_PRIORITY.get(existing_kind, 0)
            new_priority = TRIGGER_PRIORITY.get(new_kind, 0)
            if new_priority >= existing_priority:
                chosen_by_merchant[merchant_id] = candidate

        actions = []
        for merchant_id, item in chosen_by_merchant.items():
            compose_result = compose(
                category=item["category"],
                merchant=item["merchant_entry"]["payload"],
                trigger=item["trigger_entry"]["payload"],
                customer=(item["customer_entry"]["payload"] if item["customer_entry"] else None),
            )
            actions.append({
                "conversation_id": f"conv_{merchant_id}_{item['trigger_id']}",
                "merchant_id": merchant_id,
                "customer_id": item["trigger_entry"]["payload"].get("customer_id"),
                "send_as": "vera",
                "trigger_id": item["trigger_id"],
                "template_name": f"vera_{item['trigger_entry']['payload'].get('kind', 'message')}_v1",
                "template_params": [item["merchant_entry"]["payload"].get("identity", {}).get("name", ""), compose_result.get("body", compose_result.get("message", "")), compose_result.get("cta", "")],
                "body": compose_result.get("body", compose_result.get("message", "")),
                "cta": compose_result.get("cta", "open_ended"),
                "suppression_key": compose_result.get("suppression_key", ""),
                "rationale": compose_result.get("rationale", ""),
            })
        return {"actions": actions}

    # Backwards-compatible local smoke path: merchant_id + trigger_id -> one message dict.
    merchant_entry = _resolve_context("merchant", req.merchant_id or "") if req.merchant_id else None
    if not merchant_entry:
        raise HTTPException(status_code=404, detail=f"No merchant context stored for '{req.merchant_id}'")

    trigger_entry = _resolve_context("trigger", req.trigger_id) if req.trigger_id else None
    customer_entry = _resolve_context("customer", req.customer_id) if req.customer_id else None

    category = merchant_entry["payload"].get("identity", {}).get("category", DEFAULT_CATEGORY)

    result = compose(
        category=category,
        merchant=merchant_entry["payload"],
        trigger=(trigger_entry["payload"] if trigger_entry else {"kind": "recall"}),
        customer=(customer_entry["payload"] if customer_entry else None),
    )
    return result


@app.post("/v1/reply")
def reply(req: ReplyRequest):
    """Very small intent classifier + response map.

    This is deliberately simple and rule-based first (fast + deterministic),
    which is exactly what the rubric rewards. Swap in an LLM classifier for
    the harder / ambiguous cases once this baseline is solid -- see the PDF
    guide, section 'Leveling up /v1/reply', for how to do that safely.
    """
    text_source = req.message or req.incoming_text or ""
    text = text_source.strip().lower()

    if any(phrase in text for phrase in ("thank you for contacting", "we will respond shortly", "auto-reply")):
        action = {
            "action": "wait",
            "wait_seconds": 14400,
            "rationale": "Detected merchant auto-reply, backing off to avoid wasting turns.",
        }
    elif any(word in text for word in ("not interested", "stop messaging", "stop", "unsubscribe")):
        action = {"action": "end", "rationale": "Merchant explicitly opted out; ending conversation."}
    elif any(word in text for word in ("yes", "send", "abstract", "go ahead", "okay", "ok", "sure")):
        action = {
            "action": "send",
            "body": "Sending now — I can also draft the next step if you want.",
            "cta": "open_ended",
            "rationale": "Confirmed interest, so continuing with the next useful step.",
        }
    elif any(word in text for word in ("later", "tomorrow", "call back", "busy", "time")):
        action = {
            "action": "wait",
            "wait_seconds": 1800,
            "rationale": "Merchant asked for time, so pausing before the next message.",
        }
    elif any(w in text for w in ("human", "talk to", "agent", "support")):
        action = {
            "action": "end",
            "rationale": "Handing off to a human since the merchant requested human support.",
        }
    else:
        action = {
            "action": "send",
            "body": "Got it — want me to make this easier with a ready draft?",
            "cta": "open_ended",
            "rationale": "Kept the thread moving with a low-friction question.",
        }

    merchant_id = req.merchant_id or "unknown"
    if req.from_role is None and req.incoming_text is not None and req.message is None:
        intent = "confirm" if action["action"] == "send" else "decline" if action["action"] == "end" else "wait"
        return {
            "message": action.get("body", action.get("rationale", "")),
            "cta": action.get("cta"),
            "send_as": "Vera",
            "suppression_key": f"{merchant_id}:reply:{intent}",
            "rationale": action["rationale"],
            "intent_detected": intent,
            "action": action["action"],
        }

    if action["action"] == "send":
        return {
            **action,
            "send_as": "vera",
            "suppression_key": f"{merchant_id}:{req.conversation_id or 'reply'}:send",
            "message": action["body"],
            "intent_detected": "confirm",
        }
    if action["action"] == "wait":
        return {
            **action,
            "send_as": "vera",
            "suppression_key": f"{merchant_id}:{req.conversation_id or 'reply'}:wait",
            "intent_detected": "wait",
        }
    return {
        **action,
        "send_as": "vera",
        "suppression_key": f"{merchant_id}:{req.conversation_id or 'reply'}:end",
        "intent_detected": "decline",
    }
