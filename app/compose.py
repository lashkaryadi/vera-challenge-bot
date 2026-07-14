"""
compose(category, merchant, trigger, customer?, category_context?) -> {body, cta, send_as, suppression_key, rationale}

Pipeline (maps to rubric):
  1. extract rich facts from all contexts -> Specificity + Merchant fit
  2. resolve category voice -> Category fit
  3. determine send_as -> Decision quality
  4. LLM draft + guardrail -> Engagement compulsion with safety net
"""

from .voice_profiles import get_voice, TRIGGER_PRIORITY
from .guardrails import build_fact_whitelist, passes_all_guardrails
from .llm import generate_message


def pick_trigger(available_triggers: list[dict]) -> dict:
    if not available_triggers:
        return {"kind": "recall"}
    return max(available_triggers, key=lambda t: TRIGGER_PRIORITY.get(t.get("kind", ""), 0))


def _safe_get(d, *keys, default=""):
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k, default)
        else:
            return default
    return current if current is not None else default


def extract_merchant_facts(merchant_payload: dict) -> dict:
    facts: dict = {}
    identity = merchant_payload.get("identity", {}) or {}
    performance = merchant_payload.get("performance", {}) or {}
    offers = merchant_payload.get("offers", []) or []
    subscription = merchant_payload.get("subscription", {}) or {}
    customer_agg = merchant_payload.get("customer_aggregate", {}) or {}
    signals = merchant_payload.get("signals", []) or []

    facts["merchant_id"] = (
        merchant_payload.get("merchant_id")
        or identity.get("merchant_id")
        or identity.get("id", "unknown")
    )
    facts["merchant_name"] = identity.get("name", "there")
    facts["owner_first_name"] = identity.get("owner_first_name", "")
    facts["category"] = (
        merchant_payload.get("category_slug")
        or identity.get("category", "")
    )
    facts["city"] = identity.get("city", "")
    facts["locality"] = identity.get("locality", "")
    facts["verified"] = identity.get("verified", False)
    facts["languages"] = identity.get("languages", ["en"])

    for key, value in performance.items():
        if isinstance(value, dict):
            for sub_key, sub_val in value.items():
                facts[f"perf_{key}_{sub_key}"] = sub_val
        else:
            facts[f"perf_{key}"] = value

    if subscription:
        facts["sub_status"] = subscription.get("status", "")
        facts["sub_plan"] = subscription.get("plan", "")
        facts["sub_days_remaining"] = subscription.get("days_remaining", "")

    if customer_agg:
        for k, v in customer_agg.items():
            facts[f"cust_{k}"] = v

    facts["signals"] = signals

    active_offers = [o for o in offers if o.get("status") == "active"]
    all_offers_text = []
    for o in offers:
        all_offers_text.append(o.get("title", ""))
    facts["all_offers"] = all_offers_text

    if active_offers:
        top_offer = active_offers[0]
        facts["offer_title"] = top_offer.get("title", "")
        facts["offer_price"] = top_offer.get("price", top_offer.get("value", ""))
    elif offers:
        top_offer = offers[0]
        facts["offer_title"] = top_offer.get("title", "")
        facts["offer_price"] = top_offer.get("price", top_offer.get("value", ""))

    return facts


def extract_trigger_facts(trigger_payload: dict) -> dict:
    if not trigger_payload:
        return {}
    facts = {}
    for k, v in trigger_payload.items():
        if k == "payload" and isinstance(v, dict):
            for pk, pv in v.items():
                facts[f"trigger_{pk}"] = pv
        else:
            facts[k] = v
    return facts


