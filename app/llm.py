"""
One tiny client that talks to whichever FREE LLM provider you configure in
.env — Groq, Google Gemini, or OpenRouter. All three now speak the
OpenAI-compatible chat-completions format, so we only need one code path.

Nothing here is required to run the app or the tests: if LLM_API_KEY is
empty, generate_message() returns None and compose.py falls back to a
deterministic template. That means you can build and test the whole flow
before you've even signed up for an API key.

Get a free key from ONE of:
  Groq        -> https://console.groq.com/keys           (fastest, great default)
  Gemini      -> https://aistudio.google.com/apikey        (biggest context window)
  OpenRouter  -> https://openrouter.ai/keys                 (most model variety)
"""

import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from openai import OpenAI
except ImportError:  # keeps the app importable even before `pip install` runs
    OpenAI = None  # type: ignore

PROVIDER_CONFIG = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "openai/gpt-oss-120b",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-oss-120bt:free",
    },
}


def _get_client_and_model():
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    cfg = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["groq"])
    model = os.getenv("LLM_MODEL", "").strip() or cfg["default_model"]

    if not api_key or OpenAI is None:
        return None, model
    client = OpenAI(base_url=cfg["base_url"], api_key=api_key)
    return client, model


def generate_message(system_prompt: str, user_prompt: str, timeout: float = 12.0) -> Optional[str]:
    """Returns the model's reply text, or None if no key is set / the call fails.

    The `timeout` default (12s) is intentionally well under the judge's 30s
    endpoint timeout, leaving headroom for guardrail checks + network time.
    """
    client, model = _get_client_and_model()
    if client is None:
        return None

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=300,
            timeout=timeout,
        )
        text = resp.choices[0].message.content
        return text.strip() if text else None
    except Exception as exc:  # network hiccup, rate limit, bad key, etc.
        print(f"[llm] generation failed, falling back to template: {exc}")
        return None
