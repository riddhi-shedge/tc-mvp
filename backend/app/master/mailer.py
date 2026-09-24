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
from typing import Any, Callable, Protocol


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
    def send(self, *, to: str, subject: str, body: str, org_id: str = "") -> SentMessage: ...


def _env_allowlist() -> set[str]:
    raw = os.environ.get("SEND_ALLOWLIST", "")
    return {a.strip().lower() for a in raw.split(",") if a.strip()}


class PostmarkMailer:
    """Real Postmark send — guarded, fails closed.

    Recipient policy (Track A5) is layered, and can only NARROW:
      * The org's own settings row: mode 'open' allows any recipient; mode
        'allowlist' allows only its listed addresses.
      * No settings row yet: legacy/dev behavior — env SEND_ALLOWLIST governs;
        with the env unset too, every send is refused (fail closed).
      * The env SEND_ALLOWLIST, when set, ALWAYS also applies (a global
        tighten for dev/demo deployments — it can never widen an org's list).
    """

    def __init__(
        self, settings_lookup: "Callable[[str], dict[str, Any] | None] | None" = None
    ) -> None:
        # Injectable for tests; lazily resolves to the org_settings table.
        self._settings_lookup = settings_lookup

    def _org_settings(self, org_id: str) -> dict[str, Any] | None:
        if not org_id:
            return None
        lookup = self._settings_lookup
        try:
            if lookup is None:
                from app.master.org_repo import SupabaseOrgsRepo

                lookup = SupabaseOrgsRepo().get_settings
                self._settings_lookup = lookup
            return lookup(org_id)
        except Exception:
            return None  # outage/misconfig reads as "no row" -> the stricter path

    def _check_recipient(self, to: str, org_id: str) -> None:
        to_l = to.lower()
        env_list = _env_allowlist()
        settings = self._org_settings(org_id)
        if settings is None:
            # Legacy / unconfigured org: the env list is the only permission.
            if to_l not in env_list:
                raise RecipientNotAllowed(
                    "Recipient is not on the verified-address allowlist. "
                    "Add them in workspace settings."
                )
            return
        if str(settings.get("send_mode")) != "open":
            org_list = {
                str(a).strip().lower() for a in (settings.get("send_allowlist") or [])
            }
            if to_l not in org_list:
                raise RecipientNotAllowed(
                    "Recipient is not on this workspace's send allowlist."
                )
        if env_list and to_l not in env_list:
            raise RecipientNotAllowed(
                "Recipient is outside this deployment's global send allowlist."
            )

    def send(self, *, to: str, subject: str, body: str, org_id: str = "") -> SentMessage:
        if os.environ.get("SEND_ENABLED", "false").lower() != "true":
            raise SendDisabled(
                "Outbound email is disabled (SEND_ENABLED != true). No message was sent."
            )
        self._check_recipient(to, org_id)
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
