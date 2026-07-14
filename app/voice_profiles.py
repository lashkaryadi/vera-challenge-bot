"""
Category voice profiles + trigger priority.

This drives "category fit" (rubric dimension 3) and "decision quality" (rubric dimension 1).
"""

CATEGORY_VOICE = {
    "dentist": {
        "tone": "peer_clinical",
        "style": "Calm, professional, trust-first. Lead with a health/hygiene "
        "reason, not just a discount. Sound like a helpful clinic coordinator. "
        "Technical terms welcome (fluoride varnish, caries, recall).",
        "avoid": ["over-selling", "excess emojis", "casual slang", "cure", "guaranteed", "100% safe"],
    },
    "dentists": {
        "tone": "peer_clinical",
        "style": "Calm, professional, trust-first. Lead with a health/hygiene "
        "reason, not just a discount. Sound like a helpful clinic coordinator. "
        "Technical terms welcome (fluoride varnish, caries, recall).",
        "avoid": ["over-selling", "excess emojis", "casual slang", "cure", "guaranteed", "100% safe"],
    },
    "salon": {
        "tone": "warm_visual",
        "style": "Trendy, warm, a little playful. Talk about looks, styling, "
        "self-care and 'treat yourself' energy. Fellow-operator register.",
        "avoid": ["clinical language", "dry corporate tone"],
    },
    "salons": {
        "tone": "warm_visual",
        "style": "Trendy, warm, a little playful. Talk about looks, styling, "
        "self-care and 'treat yourself' energy. Fellow-operator register.",
        "avoid": ["clinical language", "dry corporate tone"],
    },
    "restaurant": {
        "tone": "sensory_operator",
        "style": "Appetite-driven, food-forward, operator-to-operator language "
        "(covers, AOV, delivery radius). Time-boxed urgency.",
        "avoid": ["clinical language", "long paragraphs"],
    },
    "restaurants": {
        "tone": "sensory_operator",
        "style": "Appetite-driven, food-forward, operator-to-operator language "
        "(covers, AOV, delivery radius). Time-boxed urgency.",
        "avoid": ["clinical language", "long paragraphs"],
    },
    "gym": {
        "tone": "coach_motivational",
        "style": "Energetic, progress-and-results focused, short punchy "
        "sentences, coach-to-operator tone. Use terms like ad spend, conversion, members.",
        "avoid": ["passive language", "overly formal tone", "shame", "guilt-trip"],
    },
    "gyms": {
        "tone": "coach_motivational",
        "style": "Energetic, progress-and-results focused, short punchy "
        "sentences, coach-to-operator tone. Use terms like ad spend, conversion, members.",
        "avoid": ["passive language", "overly formal tone", "shame", "guilt-trip"],
    },
    "pharmacy": {
        "tone": "trustworthy_precise",
        "style": "Quick, transactional, convenience/availability-focused. "
        "Precise with molecule names, batch numbers, dosages. Minimal fluff.",
        "avoid": ["long build-up", "hard-sell language", "medical claims"],
    },
    "pharmacies": {
        "tone": "trustworthy_precise",
        "style": "Quick, transactional, convenience/availability-focused. "
        "Precise with molecule names, batch numbers, dosages. Minimal fluff.",
        "avoid": ["long build-up", "hard-sell language", "medical claims"],
    },
}

TRIGGER_PRIORITY = {
    "supply_alert": 6,
    "dip": 5,
    "perf_dip": 5,
    "seasonal_perf_dip": 5,
    "chronic_refill_due": 5,
    "spike": 4,
    "perf_spike": 4,
    "active_planning_intent": 4,
    "renewal_due": 4,
    "ipl_match_today": 4,
    "festival": 3,
    "festival_upcoming": 3,
    "weather_heatwave": 3,
    "local_news_event": 3,
    "bridal_followup": 3,
    "recall": 2,
    "recall_due": 2,
    "customer_lapsed_soft": 2,
    "customer_lapsed_hard": 2,
    "trial_followup": 2,
    "competitor_opened": 2,
    "appointment_tomorrow": 2,
    "dormant_with_vera": 2,
    "curious_ask_due": 2,
    "research": 1,
    "research_digest": 1,
    "research_digest_release": 1,
    "category_research_digest_release": 1,
    "cde_opportunity": 1,
    "milestone_reached": 1,
    "review_theme_emerged": 1,
    "regulation_change": 1,
    "category_trend_movement": 1,
    "scheduled_recurring": 1,
}

DEFAULT_CATEGORY = "pharmacy"


def get_voice(category: str) -> dict:
    return CATEGORY_VOICE.get(category, CATEGORY_VOICE.get(DEFAULT_CATEGORY, CATEGORY_VOICE["pharmacy"]))
