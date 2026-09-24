"""Org workspace routes: signup, teammate invites, members, send settings.

Tenancy notes for tests/test_tenancy.py: every authenticated route here derives
its org from the caller's token (owner routes via require_tc + role check; the
two onboarding routes via require_tc_candidate — a verified MFA'd session that
has no org yet). No route takes an org id from the client.

SIGNUP_MODE (env): 'closed' (default) refuses self-serve org creation; 'open'
allows it. Teammate invites are accepted in either mode — the owner's minted
link IS the authorization."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.common import orgs as org_directory
from app.common.auth import TCCandidate, TCUser, require_tc, require_tc_candidate
from app.master.org_repo import (
    INVITE_TOKEN_PREFIX,
    VALID_MEMBER_ROLES,
    VALID_SEND_MODES,
    OrgsRepo,
    SupabaseOrgsRepo,
)

router = APIRouter(prefix="/orgs")
_log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@lru_cache(maxsize=1)
def _default_orgs_repo() -> SupabaseOrgsRepo:
    return SupabaseOrgsRepo()


def get_orgs_repo() -> OrgsRepo:
    return _default_orgs_repo()


def _require_owner(tc: TCUser) -> None:
    if tc.org_role != "owner":
        raise HTTPException(status_code=403, detail="Only a workspace owner can do this")


def _signup_mode() -> str:
    mode = os.environ.get("SIGNUP_MODE", "closed").lower()
    return mode if mode in ("closed", "open") else "closed"


def _inbound_address(info: dict[str, Any] | None) -> str | None:
    """The org's plus-addressed inbound mailbox (deal+<key>@domain), if both the
    deployment address and the org's inbound_key exist."""
    base = os.environ.get("POSTMARK_INBOUND_ADDRESS", "")
    key = (info or {}).get("inbound_key")
    if not base or "@" not in base or not key:
        return None
    local, _, domain = base.partition("@")
    return f"{local}+{key}@{domain}"


# ---- Public config (the login screen decides whether to show "create") ------


@router.get("/config")
def org_config() -> dict[str, Any]:
    return {"signup_mode": _signup_mode()}


# ---- Onboarding (candidate sessions: verified + MFA, no org yet) -------------


class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)


@router.post("", status_code=201)
def create_org(
    body: CreateOrgRequest,
    candidate: TCCandidate = Depends(require_tc_candidate),
    repo: OrgsRepo = Depends(get_orgs_repo),
) -> dict[str, Any]:
    if _signup_mode() != "open":
        raise HTTPException(
            status_code=403, detail="Workspace creation is invite-only right now"
        )
    if org_directory.membership_for_user(candidate.id) is not None:
        raise HTTPException(status_code=409, detail="This account already has a workspace")
    org = repo.create_org(name=body.name.strip(), user_id=candidate.id, email=candidate.email)
    org_directory.invalidate_membership(candidate.id)
    _log.info("org.created org=%s", org["id"])
    return {"org_id": org["id"], "name": org["name"], "role": "owner"}


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)


@router.post("/members/accept")
def accept_member_invite(
    body: AcceptInviteRequest,
    candidate: TCCandidate = Depends(require_tc_candidate),
    repo: OrgsRepo = Depends(get_orgs_repo),
) -> dict[str, Any]:
    if not body.token.startswith(INVITE_TOKEN_PREFIX):
        raise HTTPException(status_code=404, detail="Invite link is invalid or was revoked")
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    invite = repo.resolve_member_invite(token_hash)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite link is invalid or was revoked")
    # The invite is bound to an address: the accepting session must be that
    # address, so a leaked link is useless to anyone else.
    if (candidate.email or "").strip().lower() != str(invite["email"]).strip().lower():
        raise HTTPException(
            status_code=403, detail="This invite was issued to a different email address"
        )
    if org_directory.membership_for_user(candidate.id) is not None:
        raise HTTPException(status_code=409, detail="This account already has a workspace")
    member = repo.accept_member_invite(
        invite_id=str(invite["id"]),
        org_id=str(invite["org_id"]),
        user_id=candidate.id,
        email=candidate.email,
        role=str(invite["role"]),
    )
    org_directory.invalidate_membership(candidate.id)
    _log.info("org.member_joined org=%s", invite["org_id"])
    return {"org_id": str(invite["org_id"]), "role": member["role"]}