def extract_customer_facts(customer_payload: dict | None) -> dict:
    if not customer_payload:
        return {}
    facts = {}
    facts["customer_id"] = customer_payload.get("customer_id", "")
    identity = customer_payload.get("identity", {}) or {}
    facts["customer_name"] = identity.get("name", "")
    facts["customer_language"] = identity.get("language_pref", "en")

    rel = customer_payload.get("relationship", {}) or {}
    facts["first_visit"] = rel.get("first_visit", "")
    facts["last_visit"] = rel.get("last_visit", "")
    facts["visits_total"] = rel.get("visits_total", "")
    facts["services_received"] = rel.get("services_received", [])

    facts["customer_state"] = customer_payload.get("state", "")
    prefs = customer_payload.get("preferences", {}) or {}
    facts["preferred_slots"] = prefs.get("preferred_slots", "")
    facts["preferred_channel"] = prefs.get("channel", "whatsapp")

    consent = customer_payload.get("consent", {}) or {}
    facts["consent_scope"] = consent.get("scope", [])
    return facts


def extract_category_facts(category_context: dict | None) -> dict:
    if not category_context:
        return {}
    facts = {}
    voice = category_context.get("voice", {}) or {}
    facts["cat_tone"] = voice.get("tone", "")
    facts["cat_taboos"] = voice.get("taboos", voice.get("vocab_taboo", []))

    peer = category_context.get("peer_stats", {}) or {}
    for k, v in peer.items():
        facts[f"peer_{k}"] = v

    digests = category_context.get("digest", []) or []
    if digests:
        for i, d in enumerate(digests[:3]):
            facts[f"digest_{i}_title"] = d.get("title", "")
            facts[f"digest_{i}_source"] = d.get("source", "")
            facts[f"digest_{i}_kind"] = d.get("kind", "")
            if d.get("trial_n"):
                facts[f"digest_{i}_trial_n"] = d["trial_n"]
            if d.get("summary"):
                facts[f"digest_{i}_summary"] = d["summary"]

    trends = category_context.get("trend_signals", []) or []
    for i, t in enumerate(trends[:2]):
        facts[f"trend_{i}_query"] = t.get("query", "")
        facts[f"trend_{i}_delta"] = t.get("delta_yoy", "")

    seasonal = category_context.get("seasonal_beats", []) or []
    for i, s in enumerate(seasonal[:2]):
        facts[f"seasonal_{i}"] = f"{s.get('month_range', '')}: {s.get('note', '')}"

    catalog = category_context.get("offer_catalog", []) or []
    facts["cat_offers"] = [c.get("title", "") for c in catalog[:5]]

    return facts


def _get_display_name(merchant_facts: dict) -> str:
    owner = merchant_facts.get("owner_first_name", "")
    if owner:
        return owner
    name = merchant_facts.get("merchant_name", "there")
    if name and name != "there":
        return name
    return "there"


def _get_taboos(category_context: dict | None, category_facts: dict) -> list[str]:
    if category_context:
        voice = category_context.get("voice", {}) or {}
        taboos = voice.get("taboos", voice.get("vocab_taboo", []))
        if taboos:
            return taboos
    return category_facts.get("cat_taboos", [])


