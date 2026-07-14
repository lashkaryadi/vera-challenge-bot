"""
Guardrails — protects Specificity and Decision quality scores.

Checks: number grounding, single CTA, length, URL ban, category taboos.
"""

import re

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _clean(text: str) -> str:
    return text.replace(",", "")


def extract_numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(_clean(text)))


def _deep_extract_numbers(obj, whitelist: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _deep_extract_numbers(v, whitelist)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _deep_extract_numbers(item, whitelist)
    else:
        whitelist |= extract_numbers(str(obj))


def build_fact_whitelist(*fact_sources) -> set[str]:
    whitelist: set[str] = set()
    for source in fact_sources:
        if source is None:
            continue
        _deep_extract_numbers(source, whitelist)
    return whitelist


def is_grounded(message: str, whitelist: set[str]) -> tuple[bool, list[str]]:
    used = extract_numbers(message)
    invented = sorted(n for n in used if n not in whitelist)
    return (len(invented) == 0, invented)


def has_single_cta(message: str) -> bool:
    return message.count("?") <= 1


def within_length(message: str, max_words: int = 60) -> bool:
    return len(message.split()) <= max_words


def has_url(message: str) -> bool:
    return bool(URL_RE.search(message))


def has_taboo_words(message: str, taboos: list[str] | None) -> tuple[bool, list[str]]:
    if not taboos:
        return False, []
    lower = message.lower()
    found = [t for t in taboos if t.lower() in lower]
    return (len(found) > 0, found)


def passes_all_guardrails(
    message: str,
    whitelist: set[str],
    taboos: list[str] | None = None,
) -> tuple[bool, str]:
    if has_url(message):
        return False, "message contains a URL (hard penalty)"
    grounded, invented = is_grounded(message, whitelist)
    if not grounded:
        return False, f"invented numbers not in context: {invented}"
    if not has_single_cta(message):
        return False, "more than one question/CTA in the message"
    if not within_length(message):
        return False, "message too long"
    has_taboo, found_taboos = has_taboo_words(message, taboos)
    if has_taboo:
        return False, f"message contains taboo words: {found_taboos}"
    return True, "ok"
