# Vera Challenge Bot — starter kit

A working starting point for magicpin's **Vera AI Challenge**. It implements
the `compose(category, merchant, trigger, customer?)` engine the brief asks
for, wrapped in the 5 HTTP endpoints the judge harness calls.

> Full plain-language strategy guide (workflow, scoring breakdown, free AI
> tools, deploy walkthrough, day-by-day plan) is in the accompanying PDF.
> This file is just the quick technical start.

## ⚠️ Before you touch anything — read this

This code was written from the **public challenge microsite** (Challenge /
Rubric / Testing / Package / Submit / FAQ tabs), not from the actual zip
(`challenge-brief.md`, `challenge-testing-brief.md`, `api-call-examples.md`,
the dataset). The overall shape (endpoints, `/v1/context` payload, the 5
rubric dimensions, the 4 compose() inputs) is confirmed from the site
itself — but exact field names inside `/v1/tick` and `/v1/reply` are my
best inference, not copied from the real spec.

**Step 0, before writing a single line of your own logic:**
1. Download the real challenge zip (Package tab → "Download challenge zip").
2. Open `api-call-examples.md` and `challenge-testing-brief.md`.
3. Compare every field name against `app/models.py` in this project.
4. Fix any mismatches — `models.py` is the *only* file you need to edit for
   that, since every other file imports its shapes from there.

## Quick start (5 minutes)

```bash
python3 -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt

# Run the local test suite (works with NO API key — uses template fallback)
python tests/test_flow.py

# Start the server
uvicorn app.main:app --reload --port 8000

# In another terminal:
curl http://localhost:8000/v1/healthz
```

## Add a free LLM (optional but recommended for higher scores)

```bash
cp .env.example .env
```

Edit `.env` and set:
```
LLM_PROVIDER=groq
LLM_API_KEY=paste_your_key_here
```

Get a free key (no credit card) from **one** of:
| Provider | Get a key | Why pick it |
|---|---|---|
| Groq | https://console.groq.com/keys | Fastest — best for staying under the judge's 30s timeout |
| Gemini | https://aistudio.google.com/apikey | Huge context window, strong reasoning |
| OpenRouter | https://openrouter.ai/keys | One key, many free models, good fallback |

Install `python-dotenv` is already in requirements.txt — load it at the top
of `main.py` if you want `.env` picked up automatically:
```python
from dotenv import load_dotenv
load_dotenv()
```
(or just `export LLM_PROVIDER=groq` and `export LLM_API_KEY=...` in your shell
before running `uvicorn`.)

**No key set?** The app still works — `compose()` automatically falls back
to a deterministic, always-grounded template. That's a legitimate strategy
on its own (100% deterministic = full marks on that part of "Decision
quality"), you're just trading away some of the "Engagement compulsion"
polish an LLM can add.

## Project layout

```
vera-challenge-bot/
├── app/
│   ├── main.py            # FastAPI app + the 5 endpoints
│   ├── models.py          # ⚠️ edit this first — request/response field names
│   ├── store.py           # in-memory versioned context store
│   ├── compose.py         # the compose() engine (decision + generation)
│   ├── voice_profiles.py  # per-category tone rules + trigger priority
│   ├── guardrails.py      # fact-grounding + single-CTA validation
│   └── llm.py             # Groq / Gemini / OpenRouter client (one code path)
├── tests/test_flow.py     # local end-to-end simulation, no API key needed
├── requirements.txt
├── .env.example
└── README.md
```
