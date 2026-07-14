"""
FastAPI app exposing the 5 endpoints the judge harness calls:

  POST /v1/context   push merchant / customer / trigger / category context
  POST /v1/tick       ask the bot to decide + compose the next message
  POST /v1/reply      hand the bot an incoming reply, get the next step
  GET  /v1/healthz    liveness check
  GET  /v1/metadata   bot self-description

Run locally:
    uvicorn app.main:app --reload --port 8000
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
from .voice_profiles import DEFAULT_CATEGORY, TRIGGER_PRIORITY
from .llm import generate_message

app = FastAPI(title="Vera Challenge Bot", version="0.2.0")
START_TIME = datetime.now(timezone.utc)

conversations: dict[str, dict] = {}
ended_conversations: set[str] = set()
merchant_auto_reply_counts: dict[str, int] = {}  # track auto-replies per merchant across conversations


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


def _get_conversation(conv_id: str) -> dict:
    if conv_id not in conversations:
        conversations[conv_id] = {
            "turns": [],
            "auto_reply_count": 0,
            "last_sent_body": "",
            "merchant_id": None,
            "customer_id": None,
            "trigger_id": None,
            "trigger_kind": None,
        }
    return conversations[conv_id]


def _is_auto_reply(text: str) -> bool:
    lower = text.strip().lower()
    auto_phrases = [
        "thank you for contacting",
        "we will respond shortly",
        "auto-reply",
        "our team will respond",
        "automated assistant",
        "automated reply",
        "will get back to you",
        "we'll get back to you",
        "this is an automated",
        "your message has been received",
        "thanks for reaching out",
    ]
    return any(p in lower for p in auto_phrases)


def _is_opt_out(text: str) -> bool:
    lower = text.strip().lower()
    opt_out_phrases = [
        "not interested",
        "stop messaging",
        "stop sending",
        "don't message",
        "don't contact",
        "unsubscribe",
        "remove me",
        "leave me alone",
        "this is useless",
        "stop bothering",
        "why are you bothering",
    ]
    return any(p in lower for p in opt_out_phrases)


def _is_hostile(text: str) -> bool:
    lower = text.strip().lower()
    hostile_markers = [
        "useless",
        "spam",
        "scam",
        "fraud",
        "stop bothering",
        "waste of time",
        "rubbish",
        "bakwas",
    ]
    return any(m in lower for m in hostile_markers)


def _is_intent_confirm(text: str) -> bool:
    lower = text.strip().lower()
    confirm_phrases = [
        "yes", "sure", "ok", "okay", "go ahead", "let's do it",
        "do it", "send it", "proceed", "confirm", "haan", "ha",
        "chalo", "kar do", "bhej do", "theek hai", "thik hai",
        "sounds good", "great", "perfect", "absolutely",
        "send", "draft", "please", "yep", "yeah",
    ]
    for phrase in confirm_phrases:
        if lower == phrase or lower.startswith(phrase + " ") or lower.startswith(phrase + ",") or lower.startswith(phrase + "."):
            return True
        if f" {phrase}" in f" {lower}":
            words = lower.split()
            if phrase in words:
                return True
    return False


def _is_delay_request(text: str) -> bool:
    lower = text.strip().lower()
    delay_words = ["later", "tomorrow", "call back", "busy", "not now", "baad mein", "kal"]
    return any(w in lower for w in delay_words)


def _is_human_request(text: str) -> bool:
    lower = text.strip().lower()
    return any(w in lower for w in ["human", "talk to someone", "agent", "real person", "support team"])


def _is_repeated_message(conv: dict, text: str) -> bool:
    for turn in conv["turns"]:
        if turn.get("role") == "merchant" and turn.get("body", "").strip().lower() == text.strip().lower():
            return True
    return False


@app.get("/")
def root():
    return {"status": "ok", "message": "Vera Challenge Bot is running"}


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
        "model": "openai/gpt-oss-120b + rule-based-guardrails",
        "approach": "4-context composer with category voice, trigger dispatch, LLM generation, guardrail validation, conversation state tracking, auto-reply escalation",
        "contact_email": "",
        "version": "0.2.0",
        "capabilities": ["context", "tick", "reply", "healthz"],
        "categories_supported": ["dentist", "dentists", "salon", "salons", "restaurant", "restaurants", "gym", "gyms", "pharmacy", "pharmacies"],
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
        ack_id=f"ack_{ctx.context_id}_v{ctx.version}",
        stored_at=_stored_at(),
    )


@app.post("/v1/tick")
def tick(req: TickRequest):
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
            category_slug = (
                merchant_payload.get("category_slug")
                or merchant_payload.get("identity", {}).get("category")
                or trigger_payload.get("payload", {}).get("category")
                or DEFAULT_CATEGORY
            )

            category_entry = _resolve_context("category", category_slug)
            if not category_entry:
                alt_slug = category_slug.rstrip("s") if category_slug.endswith("s") else category_slug + "s"
                category_entry = _resolve_context("category", alt_slug)

            customer_id = trigger_payload.get("customer_id")
            customer_entry = _resolve_context("customer", customer_id) if customer_id else None

            candidate = {
                "trigger_id": trigger_id,
                "trigger_entry": trigger_entry,
                "merchant_entry": merchant_entry,
                "category": category_slug,
                "category_entry": category_entry,
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
            trigger_payload = item["trigger_entry"]["payload"]
            trigger_kind = trigger_payload.get("kind", "message")

            compose_result = compose(
                category=item["category"],
                merchant=item["merchant_entry"]["payload"],
                trigger=trigger_payload,
                customer=(item["customer_entry"]["payload"] if item["customer_entry"] else None),
                category_context=(item["category_entry"]["payload"] if item["category_entry"] else None),
            )

            merchant_name = item["merchant_entry"]["payload"].get("identity", {}).get("name", "")
            conv_id = f"conv_{merchant_id}_{item['trigger_id']}"

            if conv_id in ended_conversations:
                continue

            customer_id = trigger_payload.get("customer_id")
            send_as = compose_result.get("send_as", "vera")
            trigger_sup_key = trigger_payload.get("suppression_key", "")
            sup_key = compose_result.get("suppression_key", trigger_sup_key or f"{merchant_id}:{trigger_kind}:{item['trigger_id']}")

            action = {
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "send_as": send_as,
                "trigger_id": item["trigger_id"],
                "template_name": f"vera_{trigger_kind}_v1",
                "template_params": [
                    merchant_name,
                    compose_result.get("body", ""),
                    compose_result.get("cta", ""),
                ],
                "body": compose_result.get("body", compose_result.get("message", "")),
                "cta": compose_result.get("cta", "open_ended"),
                "suppression_key": sup_key,
                "rationale": compose_result.get("rationale", ""),
            }
            actions.append(action)

            conv = _get_conversation(conv_id)
            conv["merchant_id"] = merchant_id
            conv["customer_id"] = customer_id
            conv["trigger_id"] = item["trigger_id"]
            conv["trigger_kind"] = trigger_kind
            conv["last_sent_body"] = action["body"]
            conv["turns"].append({
                "role": "vera",
                "body": action["body"],
                "ts": req.now or _stored_at(),
            })

        return {"actions": actions}

    merchant_entry = _resolve_context("merchant", req.merchant_id or "") if req.merchant_id else None
    if not merchant_entry:
        raise HTTPException(status_code=404, detail=f"No merchant context stored for '{req.merchant_id}'")

    trigger_entry = _resolve_context("trigger", req.trigger_id) if req.trigger_id else None
    customer_entry = _resolve_context("customer", req.customer_id) if req.customer_id else None

    merchant_payload = merchant_entry["payload"]
    category_slug = merchant_payload.get("category_slug") or merchant_payload.get("identity", {}).get("category", DEFAULT_CATEGORY)
    category_entry = _resolve_context("category", category_slug)
    if not category_entry:
        alt_slug = category_slug.rstrip("s") if category_slug.endswith("s") else category_slug + "s"
        category_entry = _resolve_context("category", alt_slug)

    result = compose(
        category=category_slug,
        merchant=merchant_payload,
        trigger=(trigger_entry["payload"] if trigger_entry else {"kind": "recall"}),
        customer=(customer_entry["payload"] if customer_entry else None),
        category_context=(category_entry["payload"] if category_entry else None),
    )
    return result


@app.post("/v1/reply")
def reply(req: ReplyRequest):
    text_source = req.message or req.incoming_text or ""
    text = text_source.strip()
    text_lower = text.lower()

    conv_id = req.conversation_id or f"reply_{req.merchant_id or 'unknown'}"
    conv = _get_conversation(conv_id)

    if req.merchant_id:
        conv["merchant_id"] = req.merchant_id
    if req.customer_id:
        conv["customer_id"] = req.customer_id

    conv["turns"].append({
        "role": req.from_role or "merchant",
        "body": text,
        "ts": req.received_at or _stored_at(),
    })

    merchant_id = req.merchant_id or conv.get("merchant_id") or "unknown"

    if conv_id in ended_conversations:
        return {
            "action": "end",
            "rationale": "Conversation was already ended.",
            "send_as": "vera",
            "suppression_key": f"{merchant_id}:{conv_id}:ended",
            "intent_detected": "decline",
        }

    is_repeated = _is_repeated_message(conv, text)
    auto_reply = _is_auto_reply(text)

    if auto_reply or (is_repeated and len(conv["turns"]) > 2):
        # Track auto-reply count per merchant (across conversations)
        merchant_auto_reply_counts[merchant_id] = merchant_auto_reply_counts.get(merchant_id, 0) + 1
        conv["auto_reply_count"] = conv.get("auto_reply_count", 0) + 1
        count = merchant_auto_reply_counts[merchant_id]

        if count >= 4:
            ended_conversations.add(conv_id)
            action = {
                "action": "end",
                "rationale": f"Auto-reply {count}x from this merchant across conversations. No real engagement; closing.",
                "send_as": "vera",
                "suppression_key": f"{merchant_id}:{conv_id}:auto_reply_end",
                "intent_detected": "auto_reply",
            }
        else:
            wait_seconds = 86400 if count >= 2 else 3600
            action = {
                "action": "wait",
                "wait_seconds": wait_seconds,
                "rationale": f"Auto-reply {count}x from this merchant — owner not at phone. Waiting before retry.",
                "send_as": "vera",
                "suppression_key": f"{merchant_id}:{conv_id}:auto_reply_wait_{count}",
                "intent_detected": "auto_reply",
            }

        conv["turns"].append({"role": "vera", "body": action.get("body", ""), "ts": _stored_at()})
        return {**action, "message": action.get("body", action.get("rationale", ""))}

    if _is_opt_out(text) or _is_hostile(text):
        ended_conversations.add(conv_id)
        action = {
            "action": "end",
            "rationale": "Merchant explicitly opted out or expressed frustration; closing conversation.",
            "send_as": "vera",
            "suppression_key": f"{merchant_id}:{conv_id}:opt_out",
            "intent_detected": "decline",
        }
        return {**action, "message": action.get("rationale", "")}

    if _is_human_request(text):
        ended_conversations.add(conv_id)
        action = {
            "action": "end",
            "rationale": "Handing off to a human since the merchant requested human support.",
            "send_as": "vera",
            "suppression_key": f"{merchant_id}:{conv_id}:handoff",
            "intent_detected": "handoff",
        }
        return {**action, "message": action.get("rationale", "")}

    if _is_delay_request(text):
        action = {
            "action": "wait",
            "wait_seconds": 1800,
            "rationale": "Merchant asked for time; pausing 30 min before next message.",
            "send_as": "vera",
            "suppression_key": f"{merchant_id}:{conv_id}:wait",
            "intent_detected": "wait",
        }
        return {**action, "message": action.get("rationale", "")}

    conv["auto_reply_count"] = 0

    merchant_entry = _resolve_context("merchant", merchant_id)
    merchant_payload = merchant_entry["payload"] if merchant_entry else {}
    merchant_name = merchant_payload.get("identity", {}).get("name", "")
    category_slug = (
        merchant_payload.get("category_slug")
        or merchant_payload.get("identity", {}).get("category", DEFAULT_CATEGORY)
    )
    category_entry = _resolve_context("category", category_slug)
    if not category_entry:
        alt_slug = category_slug.rstrip("s") if category_slug.endswith("s") else category_slug + "s"
        category_entry = _resolve_context("category", alt_slug)

    trigger_kind = conv.get("trigger_kind", "recall")

    if _is_intent_confirm(text):
        reply_body = _compose_confirm_reply(
            merchant_payload, category_entry, trigger_kind, text, conv
        )
        action = {
            "action": "send",
            "body": reply_body,
            "cta": "open_ended",
            "rationale": f"Merchant confirmed interest ('{text[:50]}'); switching to action mode with concrete next step.",
            "send_as": "vera",
            "suppression_key": f"{merchant_id}:{conv_id}:confirmed",
            "intent_detected": "confirm",
            "message": reply_body,
        }
        conv["last_sent_body"] = reply_body
        conv["turns"].append({"role": "vera", "body": reply_body, "ts": _stored_at()})
        return action

    reply_body = _compose_contextual_reply(
        merchant_payload, category_entry, trigger_kind, text, conv
    )
    action = {
        "action": "send",
        "body": reply_body,
        "cta": "open_ended",
        "rationale": f"Continued conversation with contextual response to merchant input.",
        "send_as": "vera",
        "suppression_key": f"{merchant_id}:{conv_id}:reply",
        "intent_detected": "engaged",
        "message": reply_body,
    }
    conv["last_sent_body"] = reply_body
    conv["turns"].append({"role": "vera", "body": reply_body, "ts": _stored_at()})
    return action


def _compose_confirm_reply(
    merchant_payload: dict,
    category_entry: dict | None,
    trigger_kind: str,
    merchant_text: str,
    conv: dict,
) -> str:
    merchant_name = merchant_payload.get("identity", {}).get("name", "")
    owner_name = merchant_payload.get("identity", {}).get("owner_first_name", "")
    display = owner_name or merchant_name or "there"

    offers = merchant_payload.get("offers", []) or []
    active_offers = [o for o in offers if o.get("status") == "active"]
    offer_text = active_offers[0].get("title", "") if active_offers else ""

    cust_agg = merchant_payload.get("customer_aggregate", {}) or {}

    cat_payload = category_entry["payload"] if category_entry else {}
    cat_tone = cat_payload.get("voice", {}).get("tone", "professional")

    context_parts = [
        f"Merchant: {display}",
        f"Category tone: {cat_tone}",
        f"Trigger: {trigger_kind}",
        f"Merchant said: '{merchant_text}'",
    ]
    if offer_text:
        context_parts.append(f"Active offer: {offer_text}")
    if cust_agg:
        context_parts.append(f"Customer stats: {cust_agg}")

    prev_turns = conv.get("turns", [])[-4:]
    history = " | ".join(f"{t['role']}: {t['body'][:80]}" for t in prev_turns)
    if history:
        context_parts.append(f"Recent conversation: {history}")

    system_prompt = (
        "You are Vera, an AI growth assistant. The merchant just confirmed they want to proceed. "
        "Switch to ACTION mode — give a concrete next step with specific details. "
        "Do NOT ask another qualifying question. Be specific about what you'll do next. "
        "Keep under 40 words. One sentence. No URLs. No preamble."
    )
    user_prompt = "Context: " + "; ".join(context_parts) + ". Write the action-mode reply."

    llm_reply = generate_message(system_prompt, user_prompt)
    if llm_reply:
        from .guardrails import has_url
        if not has_url(llm_reply):
            return llm_reply

    if trigger_kind in ("research_digest", "research"):
        return f"Sending the details now. I'll also draft a ready-to-share version — review it and say GO when ready."
    if trigger_kind in ("spike", "perf_spike"):
        return f"On it — drafting your {offer_text or 'offer'} push now. Will have it ready in 2 minutes."
    if trigger_kind in ("recall", "recall_due", "customer_lapsed_soft"):
        return f"Drafting the recall message for your lapsed customers now. I'll share the draft for your approval."
    if trigger_kind in ("dip", "perf_dip", "seasonal_perf_dip"):
        return f"Creating a win-back campaign draft now. Will target your recent customers with {offer_text or 'your best offer'}."
    return f"On it — preparing everything now. I'll share the draft for your review in a moment."


def _compose_contextual_reply(
    merchant_payload: dict,
    category_entry: dict | None,
    trigger_kind: str,
    merchant_text: str,
    conv: dict,
) -> str:
    merchant_name = merchant_payload.get("identity", {}).get("name", "")
    owner_name = merchant_payload.get("identity", {}).get("owner_first_name", "")
    display = owner_name or merchant_name or "there"

    cat_payload = category_entry["payload"] if category_entry else {}
    cat_tone = cat_payload.get("voice", {}).get("tone", "professional")

    offers = merchant_payload.get("offers", []) or []
    active_offers = [o for o in offers if o.get("status") == "active"]
    offer_text = active_offers[0].get("title", "") if active_offers else ""

    prev_turns = conv.get("turns", [])[-4:]
    history = " | ".join(f"{t['role']}: {t['body'][:80]}" for t in prev_turns)

    context_parts = [
        f"Merchant: {display}",
        f"Category tone: {cat_tone}",
        f"Trigger: {trigger_kind}",
        f"Merchant said: '{merchant_text}'",
    ]
    if offer_text:
        context_parts.append(f"Active offer: {offer_text}")
    if history:
        context_parts.append(f"Recent conversation: {history}")

    system_prompt = (
        "You are Vera, an AI growth assistant for local merchants. "
        "Reply to the merchant's message helpfully. "
        "If they ask something off-topic (GST, legal, unrelated), politely decline and redirect back to the original topic. "
        "If they ask a question about your capabilities, answer honestly. "
        "Keep under 35 words. One clear next step. No URLs. No preamble. No 'I hope you're doing well'."
    )
    user_prompt = "Context: " + "; ".join(context_parts) + ". Write the reply."

    llm_reply = generate_message(system_prompt, user_prompt)
    if llm_reply:
        from .guardrails import has_url
        if not has_url(llm_reply):
            return llm_reply

    return f"Got it — want me to prepare a ready draft for you? Just say GO and I'll have it in 2 minutes."
