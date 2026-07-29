"""Test doubles for the mail + drafting seams — nothing leaves the system."""

from __future__ import annotations

from app.master.drafting import DraftContext, LenderDraft, MessageContext, MessageDraft
from app.master.mailer import SentMessage


class FakeMailer:
    """Records sends instead of delivering. Optionally simulates a guard/failure."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.sent: list[dict[str, str]] = []
        self._raises = raises

    def send(self, *, to: str, subject: str, body: str) -> SentMessage:
        if self._raises is not None:
            raise self._raises
        self.sent.append({"to": to, "subject": subject, "body": body})
        return SentMessage(provider_message_id=f"fake-{len(self.sent)}")


class FakePartyAccessIssuer:
    """Returns a deterministic token instead of provisioning a Supabase user."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def issue(
        self, *, party_id: str, transaction_id: str, email: str | None,
        tier: str = "receiving_end",
    ) -> dict[str, str]:
        self.calls.append(
            {"party_id": party_id, "transaction_id": transaction_id, "email": email, "tier": tier}
        )
        return {"party_id": party_id, "access_token": f"fake-token-{party_id}"}


class FakeDrafter:
    """Returns a canned lender draft referencing the context — no model call."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.override: LenderDraft | None = None  # force a specific draft (tests)
        self.calls: list[DraftContext] = []

    def draft_lender_status(self, ctx: DraftContext) -> LenderDraft:
        if self._raises is not None:
            raise self._raises
        self.calls.append(ctx)
        if self.override is not None:
            return self.override
        deadline = ctx.loan_deadline or "the upcoming deadline"
        return LenderDraft(
            subject=f"Loan status — {ctx.property_address or 'the property'}",
            body=(
                f"Hi {ctx.lender_name or 'there'}, checking in on loan progress for "
                f"{ctx.property_address or 'the deal'} ahead of {deadline}. Could you "
                "share the current application status? Thanks."
            ),
            why=f"Loan contingency ({deadline}) is approaching and status isn't confirmed.",
        )

    def draft_message(self, ctx: MessageContext) -> MessageDraft:
        if self._raises is not None:
            raise self._raises
        self.calls.append(ctx)
        who = ctx.recipient_name or "there"
        buyers = ctx.buyer_names or "the buyers"
        prop = ctx.property_address or "the property"
        return MessageDraft(
            subject=f"{ctx.purpose.replace('_', ' ').title()} — {prop}",
            body=(
                f"Hi {who}, I'm {ctx.tc_name or 'the transaction coordinator'} on the "
                f"purchase of {prop} by {buyers}. {PURPOSES_HINT.get(ctx.purpose, '')} "
                "Thanks!"
            ),
            why=f"{ctx.purpose} for {who} on {prop}.",
        )


# Short canned hints so the fake body varies by purpose (mirrors the real intent).
PURPOSES_HINT = {
    "lender_status": "Could you confirm the loan and appraisal are on track?",
    "inspection_schedule": "Can we get the inspection scheduled this week?",
    "disclosure_reminder": "Following up on the outstanding seller disclosures.",
    "escrow_checkin": "Checking that the deposit is in and escrow is open.",
    "intro": "I'll be your point of contact for paperwork and deadlines.",
    "general": "Just checking in on status.",
}


class FakeAssistant:
    """Deterministic grounded Q&A over the built context — no model call. Returns
    a line that matches a keyword from the question, else the not-found reply."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, context: str, question: str) -> str:
        self.calls.append({"context": context, "question": question})
        words = [w for w in question.lower().replace("?", "").split() if len(w) > 3]
        for line in context.splitlines():
            low = line.strip().lower()
            if low and any(w in low for w in words):
                return f"From this deal: {line.strip('- ').strip()}"
        return "I couldn't find that in this deal's documents."
