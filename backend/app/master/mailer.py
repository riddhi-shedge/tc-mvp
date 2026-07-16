"""Outbound email seam (part b) — the ONLY place a message leaves the system.

Rule 3: this is called exclusively from the approve-and-send path, after a human
Approval is recorded. Rule 2: the caller must never put wiring/payment details in
a message; nothing here inspects or forwards such data.

The real PostmarkMailer is GUARDED: it refuses to send unless SEND_ENABLED=true
AND the recipient is on SEND_ALLOWLIST (verified addresses). Until then — and in
all tests — nothing is delivered. Postmark is pending production approval (§16),
so real sends only work to verified addresses regardless.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class SendDisabled(Exception):
    """Real sending is off (SEND_ENABLED != true). Fails closed."""


class RecipientNotAllowed(Exception):
    """The recipient is not on the verified-address allowlist."""


class SendFailed(Exception):
    """The provider rejected or could not deliver. Generic — no message content."""


@dataclass(frozen=True)
class SentMessage:
    provider_message_id: str


class Mailer(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> SentMessage: ...


def _allowlist() -> set[str]:
    raw = os.environ.get("SEND_ALLOWLIST", "")
    return {a.strip().lower() for a in raw.split(",") if a.strip()}


class PostmarkMailer:
    """Real Postmark send — guarded, fails closed."""

    def send(self, *, to: str, subject: str, body: str) -> SentMessage:
        if os.environ.get("SEND_ENABLED", "false").lower() != "true":
            raise SendDisabled(
                "Outbound email is disabled (SEND_ENABLED != true). No message was sent."
            )
        if to.lower() not in _allowlist():
            raise RecipientNotAllowed(
                "Recipient is not on the verified-address allowlist (SEND_ALLOWLIST)."
            )
        token = os.environ.get("POSTMARK_SERVER_TOKEN")
        sender = os.environ.get("POSTMARK_FROM_EMAIL")
        if not token or not sender:
            raise SendDisabled("Postmark is not configured (token/from address missing).")

        import httpx

        try:
            resp = httpx.post(
                "https://api.postmarkapp.com/email",
                headers={
                    "X-Postmark-Server-Token": token,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "From": sender,
                    "To": to,
                    "Subject": subject,
                    "TextBody": body,
                    "MessageStream": "outbound",
                },
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise SendFailed(f"email provider unreachable ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            # No message content in the error (Rule 5 logging discipline).
            raise SendFailed(f"email provider rejected the send (HTTP {resp.status_code})")
        return SentMessage(provider_message_id=str(resp.json().get("MessageID", "")))