def build_template_message(
    trigger: dict,
    facts: dict,
    category_facts: dict,
    customer_facts: dict,
) -> str:
    kind = trigger.get("kind", "recall")
    name = _get_display_name(facts)
    customer_name = customer_facts.get("customer_name", "")

    offer_suffix = f" at {facts['offer_price']}" if facts.get("offer_price") else ""
    metric_change_phrase = (
        f"dropped {facts.get('metric_change', facts.get('perf_delta_7d_calls_pct', ''))}"
        if facts.get("metric_change") or facts.get("perf_delta_7d_calls_pct")
        else "have slowed down"
    )

    digest_hook = ""
    if category_facts.get("digest_0_title"):
        src = category_facts.get("digest_0_source", "")
        digest_hook = (
            f"{category_facts['digest_0_title']}"
            + (f" — {src}" if src else "")
        )

    cust_agg_lapsed = facts.get("cust_lapsed_180d_plus", "")
    cust_agg_total = facts.get("cust_total_unique_ytd", "")
    retention = facts.get("cust_retention_6mo_pct", "")

    templates = {
        "research_digest": (
            f"{name}, a relevant update landed"
            + (f": {digest_hook}" if digest_hook else "")
            + ". Want me to pull the key point and suggest a next step?"
        ),
        "spike": (
            f"{facts.get('search_volume', 'Several')} people nearby searched for "
            f"'{facts.get('search_term', facts.get('category', 'your service'))}' recently. "
            f"Should I send them your {facts.get('offer_title', 'current offer')}{offer_suffix}?"
        ),
        "perf_spike": (
            f"Hi {name}, your {facts.get('metric_name', 'views')} are up "
            f"{facts.get('metric_change', facts.get('perf_delta_7d_views_pct', ''))} this week. "
            f"Good time to push your {facts.get('offer_title', 'top offer')} to capture the momentum. Want me to draft a quick push?"
        ),
        "perf_dip": (
            f"Hi {name}, your {facts.get('metric_name', 'bookings')} "
            f"{metric_change_phrase} recently. Want me to send a win-back offer to recent customers?"
        ),
        "dip": (
            f"Hi {name}, your {facts.get('metric_name', 'bookings')} "
            f"{metric_change_phrase} recently. Want me to send a win-back offer to recent customers?"
        ),
        "seasonal_perf_dip": (
            f"Hi {name}, your numbers are down this week — but this is the normal seasonal dip. "
            f"Focus retention on your existing customers for now. Want me to draft a re-engagement message?"
        ),
        "recall_due": (
            (f"Hi {customer_name}, " if customer_name else f"Hi {name}, ")
            + "a few regulars haven't been back in a while. "
            + f"Should I send them a comeback offer to bring them in?"
        ),
        "recall": (
            f"Hi {name}, "
            + (f"{cust_agg_lapsed} of your customers" if cust_agg_lapsed else "a few regulars")
            + " haven't been back in a while. "
            + "Should I send them a comeback offer to bring them in?"
        ),
        "customer_lapsed_soft": (
            (f"Hi {customer_name}" if customer_name else f"Hi {name}")
            + (f", it's been a while since your last visit" if customer_name else "")
            + ". Want me to send a gentle nudge with your "
            + f"{facts.get('offer_title', 'best offer')}?"
        ),
        "customer_lapsed_hard": (
            (f"Hi {customer_name}" if customer_name else f"Hi {name}")
            + ", it's been a long time. "
            + f"Want me to send a win-back offer with {facts.get('offer_title', 'a special deal')}?"
        ),
        "research": (
            f"{facts.get('research_count', 'A few')} customers viewed your listing but "
            f"didn't book. Want me to send them a small nudge offer?"
        ),
        "festival": (
            f"Hi {name}, {facts.get('festival_name', 'an upcoming festival')} is coming up. "
            f"Should I launch a themed offer for it?"
        ),
        "festival_upcoming": (
            f"Hi {name}, {facts.get('festival_name', facts.get('trigger_festival_name', 'an upcoming event'))} is coming up. "
            f"Should I draft a themed campaign for your {facts.get('offer_title', 'services')}?"
        ),
        "competitor_opened": (
            f"Hi {name}, a new competitor opened nearby. "
            f"Want me to check how your listing compares and suggest improvements?"
        ),
        "supply_alert": (
            f"{name}, heads up — "
            + (f"{facts.get('trigger_alert_detail', 'a supply alert')} flagged. " if facts.get('trigger_alert_detail') else "a supply issue was flagged. ")
            + "Want me to pull the details and draft a customer notification?"
        ),
        "chronic_refill_due": (
            (f"Hi {customer_name}, " if customer_name else f"{name}, ")
            + "a refill is due soon. Want me to prepare the order and send a reminder?"
        ),
        "renewal_due": (
            f"Hi {name}, your subscription renews in {facts.get('sub_days_remaining', 'a few')} days. "
            f"Want me to review your plan options?"
        ),
        "milestone_reached": (
            f"Hi {name}, congratulations — you've hit a milestone! "
            f"Want me to draft a celebratory post for your profile?"
        ),
        "review_theme_emerged": (
            f"Hi {name}, a pattern emerged in your recent reviews"
            + (f": customers are mentioning '{facts.get('trigger_theme', '')}'" if facts.get('trigger_theme') else "")
            + ". Want me to show the details?"
        ),
    }
    return templates.get(kind, templates.get("recall", f"Hi {name}, checking in — anything I can help with?"))


