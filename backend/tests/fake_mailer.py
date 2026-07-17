"""Test doubles for the mail + drafting seams — nothing leaves the system."""

from __future__ import annotations

from app.master.drafting import DraftContext, LenderDraft
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

    def issue(self, *, party_id: str, transaction_id: str, email: str | None) -> dict[str, str]:
        self.calls.append(
            {"party_id": party_id, "transaction_id": transaction_id, "email": email}
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
