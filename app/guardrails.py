"""
Guardrails: this is what protects your "Specificity" and "Decision quality"
scores. The FAQ on the challenge site says it plainly:

    "Bots that pattern-match the simulator will fail. Bots that ground
    every output in the context they've actually been given will not."

So: before any LLM-written message goes out, we check that every number in
it actually came from the context we were given. If it didn't, we reject
the LLM draft and fall back to a deterministic template instead of risking
a fabricated claim.
"""

import re

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _clean(text: str) -> str:
    return text.replace(",", "")


def extract_numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(_clean(text)))


def build_fact_whitelist(*fact_dicts: dict) -> set[str]:
    """Flatten every number found across the given fact dictionaries into an allow-list."""
    whitelist: set[str] = set()
    for facts in fact_dicts:
        for value in facts.values():
            whitelist |= extract_numbers(str(value))
    return whitelist


def is_grounded(message: str, whitelist: set[str]) -> tuple[bool, list[str]]:
    """Return (True, []) if every number in `message` is in the whitelist."""
    used = extract_numbers(message)
    invented = sorted(n for n in used if n not in whitelist)
    return (len(invented) == 0, invented)


def has_single_cta(message: str) -> bool:
    """Hard constraint from the brief: one clear CTA per send."""
    return message.count("?") <= 1


def within_length(message: str, max_words: int = 45) -> bool:
    return len(message.split()) <= max_words


def passes_all_guardrails(message: str, whitelist: set[str]) -> tuple[bool, str]:
    grounded, invented = is_grounded(message, whitelist)
    if not grounded:
        return False, f"invented numbers not in context: {invented}"
    if not has_single_cta(message):
        return False, "more than one question/CTA in the message"
    if not within_length(message):
        return False, "message too long"
    return True, "ok"