def compose(
    category: str,
    merchant: dict,
    trigger: dict,
    customer: dict | None = None,
    category_context: dict | None = None,
) -> dict:
    voice = get_voice(category)

    merchant_facts = extract_merchant_facts(merchant)
    trigger_facts = extract_trigger_facts(trigger)
    customer_facts = extract_customer_facts(customer)
    category_facts = extract_category_facts(category_context)

    customer_scope_allowed = bool(customer) and customer.get("consent", True) is not False
    trigger_scope = trigger.get("scope", "merchant")
    is_customer_facing = customer_scope_allowed and trigger_scope == "customer"
    send_as = "merchant_on_behalf" if is_customer_facing else "vera"

    taboos = _get_taboos(category_context, category_facts)

    whitelist = build_fact_whitelist(merchant, trigger, customer, category_context)
    fallback_message = build_template_message(trigger, {**merchant_facts, **trigger_facts}, category_facts, customer_facts)

    display_name = _get_display_name(merchant_facts)
    trigger_kind = trigger.get("kind", "recall")

    cat_tone = category_facts.get("cat_tone", voice["tone"])
    cat_style = voice["style"]
    cat_avoid = voice["avoid"]
    if taboos:
        cat_avoid = list(set(cat_avoid + taboos))

    peer_stats_text = ""
    if category_facts.get("peer_avg_ctr"):
        peer_stats_text = f"Peer benchmarks: avg CTR {category_facts['peer_avg_ctr']}"
        if category_facts.get("peer_avg_rating"):
            peer_stats_text += f", avg rating {category_facts['peer_avg_rating']}"
        if category_facts.get("peer_avg_reviews"):
            peer_stats_text += f", avg reviews {category_facts['peer_avg_reviews']}"
        peer_stats_text += ". "

    merchant_perf_text = ""
    if merchant_facts.get("perf_views"):
        merchant_perf_text = f"Merchant performance (30d): views={merchant_facts.get('perf_views')}"
        if merchant_facts.get("perf_calls"):
            merchant_perf_text += f", calls={merchant_facts['perf_calls']}"
        if merchant_facts.get("perf_ctr"):
            merchant_perf_text += f", CTR={merchant_facts['perf_ctr']}"
        merchant_perf_text += ". "

    cust_agg_text = ""
    if merchant_facts.get("cust_total_unique_ytd"):
        cust_agg_text = f"Customer stats: {merchant_facts['cust_total_unique_ytd']} unique YTD"
        if merchant_facts.get("cust_lapsed_180d_plus"):
            cust_agg_text += f", {merchant_facts['cust_lapsed_180d_plus']} lapsed 180d+"
        if merchant_facts.get("cust_retention_6mo_pct"):
            cust_agg_text += f", {merchant_facts['cust_retention_6mo_pct']} 6mo retention"
        cust_agg_text += ". "

    signals_text = ""
    if merchant_facts.get("signals"):
        signals_text = f"Merchant signals: {', '.join(str(s) for s in merchant_facts['signals'])}. "

    offers_text = ""
    active_offers = merchant_facts.get("all_offers", [])
    if active_offers:
        offers_text = f"Active offers: {', '.join(o for o in active_offers if o)}. "

    digest_text = ""
    for i in range(3):
        title = category_facts.get(f"digest_{i}_title")
        if title:
            src = category_facts.get(f"digest_{i}_source", "")
            digest_text += f"Digest item: {title}"
            if src:
                digest_text += f" (source: {src})"
            summary = category_facts.get(f"digest_{i}_summary", "")
            if summary:
                digest_text += f" — {summary}"
            digest_text += ". "

    customer_text = ""
    if customer_facts:
        customer_text = f"Customer: {customer_facts.get('customer_name', 'unknown')}"
        if customer_facts.get("customer_state"):
            customer_text += f", state={customer_facts['customer_state']}"
        if customer_facts.get("last_visit"):
            customer_text += f", last visit={customer_facts['last_visit']}"
        if customer_facts.get("visits_total"):
            customer_text += f", total visits={customer_facts['visits_total']}"
        if customer_facts.get("customer_language"):
            customer_text += f", language={customer_facts['customer_language']}"
        if customer_facts.get("preferred_slots"):
            customer_text += f", prefers={customer_facts['preferred_slots']}"
        customer_text += ". "

    language_hint = ""
    langs = merchant_facts.get("languages", ["en"])
    if isinstance(langs, list) and "hi" in langs:
        language_hint = "Hindi-English code-mix is encouraged. "

    system_prompt = (
        f"You write ONE short WhatsApp-style message "
        f"{'on behalf of ' + merchant_facts.get('merchant_name', '') + ' to their customer' if is_customer_facing else 'from Vera (an AI growth assistant) to a ' + category + ' merchant'}. "
        f"Recipient: '{display_name}'"
        + (f" (customer: {customer_facts.get('customer_name', '')})" if is_customer_facing and customer_facts.get("customer_name") else "")
        + f". "
        f"Tone: {cat_tone}. Style: {cat_style}. "
        f"AVOID: {', '.join(cat_avoid)}. "
        f"NEVER include URLs. "
        f"{language_hint}"
        f"\n\nKNOWN FACTS (use ONLY these — invent NOTHING):\n"
        f"{merchant_perf_text}"
        f"{peer_stats_text}"
        f"{cust_agg_text}"
        f"{signals_text}"
        f"{offers_text}"
        f"{digest_text}"
        f"{customer_text}"
        f"Trigger data: {trigger_facts}. "
        f"\n\nSCORING DIMENSIONS — optimise for ALL:\n"
        f"1. SPECIFICITY: anchor on concrete verifiable facts (numbers, dates, sources) from the context above.\n"
        f"2. CATEGORY FIT: use domain vocabulary correctly ({cat_tone} tone).\n"
        f"3. MERCHANT FIT: personalise to THIS merchant's state, numbers, offers, name.\n"
        f"4. TRIGGER RELEVANCE: clearly communicate WHY NOW — the specific trigger reason.\n"
        f"5. ENGAGEMENT COMPULSION: use curiosity, loss aversion, social proof, effort externalisation, or reciprocity.\n"
        f"\nEnd with exactly ONE clear, low-effort call to action. "
        f"Keep the whole message under 50 words. "
        f"Do NOT start with 'I hope you're doing well' or similar preamble. "
        f"Return ONLY the message text, nothing else."
    )
    user_prompt = f"Trigger kind: '{trigger_kind}'. Write the message now."

    llm_draft = generate_message(system_prompt, user_prompt)

    if llm_draft:
        ok, _reason = passes_all_guardrails(llm_draft, whitelist, taboos)
        final_message = llm_draft if ok else fallback_message
    else:
        final_message = fallback_message

    trigger_id = trigger.get("id", trigger.get("trigger_id", trigger_kind))
    merchant_id = merchant_facts.get("merchant_id", "unknown")
    sup_key = trigger.get("suppression_key", f"{merchant_id}:{trigger_kind}:{trigger_id}")

    dimension_notes = []
    if merchant_perf_text:
        dimension_notes.append(f"perf data grounded ({merchant_facts.get('perf_views', '?')} views)")
    if peer_stats_text:
        dimension_notes.append("peer comparison available")
    if digest_text:
        dimension_notes.append("digest items referenced")
    if customer_text:
        dimension_notes.append("customer-personalised")

    rationale = (
        f"Trigger '{trigger_kind}' selected (priority-ranked). "
        f"Category voice: {category}/{cat_tone}. "
        f"{'Send as merchant on behalf (customer-scoped)' if is_customer_facing else 'Vera-to-merchant send'}. "
        f"Message grounded against {len(whitelist)} known fact values from "
        f"merchant+trigger"
        f"{'+customer' if customer_facts else ''}"
        f"{'+category' if category_facts else ''}"
        f" context. "
        + ("; ".join(dimension_notes) + ". " if dimension_notes else "")
    )

    return {
        "message": final_message,
        "body": final_message,
        "cta": "open_ended",
        "send_as": send_as,
        "suppression_key": sup_key,
        "rationale": rationale,
    }
