"""
Request/response schemas for the Vera Challenge bot.

⚠️ IMPORTANT: These field names are our BEST GUESS based on the public
challenge microsite (the /v1/context example shown on the "Testing" tab).
The real field names for /v1/tick, /v1/reply, and /v1/metadata live in
`challenge-testing-brief.md` and `api-call-examples.md` inside the official
zip (Package tab -> "Download challenge zip"). Before you submit:

    1. Download the real zip.
    2. Open api-call-examples.md and challenge-testing-brief.md.
    3. Rename any field below that doesn't match exactly.

Because every field is defined in ONE place (this file), renaming a field
here automatically fixes it everywhere else in the app.
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ---- POST /v1/context --------------------------------------------------
class ContextPush(BaseModel):
    scope: Literal["merchant", "customer", "trigger", "category"]
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


class ContextAck(BaseModel):
    accepted: bool
    ack_id: str
    stored_at: str
    reason: Optional[str] = None
    current_version: Optional[int] = None


# ---- POST /v1/tick -------------------------------------------------------
class TickRequest(BaseModel):
    now: Optional[str] = None
    available_triggers: list[str] = Field(default_factory=list)
    merchant_id: Optional[str] = None
    trigger_id: Optional[str] = None
    customer_id: Optional[str] = None


class ComposeResult(BaseModel):
    message: str
    cta: str
    send_as: str
    suppression_key: str
    rationale: str


# ---- POST /v1/reply -------------------------------------------------------
class ReplyRequest(BaseModel):
    conversation_id: Optional[str] = None
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: Optional[str] = None
    message: Optional[str] = None
    received_at: Optional[str] = None
    turn_number: Optional[int] = None
    incoming_text: Optional[str] = None


class ReplyResult(BaseModel):
    message: str
    cta: Optional[str] = None
    send_as: str
    suppression_key: Optional[str] = None
    rationale: str
    intent_detected: str


# ---- GET /v1/metadata -------------------------------------------------------
class Metadata(BaseModel):
    name: str
    version: str
    capabilities: list[str]
    categories_supported: list[str]
