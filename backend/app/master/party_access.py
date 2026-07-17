"""Receiving-end access tokens (Prompt 7, §8) — a scoped magic-link credential.

A receiving-end party (inspector/appraiser/contractor) is the one non-TC actor
who touches Supabase directly. Its identity is a genuine Supabase-issued session
whose admin-set `app_metadata.party_id` RLS keys off — so the party can mark
exactly their own task done and read nothing else (enforced in the DB).

We use `app_metadata` (admin-only; a party can't set it on themselves) rather
than a hand-minted token, because the project signs with rotating asymmetric
keys — a shared-secret HS256 token would not verify. Issuance is a dependency so
the API is unit-tested against a fake without provisioning real auth users.
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Protocol


class AccessIssuerNotConfigured(Exception):
    """Supabase env (URL + service role + anon key) is not set — cannot issue."""


class AccessIssuanceFailed(Exception):
    """The auth provider failed to provision the party or mint a session."""


def _is_already_registered(exc: Exception) -> bool:
    """True only for the 'this email already has a user' case — so other auth
    failures (rate limits, validation) surface instead of being swallowed."""
    code = getattr(exc, "code", "") or ""
    return code in {"email_exists", "user_already_exists"} or "already" in str(exc).lower()


class PartyAccessIssuer(Protocol):
    def issue(
        self, *, party_id: str, transaction_id: str, email: str | None
    ) -> dict[str, Any]:
        """Return {"party_id", "access_token"} for a receiving-end party."""
        ...


class SupabasePartyAccessIssuer:
    """Provisions (idempotently) a Supabase auth user for the party with
    `app_metadata.party_id` and returns a real session token for it.

    The returned access token is a short-lived Supabase session JWT (it expires
    on its own; we do not hand back a refresh token). Reissuing rotates the auth
    user's password but, JWTs being stateless, does not revoke an already-issued
    access token before its expiry — acceptable for the MVP's short TTL."""

    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL")
        self._service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY")
        # Auth-only address for parties without their own email. Never mailed
        # from here; the real magic-link delivery is a later, send-gated step.
        self._email_domain = os.environ.get("PARTY_AUTH_EMAIL_DOMAIN", "party.tc.invalid")

    def _auth_email(self, *, party_id: str, email: str | None) -> str:
        return email or f"party+{party_id}@{self._email_domain}"

    def issue(
        self, *, party_id: str, transaction_id: str, email: str | None
    ) -> dict[str, Any]:
        if not (self._url and self._service_key and self._anon_key):
            raise AccessIssuerNotConfigured(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY not set"
            )
        import httpx
        from supabase import create_client
        from supabase_auth.errors import AuthApiError

        admin = create_client(self._url, self._service_key)
        auth_email = self._auth_email(party_id=party_id, email=email)
        password = secrets.token_urlsafe(32)
        app_metadata = {"party_id": party_id, "transaction_id": transaction_id}

        try:
            try:
                admin.auth.admin.create_user(
                    {
                        "email": auth_email,
                        "password": password,
                        "email_confirm": True,
                        "app_metadata": app_metadata,
                    }
                )
            except AuthApiError as exc:
                if not _is_already_registered(exc):
                    raise
                # Already provisioned — rotate its password, refresh app_metadata.
                user = self._find_by_email(admin, auth_email)
                if user is None:
                    raise
                admin.auth.admin.update_user_by_id(
                    user.id, {"password": password, "app_metadata": app_metadata}
                )

            anon = create_client(self._url, self._anon_key)
            session = anon.auth.sign_in_with_password(
                {"email": auth_email, "password": password}
            )
        except (AuthApiError, httpx.HTTPError) as exc:
            raise AccessIssuanceFailed(str(exc)) from exc
        return {"party_id": party_id, "access_token": session.session.access_token}

    @staticmethod
    def _find_by_email(admin: Any, email: str) -> Any | None:
        # supabase-py has no get-by-email; page through admin.list_users.
        page = 1
        while True:
            users = admin.auth.admin.list_users(page=page, per_page=200)
            if not users:
                return None
            for u in users:
                if (u.email or "").lower() == email.lower():
                    return u
            page += 1
