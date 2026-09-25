"""Owner-initiated MFA reset (Track B): delete a locked-out teammate's TOTP
factors so their next sign-in re-enrolls a fresh authenticator.

Admin-API seam, pluggable like the mailer: routes depend on the Protocol,
tests inject a fake, production talks to Supabase's admin MFA API with the
service-role key. Deleting factors NEVER weakens the gate — the API still
requires aal2, so the user must complete a new enrollment before anything
works again."""

from __future__ import annotations

import os
from typing import Protocol


class MfaResetFailed(Exception):
    """The admin API refused or errored. Message stays generic (no PII)."""


class MfaAdmin(Protocol):
    def reset_factors(self, user_id: str) -> int:
        """Delete all of the user's MFA factors; returns how many were removed.
        Raises MfaResetFailed on any admin-API failure."""
        ...


class SupabaseMfaAdmin:
    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL")
        self._key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not self._url or not self._key:
            raise RuntimeError("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")

    def reset_factors(self, user_id: str) -> int:
        from supabase import create_client

        admin = create_client(self._url, self._key).auth.admin
        try:
            listed = admin.mfa.list_factors({"user_id": user_id})
            factors = getattr(listed, "factors", None) or []
            for factor in factors:
                admin.mfa.delete_factor({"user_id": user_id, "id": factor.id})
            return len(factors)
        except Exception as exc:  # never leak admin-API payloads
            raise MfaResetFailed(f"MFA reset failed ({type(exc).__name__})") from exc