# ---- Workspace (full TC sessions) --------------------------------------------


@router.get("/me")
def my_org(
    tc: TCUser = Depends(require_tc),
    repo: OrgsRepo = Depends(get_orgs_repo),
) -> dict[str, Any]:
    info = repo.org_info(tc.org_id)
    out: dict[str, Any] = {
        "org_id": tc.org_id,
        "name": (info or {}).get("name") or "Workspace",
        "role": tc.org_role,
        "inbound_address": _inbound_address(info),
        "members": repo.members(tc.org_id),
    }
    if tc.org_role == "owner":
        settings = repo.get_settings(tc.org_id)
        out["invites"] = repo.list_member_invites(tc.org_id)
        out["settings"] = settings or {"send_mode": "allowlist", "send_allowlist": []}
        out["settings_configured"] = settings is not None
        env_list = os.environ.get("SEND_ALLOWLIST", "")
        out["global_allowlist_active"] = bool(env_list.strip())
    return out


class InviteRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    role: str = Field(default="member")


@router.post("/members/invites", status_code=201)
def create_member_invite(
    body: InviteRequest,
    tc: TCUser = Depends(require_tc),
    repo: OrgsRepo = Depends(get_orgs_repo),
) -> dict[str, Any]:
    _require_owner(tc)
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That doesn't look like an email address")
    if body.role not in VALID_MEMBER_ROLES:
        raise HTTPException(status_code=422, detail="Role must be 'owner' or 'member'")
    if any(str(m.get("email") or "").lower() == email for m in repo.members(tc.org_id)):
        raise HTTPException(status_code=409, detail="That person is already a member")
    token = INVITE_TOKEN_PREFIX + secrets.token_hex(24)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    invite = repo.create_member_invite(
        org_id=tc.org_id, email=email, role=body.role, token_hash=token_hash
    )
    _log.info("org.invite_created org=%s invite=%s", tc.org_id, invite["id"])
    # The raw token appears ONCE, here — the owner copies the join link.
    return {"id": invite["id"], "email": email, "role": body.role, "token": token}


@router.post("/members/invites/{invite_id}/revoke")
def revoke_member_invite(
    invite_id: str,
    tc: TCUser = Depends(require_tc),
    repo: OrgsRepo = Depends(get_orgs_repo),
) -> dict[str, Any]:
    _require_owner(tc)
    if not repo.revoke_member_invite(org_id=tc.org_id, invite_id=invite_id):
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"revoked": True}


@router.delete("/members/{user_id}")
def remove_member(
    user_id: str,
    tc: TCUser = Depends(require_tc),
    repo: OrgsRepo = Depends(get_orgs_repo),
) -> dict[str, Any]:
    _require_owner(tc)
    if user_id == tc.id:
        raise HTTPException(status_code=422, detail="You can't remove yourself")
    if not repo.remove_member(org_id=tc.org_id, user_id=user_id):
        raise HTTPException(
            status_code=404, detail="Member not found (or they are the last owner)"
        )
    org_directory.invalidate_membership(user_id)
    return {"removed": True}


class SettingsRequest(BaseModel):
    send_mode: str
    send_allowlist: list[str] = Field(default_factory=list, max_length=100)


@router.patch("/settings")
def update_settings(
    body: SettingsRequest,
    tc: TCUser = Depends(require_tc),
    repo: OrgsRepo = Depends(get_orgs_repo),
) -> dict[str, Any]:
    _require_owner(tc)
    if body.send_mode not in VALID_SEND_MODES:
        raise HTTPException(status_code=422, detail="send_mode must be 'allowlist' or 'open'")
    cleaned: list[str] = []
    for entry in body.send_allowlist:
        email = entry.strip().lower()
        if not _EMAIL_RE.match(email):
            raise HTTPException(
                status_code=422, detail=f"Allowlist entry isn't an email address: {entry[:60]}"
            )
        if email not in cleaned:
            cleaned.append(email)
    row = repo.upsert_settings(
        org_id=tc.org_id, send_mode=body.send_mode, send_allowlist=cleaned
    )
    _log.info("org.settings_updated org=%s mode=%s n=%d", tc.org_id, body.send_mode, len(cleaned))
    return {"send_mode": row["send_mode"], "send_allowlist": row["send_allowlist"]}
