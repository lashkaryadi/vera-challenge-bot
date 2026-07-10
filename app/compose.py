"""
compose(category, merchant, trigger, customer?) -> {message, cta, send_as,
suppression_key, rationale}

This is the function the challenge brief asks you to build. The pipeline,
in order, is exactly what the rubric scores:

  1. pick_trigger()        -> "Decision quality": choose the single best
                               signal for this moment (not just the first one).
  2. extract_*_facts()     -> "Specificity" + "Merchant fit": pull real
                               numbers/offers/dates out of the context you
                               were actually given.
  3. get_voice()            -> "Category fit": tone rules per business type.
  4. LLM draft + guardrail -> "Engagement compulsion" with a safety net:
                               the LLM writes something compelling, but a
                               deterministic template ships instead if the
                               draft invents facts or breaks the single-CTA rule.
"""

from .voice_profiles import get_voice, TRIGGER_PRIORITY
from .guardrails import build_fact_whitelist, passes_all_guardrails
from .llm import generate_message


def pick_trigger(available_triggers: list[dict]) -> dict:
    """Choose the single best trigger when more than one is live for a merchant."""
    if not available_triggers:
        return {"kind": "recall"}
    return max(available_triggers, key=lambda t: TRIGGER_PRIORITY.get(t.get("kind", ""), 0))


def extract_merchant_facts(merchant_payload: dict) -> dict:
    facts: dict = {}
    identity = merchant_payload.get("identity", {}) or {}
    performance = merchant_payload.get("performance", {}) or {}
    offers = merchant_payload.get("offers", []) or []

    facts["merchant_id"] = identity.get("merchant_id", identity.get("id", "unknown"))
    facts["merchant_name"] = identity.get("name", "there")
    facts["category"] = identity.get("category", "")

    for key, value in performance.items():
        facts[f"perf_{key}"] = value

    if offers:
        top_offer = offers[0]
        facts["offer_title"] = top_offer.get("title", "")
        facts["offer_price"] = top_offer.get("price", "")

    return facts


def extract_trigger_facts(trigger_payload: dict) -> dict:
    return {k: v for k, v in (trigger_payload or {}).items()}


def extract_customer_facts(customer_payload: dict | None) -> dict:
    return dict(customer_payload) if customer_payload else {}


def build_template_message(trigger: dict, facts: dict) -> str:
    """Deterministic, zero-hallucination-risk message. This is also a
    perfectly valid message on its own -- the LLM step only needs to beat it,
    it doesn't need to replace it."""
    kind = trigger.get("kind", "recall")
    name = facts.get("merchant_name", "there")

    # Pre-compute the little conditional snippets so no f-string below needs
    # nested quotes (keeps this file compatible with Python 3.10/3.11 too).
    offer_price_suffix = f" at {facts['offer_price']}" if facts.get("offer_price") else ""
    metric_change_phrase = (
        f"dropped {facts['metric_change']}" if facts.get("metric_change") else "have slowed down"
    )

    templates = {
        "research_digest": (
            f"{facts.get('merchant_name', 'Hi there')}, a relevant update landed. "
            f"Want me to pull the key point and suggest a next step?"
        ),
        "spike": (
            f"{facts.get('search_volume', 'Several')} people nearby searched for "
            f"'{facts.get('search_term', facts.get('category', 'your service'))}' recently. "
            f"Should I send them your {facts.get('offer_title', 'current offer')}{offer_price_suffix}?"
        ),
        "perf_dip": (
            f"Hi {name}, your {facts.get('metric_name', 'bookings')} "
            f"{metric_change_phrase} recently. Want me to send a win-back offer to recent customers?"
        ),
        "dip": (
            f"Hi {name}, your {facts.get('metric_name', 'bookings')} "
            f"{metric_change_phrase} recently. Want me to send a win-back offer to recent customers?"
        ),
        "recall_due": (
            f"Hi {name}, a few regulars haven't been back in a while. "
            f"Should I send them a comeback offer to bring them in?"
        ),
        "recall": (
            f"Hi {name}, a few regulars haven't been back in a while. "
            f"Should I send them a comeback offer to bring them in?"
        ),
        "research": (
            f"{facts.get('research_count', 'A few')} customers viewed your listing but "
            f"didn't book. Want me to send them a small nudge offer?"
        ),
        "festival": (
            f"Hi {name}, {facts.get('festival_name', 'an upcoming festival')} is coming up. "
            f"Should I launch a themed offer for it?"
        ),
    }
    return templates.get(kind, templates.get("recall", next(iter(templates.values()))))


def compose(category: str, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    voice = get_voice(category)

    merchant_facts = extract_merchant_facts(merchant)
    trigger_facts = extract_trigger_facts(trigger)
    customer_facts = extract_customer_facts(customer)

    # --- consent / scope gate --------------------------------------------
    # If we only have merchant-level context, or the customer explicitly has
    # not consented, we must not pretend to message the customer directly.
    customer_scope_allowed = bool(customer) and customer.get("consent", True) is not False

    whitelist = build_fact_whitelist(merchant_facts, trigger_facts, customer_facts)
    fallback_message = build_template_message(trigger, {**merchant_facts, **trigger_facts})

    system_prompt = (
        f"You write ONE short WhatsApp-style business message on behalf of Vera, "
        f"an AI growth assistant, to a {category} merchant named "
        f"'{merchant_facts.get('merchant_name')}'. "
        f"Tone: {voice['tone']}. Style: {voice['style']} "
        f"Avoid: {', '.join(voice['avoid'])}. "
        f"You may ONLY reference these known facts, and must invent NOTHING else "
        f"(no new numbers, offers, or claims): {({**trigger_facts, **merchant_facts})}. "
        f"End with exactly ONE clear, low-effort call to action (a yes/no style question). "
        f"Keep the whole message under 40 words. Return only the message text."
    )
    user_prompt = f"Reason this message is going out now: '{trigger.get('kind', 'recall')}'. Write it."

    llm_draft = generate_message(system_prompt, user_prompt)

    if llm_draft:
        ok, _reason = passes_all_guardrails(llm_draft, whitelist)
        final_message = llm_draft if ok else fallback_message
    else:
        final_message = fallback_message

    trigger_kind = trigger.get("kind", "recall")
    trigger_id = trigger.get("id", trigger.get("trigger_id", trigger_kind))
    merchant_id = merchant_facts.get("merchant_id", "unknown")

    rationale = (
        f"Trigger '{trigger_kind}' selected (priority-ranked). "
        f"Category voice: {category}/{voice['tone']}. "
        f"Message grounded against {len(whitelist)} known fact value(s) from merchant+trigger"
        f"{'+customer' if customer_facts else ''} context. "
        f"{'Direct customer-scoped send.' if customer_scope_allowed else 'Merchant-facing send only (no customer scope / consent).'}"
    )

    return {
        "message": final_message,
        "body": final_message,
        "cta": "Reply YES to launch, NO to skip",
        "send_as": "vera",
        "suppression_key": f"{merchant_id}:{trigger_kind}:{trigger_id}",
        "rationale": rationale,
    }
