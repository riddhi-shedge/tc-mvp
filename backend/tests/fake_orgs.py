"""In-memory fake of the OrgsRepo interface — org settings, members, invites."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from tests.fake_repo import TEST_ORG_B_ID, TEST_ORG_ID


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryOrgsRepo:
    def __init__(self) -> None:
        self.orgs: dict[str, dict[str, Any]] = {
            TEST_ORG_ID: {"id": TEST_ORG_ID, "name": "Terra", "inbound_key": "terra"},
            TEST_ORG_B_ID: {"id": TEST_ORG_B_ID, "name": "Beta TC Co", "inbound_key": "org-b"},
        }
        self.settings: dict[str, dict[str, Any]] = {}
        self.member_rows: list[dict[str, Any]] = []
        self.invites: list[dict[str, Any]] = []

    # -- helper for the fake org directory (auth-time membership) -------------
    def membership_of(self, user_id: str) -> dict[str, Any] | None:
        row = next((m for m in self.member_rows if m["user_id"] == user_id), None)
        return {"org_id": row["org_id"], "role": row["role"]} if row else None

    # -- OrgsRepo interface ----------------------------------------------------
    def org_info(self, org_id: str) -> dict[str, Any] | None:
        return self.orgs.get(org_id)

    def get_settings(self, org_id: str) -> dict[str, Any] | None:
        return self.settings.get(org_id)

    def upsert_settings(
        self, *, org_id: str, send_mode: str, send_allowlist: list[str]
    ) -> dict[str, Any]:
        row = {"send_mode": send_mode, "send_allowlist": send_allowlist}
        self.settings[org_id] = row
        return row

    def members(self, org_id: str) -> list[dict[str, Any]]:
        return [dict(m) for m in self.member_rows if m["org_id"] == org_id]

    def create_org(self, *, name: str, user_id: str, email: str) -> dict[str, Any]:
        org = {"id": str(uuid.uuid4()), "name": name, "inbound_key": None}
        self.orgs[org["id"]] = org
        self.member_rows.append(
            {
                "org_id": org["id"],
                "user_id": user_id,
                "email": email,
                "role": "owner",
                "created_at": _now(),
            }
        )
        return org

    def create_member_invite(
        self, *, org_id: str, email: str, role: str, token_hash: str
    ) -> dict[str, Any]:
        for inv in self.invites:
            if (
                inv["org_id"] == org_id
                and inv["email"] == email
                and inv["accepted_at"] is None
                and inv["revoked_at"] is None
            ):
                inv["revoked_at"] = _now()
        invite = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "email": email,
            "role": role,
            "token_hash": token_hash,
            "created_at": _now(),
            "accepted_at": None,
            "accepted_by": None,
            "revoked_at": None,
        }
        self.invites.append(invite)
        return invite

    def list_member_invites(self, org_id: str) -> list[dict[str, Any]]:
        return [
            {"id": i["id"], "email": i["email"], "role": i["role"], "created_at": i["created_at"]}
            for i in self.invites
            if i["org_id"] == org_id and i["accepted_at"] is None and i["revoked_at"] is None
        ]

    def revoke_member_invite(self, *, org_id: str, invite_id: str) -> bool:
        inv = next(
            (
                i
                for i in self.invites
                if i["id"] == invite_id
                and i["org_id"] == org_id
                and i["accepted_at"] is None
                and i["revoked_at"] is None
            ),
            None,
        )
        if inv is None:
            return False
        inv["revoked_at"] = _now()
        return True

    def resolve_member_invite(self, token_hash: str) -> dict[str, Any] | None:
        inv = next(
            (
                i
                for i in self.invites
                if i["token_hash"] == token_hash
                and i["accepted_at"] is None
                and i["revoked_at"] is None
            ),
            None,
        )
        if inv is None:
            return None
        return {
            "id": inv["id"],
            "org_id": inv["org_id"],
            "email": inv["email"],
            "role": inv["role"],
            "created_at": inv["created_at"],
        }

    def accept_member_invite(
        self, *, invite_id: str, org_id: str, user_id: str, email: str, role: str
    ) -> dict[str, Any] | None:
        # Claim-first CAS, mirroring the Supabase impl: only a still-pending
        # invite can be claimed; a racing revoke/accept loses cleanly.
        inv = next(
            (
                i
                for i in self.invites
                if i["id"] == invite_id
                and i["accepted_at"] is None
                and i["revoked_at"] is None
            ),
            None,
        )
        if inv is None:
            return None
        inv["accepted_at"] = _now()
        inv["accepted_by"] = user_id
        member = {
            "org_id": org_id,
            "user_id": user_id,
            "email": email,
            "role": role,
            "created_at": _now(),
        }
        self.member_rows.append(member)
        return member

    def remove_member(self, *, org_id: str, user_id: str) -> bool:
        rows = [m for m in self.member_rows if m["org_id"] == org_id]
        target = next((m for m in rows if m["user_id"] == user_id), None)
        if target is None:
            return False
        owners = [m for m in rows if m["role"] == "owner"]
        if target["role"] == "owner" and len(owners) <= 1:
            return False
        self.member_rows.remove(target)
        if target["role"] == "owner" and not any(
            m["role"] == "owner" for m in self.member_rows if m["org_id"] == org_id
        ):
            self.member_rows.append(target)  # compensate: never orphan an org
            return False
        return True

    def sync_member_email(self, *, org_id: str, user_id: str, email: str) -> None:
        for m in self.member_rows:
            if m["org_id"] == org_id and m["user_id"] == user_id:
                m["email"] = email
