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


# ---- Generalized, personalized messages to any party ------------------------


@dataclass(frozen=True)
class MessageContext:
    purpose: str
    recipient_name: str | None
    recipient_role: str | None
    property_address: str | None
    buyer_names: str | None
    seller_names: str | None
    tc_name: str | None
    key_dates: tuple[tuple[str, str], ...]  # (label, ISO date)
    note: str | None = None


@dataclass(frozen=True)
class MessageDraft:
    subject: str
    body: str
    why: str


# Purpose -> the specific ask the email should make. The model personalizes the
# rest from the deal context (who the buyers are, the property, the dates).
PURPOSES: dict[str, str] = {
    "lender_status": "Ask the lender / loan officer for a status update on the loan and "
    "appraisal, ahead of the loan-contingency deadline.",
    "appraisal_status": "Ask about the status of the appraisal ahead of the "
    "appraisal-contingency deadline.",
    "inspection_schedule": "Coordinate scheduling the property inspection before the "
    "inspection-contingency deadline.",
    "disclosure_reminder": "Remind the listing side about any outstanding seller "
    "disclosures needed before closing.",
    "escrow_checkin": "Check in with escrow on deal status — e.g. earnest-money deposit "
    "received, escrow opened, on track to close.",
    "intro": "Introduce yourself as the transaction coordinator and offer to be the point "
    "of contact for paperwork and deadlines on this transaction.",
    "general": "A brief, professional, deal-specific status check-in relevant to this "
    "recipient's role on the transaction.",
}


def _message_prompt(ctx: MessageContext) -> str:
    dates = "; ".join(f"{label}: {iso}" for label, iso in ctx.key_dates) or "(none on file)"
    role = f" ({ctx.recipient_role.replace('_', ' ')})" if ctx.recipient_role else ""
    return (
        f"You are {ctx.tc_name or 'the transaction coordinator (TC)'}, coordinating a "
        "California residential real-estate transaction after the purchase agreement was "
        "signed. Draft a short, professional, SPECIFIC email — the way a real estate "
        "transaction coordinator actually writes.\n\n"
        f"Recipient: {ctx.recipient_name or 'the recipient'}{role}.\n"
        f"Purpose: {PURPOSES.get(ctx.purpose, PURPOSES['general'])}\n\n"
        "How to write it:\n"
        "- Open by identifying yourself as the transaction coordinator and naming the deal "
        "(the buyers and the property address) so the recipient has immediate context.\n"
        "- Reference the specific, relevant date(s) from the context below.\n"
        "- Make ONE clear, courteous ask tied to the purpose.\n"
        "- Concise (a few sentences), friendly, professional, and signature-ready.\n\n"
        "Rules:\n"
        "1. NEVER mention or request wiring instructions, bank-account or routing numbers, "
        "or any payment-transfer details.\n"
        "2. Do NOT reproduce or attach any C.A.R. form or contingency-removal document — a "
        "plain email only.\n"
        "3. Use ONLY the facts below — never invent names, dates, amounts, or terms.\n"
        "4. 'why' is a one-sentence INTERNAL rationale (not shown to the recipient).\n\n"
        "Deal context:\n"
        f"- Property: {ctx.property_address or '(unknown)'}\n"
        f"- Buyer(s): {ctx.buyer_names or '(unknown)'}\n"
        f"- Seller(s): {ctx.seller_names or '(unknown)'}\n"
        f"- Key dates: {dates}\n"
        f"- Note: {ctx.note or '(none)'}\n"
    )


class Drafter(Protocol):
    def draft_lender_status(self, ctx: DraftContext) -> LenderDraft: ...

    def draft_message(self, ctx: MessageContext) -> MessageDraft: ...


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
    def _generate(self, prompt: str) -> dict[str, Any]:
        check_zdr_gate()
        import anthropic

        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("DRAFTING_MODEL", "claude-sonnet-5")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2000,
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
                messages=[{"role": "user", "content": prompt}],
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
            return json.loads(text)
        except ValueError as exc:
            raise DraftFailed("drafting returned unparseable output") from exc

    def draft_lender_status(self, ctx: DraftContext) -> LenderDraft:
        data = self._generate(_prompt(ctx))
        return LenderDraft(
            subject=str(data["subject"]), body=str(data["body"]), why=str(data["why"])
        )

    def draft_message(self, ctx: MessageContext) -> MessageDraft:
        data = self._generate(_message_prompt(ctx))
        return MessageDraft(
            subject=str(data["subject"]), body=str(data["body"]), why=str(data["why"])
        )
