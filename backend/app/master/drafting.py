"""Real lender-draft generation (part b, Claude) — Prompt 6.

Given the deal state, Claude drafts a specific lender STATUS REQUEST and a short
WHY. Rule 2: wiring/payment details are never included or requested. Rule 1: this
is a plain email, never a C.A.R. or contingency-removal form. Rule 5: gated by the
same ZDR/synthetic gate as extraction — deal state is synthetic today, and no
real client data may be sent to the model until ZDR is confirmed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from app.common.zdr import check_zdr_gate


class DraftFailed(Exception):
    """The drafting service failed. Generic — no deal content (Rule 5)."""


@dataclass(frozen=True)
class DraftContext:
    property_address: str | None
    lender_name: str | None
    loan_deadline: str | None  # ISO date or None
    loan_status_note: str | None  # e.g. "loan approval not yet confirmed"


@dataclass(frozen=True)
class LenderDraft:
    subject: str
    body: str
    why: str


class Drafter(Protocol):
    def draft_lender_status(self, ctx: DraftContext) -> LenderDraft: ...


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["subject", "body", "why"],
    "additionalProperties": False,
}


def _prompt(ctx: DraftContext) -> str:
    return (
        "You are a transaction coordinator drafting a short, professional email to "
        "the lender/loan officer on a California residential real-estate deal, "
        "asking for a status update.\n\n"
        "Rules:\n"
        "1. NEVER mention, request, or include wiring instructions, bank account "
        "numbers, routing numbers, or any payment-transfer details.\n"
        "2. Do NOT attach or reproduce any C.A.R. form or contingency-removal "
        "document — this is a plain status-request email.\n"
        "3. Keep it concise and specific to this deal.\n"
        "4. 'why' is a one-sentence internal rationale (not shown to the lender) "
        "explaining why this follow-up is being sent now.\n\n"
        f"Deal context:\n"
        f"- Property: {ctx.property_address or '(unknown)'}\n"
        f"- Lender/loan officer: {ctx.lender_name or '(unknown)'}\n"
        f"- Loan contingency deadline: {ctx.loan_deadline or '(not set)'}\n"
        f"- Status note: {ctx.loan_status_note or 'checking in on loan progress'}\n"
    )


class ClaudeDrafter:
    def draft_lender_status(self, ctx: DraftContext) -> LenderDraft:
        check_zdr_gate()
        import anthropic

        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("DRAFTING_MODEL", "claude-sonnet-5")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2000,
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
                messages=[{"role": "user", "content": _prompt(ctx)}],
            )
        except anthropic.APIStatusError as exc:
            raise DraftFailed(f"drafting service error (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise DraftFailed("drafting service unreachable") from exc
        if response.stop_reason == "refusal":
            raise DraftFailed("drafting request was refused by the model")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise DraftFailed("drafting returned no output")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise DraftFailed("drafting returned unparseable output") from exc
        return LenderDraft(
            subject=str(data["subject"]), body=str(data["body"]), why=str(data["why"])
        )
