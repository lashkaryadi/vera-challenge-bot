"""
Category voice profiles + trigger priority.

This is where "category fit" (rubric dimension 3) and part of
"decision quality" (rubric dimension 1) get their points. Tune these
freely — this is the highest-leverage file in the whole project.
"""

CATEGORY_VOICE = {
    "dentist": {
        "tone": "clinical",
        "style": "Calm, professional, trust-first. Lead with a health/hygiene "
        "reason, not just a discount. Sound like a helpful clinic coordinator.",
        "avoid": ["over-selling", "excess emojis", "casual slang"],
    },
    "salon": {
        "tone": "visual",
        "style": "Trendy, warm, a little playful. Talk about looks, styling, "
        "self-care and 'treat yourself' energy.",
        "avoid": ["clinical language", "dry corporate tone"],
    },
    "restaurant": {
        "tone": "sensory",
        "style": "Appetite-driven, food-forward, time-boxed urgency "
        "('today', 'this weekend').",
        "avoid": ["clinical language", "long paragraphs"],
    },
    "gym": {
        "tone": "motivational",
        "style": "Energetic, progress-and-results focused, short punchy "
        "sentences, light urgency.",
        "avoid": ["passive language", "overly formal tone"],
    },
    "pharmacy": {
        "tone": "utility-first",
        "style": "Quick, transactional, convenience/availability-focused. "
        "Minimal fluff, get to the point in the first sentence.",
        "avoid": ["long build-up", "hard-sell language"],
    },
}

# Used by compose.pick_trigger() when more than one trigger is live for a
# merchant at once. Higher number = acted on first.
#   dip      -> revenue is actively being lost right now (most urgent)
#   spike    -> a time-sensitive demand opportunity
#   festival -> time-boxed seasonal moment
#   recall   -> evergreen win-back, no clock ticking
#   research -> evergreen conversion nudge, softest signal
TRIGGER_PRIORITY = {
    "dip": 5,
    "perf_dip": 5,
    "seasonal_perf_dip": 5,
    "supply_alert": 5,
    "chronic_refill_due": 5,
    "spike": 4,
    "perf_spike": 4,
    "active_planning_intent": 4,
    "renewal_due": 4,
    "festival": 3,
    "festival_upcoming": 3,
    "recall": 2,
    "recall_due": 2,
    "customer_lapsed_soft": 2,
    "customer_lapsed_hard": 2,
    "trial_followup": 2,
    "competitor_opened": 2,
    "research": 1,
    "research_digest": 1,
    "cde_opportunity": 1,
    "milestone_reached": 1,
    "review_theme_emerged": 1,
}

DEFAULT_CATEGORY = "pharmacy"


def get_voice(category: str) -> dict:
    return CATEGORY_VOICE.get(category, CATEGORY_VOICE[DEFAULT_CATEGORY])
