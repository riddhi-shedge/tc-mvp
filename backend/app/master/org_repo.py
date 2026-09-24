"""Org workspace repository: settings, members, teammate invites.

Separate from MasterRepo (deal SOR) on purpose — org administration is a
different concern with a much smaller surface, and keeping it apart means the
60-method deal interface doesn't grow tenancy plumbing. Service-role client;
every method is already org-scoped by its arguments (routes derive org_id from
the caller's token, never from the client)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Protocol

from app.common.db import ThreadLocalSupabase

INVITE_TOKEN_PREFIX = "oi_"
VALID_SEND_MODES = ("allowlist", "open")
VALID_MEMBER_ROLES = ("owner", "member")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OrgsRepo(Protocol):
    def org_info(self, org_id: str) -> dict[str, Any] | None: ...

    def get_settings(self, org_id: str) -> dict[str, Any] | None:
        """{"send_mode", "send_allowlist"} or None when the org has no row yet
        (the mailer treats no-row as fail-closed / env-only legacy)."""
        ...

    def upsert_settings(
        self, *, org_id: str, send_mode: str, send_allowlist: list[str]
    ) -> dict[str, Any]: ...

    def members(self, org_id: str) -> list[dict[str, Any]]: ...

    def create_org(self, *, name: str, user_id: str, email: str) -> dict[str, Any]:
        """New org + its first (owner) membership, atomically enough: the org is
        deleted if the membership insert fails."""
        ...

    def create_member_invite(
        self, *, org_id: str, email: str, role: str, token_hash: str
    ) -> dict[str, Any]:
        """Mint an invite; any prior PENDING invite for the same email in this
        org is revoked (re-inviting rotates the link, like party invites)."""
        ...

    def list_member_invites(self, org_id: str) -> list[dict[str, Any]]:
        """Pending invites (never includes token hashes)."""
        ...

    def revoke_member_invite(self, *, org_id: str, invite_id: str) -> bool: ...

    def resolve_member_invite(self, token_hash: str) -> dict[str, Any] | None:
        """The pending (unaccepted, unrevoked) invite for this token, or None."""
        ...

    def accept_member_invite(
        self, *, invite_id: str, org_id: str, user_id: str, email: str, role: str
    ) -> dict[str, Any]:
        """Write the membership and mark the invite accepted."""
        ...

    def remove_member(self, *, org_id: str, user_id: str) -> bool:
        """Remove a member. Refuses to remove the last owner (returns False)."""
        ...


class SupabaseOrgsRepo:
    def __init__(self) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")
        self._client = ThreadLocalSupabase(url, key)

    @property
    def _db(self) -> Any:
        return self._client.client

    def org_info(self, org_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("orgs")
            .select("id, name, inbound_key, created_at")
            .eq("id", org_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def get_settings(self, org_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("org_settings")
            .select("send_mode, send_allowlist")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def upsert_settings(
        self, *, org_id: str, send_mode: str, send_allowlist: list[str]
    ) -> dict[str, Any]:
        row = {
            "org_id": org_id,
            "send_mode": send_mode,
            "send_allowlist": send_allowlist,
            "updated_at": _now(),
        }
        return (
            self._db.table("org_settings")
            .upsert(row, on_conflict="org_id")
            .execute()
            .data[0]
        )

    def members(self, org_id: str) -> list[dict[str, Any]]:
        return (
            self._db.table("org_members")
            .select("user_id, email, role, created_at")
            .eq("org_id", org_id)
            .order("created_at")
            .execute()
            .data
        )

    def create_org(self, *, name: str, user_id: str, email: str) -> dict[str, Any]:
        org = self._db.table("orgs").insert({"name": name}).execute().data[0]
        try:
            self._db.table("org_members").insert(
                {"org_id": org["id"], "user_id": user_id, "email": email, "role": "owner"}
            ).execute()
        except Exception:
            self._db.table("orgs").delete().eq("id", org["id"]).execute()
            raise
        return org

    def create_member_invite(
        self, *, org_id: str, email: str, role: str, token_hash: str
    ) -> dict[str, Any]:
        # Re-inviting the same address rotates the credential: revoke prior pending.
        self._db.table("org_member_invites").update({"revoked_at": _now()}).eq(
            "org_id", org_id
        ).eq("email", email).is_("accepted_at", "null").is_("revoked_at", "null").execute()
        return (
            self._db.table("org_member_invites")
            .insert({"org_id": org_id, "email": email, "role": role, "token_hash": token_hash})
            .execute()
            .data[0]
        )

    def list_member_invites(self, org_id: str) -> list[dict[str, Any]]:
        return (
            self._db.table("org_member_invites")
            .select("id, email, role, created_at")
            .eq("org_id", org_id)
            .is_("accepted_at", "null")
            .is_("revoked_at", "null")
            .order("created_at", desc=True)
            .execute()
            .data
        )

    def revoke_member_invite(self, *, org_id: str, invite_id: str) -> bool:
        rows = (
            self._db.table("org_member_invites")
            .update({"revoked_at": _now()})
            .eq("id", invite_id)
            .eq("org_id", org_id)
            .is_("accepted_at", "null")
            .is_("revoked_at", "null")
            .execute()
            .data
        )
        return bool(rows)

    def resolve_member_invite(self, token_hash: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("org_member_invites")
            .select("id, org_id, email, role")
            .eq("token_hash", token_hash)
            .is_("accepted_at", "null")
            .is_("revoked_at", "null")
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def accept_member_invite(
        self, *, invite_id: str, org_id: str, user_id: str, email: str, role: str
    ) -> dict[str, Any]:
        member = (
            self._db.table("org_members")
            .insert({"org_id": org_id, "user_id": user_id, "email": email, "role": role})
            .execute()
            .data[0]
        )
        self._db.table("org_member_invites").update(
            {"accepted_at": _now(), "accepted_by": user_id}
        ).eq("id", invite_id).execute()
        return member

    def remove_member(self, *, org_id: str, user_id: str) -> bool:
        rows = self.members(org_id)
        target = next((m for m in rows if str(m["user_id"]) == str(user_id)), None)
        if target is None:
            return False
        owners = [m for m in rows if m["role"] == "owner"]
        if target["role"] == "owner" and len(owners) <= 1:
            return False  # never orphan an org
        self._db.table("org_members").delete().eq("org_id", org_id).eq(
            "user_id", user_id
        ).execute()
        return True
