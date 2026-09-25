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
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.common import orgs as org_directory
from app.common.auth import TCCandidate, TCUser, require_tc, require_tc_candidate
from app.master.mfa_admin import MfaAdmin, MfaResetFailed, SupabaseMfaAdmin
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

# A join link that was never accepted expires; email-bound or not, a workspace
# credential should not stay live in an inbox forever.
INVITE_TTL_DAYS = 14


def _invite_expired(created_at: Any) -> bool:
    if not created_at:
        return False  # no timestamp -> fall back to email binding + revocation
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created > timedelta(days=INVITE_TTL_DAYS)


@lru_cache(maxsize=1)
def _default_orgs_repo() -> SupabaseOrgsRepo:
    return SupabaseOrgsRepo()


def get_orgs_repo() -> OrgsRepo:
    try:
        return _default_orgs_repo()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Workspace service not configured") from None


@lru_cache(maxsize=1)
def _default_mfa_admin() -> SupabaseMfaAdmin:
    return SupabaseMfaAdmin()


def get_mfa_admin() -> MfaAdmin:
    try:
        return _default_mfa_admin()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Workspace service not configured") from None


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
    if org_directory.membership_for_user(candidate.id, fresh=True) is not None:
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
    # The invite is bound to an address: the accepting session must be that
    # address. Wrong-account attempts get the SAME 404 as a bogus token — a
    # leaked link is useless and its validity is never confirmed to a stranger.
    if invite is None or (candidate.email or "").strip().lower() != str(
        invite["email"]
    ).strip().lower():
        raise HTTPException(
            status_code=404,
            detail=(
                "Invite link is invalid, was revoked, or was issued to a different "
                "email address. Make sure you're signed in with the invited email."
            ),
        )
    if _invite_expired(invite.get("created_at")):
        raise HTTPException(status_code=404, detail="This invite link has expired")
    if org_directory.membership_for_user(candidate.id, fresh=True) is not None:
        raise HTTPException(status_code=409, detail="This account already has a workspace")
    member = repo.accept_member_invite(
        invite_id=str(invite["id"]),
        org_id=str(invite["org_id"]),
        user_id=candidate.id,
        email=candidate.email,
        role=str(invite["role"]),
    )
    if member is None:  # revoked or claimed by a racing request meanwhile
        raise HTTPException(status_code=404, detail="Invite link is invalid or was revoked")
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
    members = repo.members(tc.org_id)
    # Self-heal the denormalized email after an address change: the JWT is the
    # truth; the row is display-only.
    mine = next((m for m in members if str(m.get("user_id")) == tc.id), None)
    if mine is not None and tc.email and (mine.get("email") or "").lower() != tc.email.lower():
        repo.sync_member_email(org_id=tc.org_id, user_id=tc.id, email=tc.email)
        mine["email"] = tc.email
    out: dict[str, Any] = {
        "org_id": tc.org_id,
        "name": (info or {}).get("name") or "Workspace",
        "role": tc.org_role,
        "inbound_address": _inbound_address(info),
        "members": members,
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


@router.post("/members/{user_id}/reset-mfa")
def reset_member_mfa(
    user_id: str,
    tc: TCUser = Depends(require_tc),
    repo: OrgsRepo = Depends(get_orgs_repo),
    mfa: MfaAdmin = Depends(get_mfa_admin),
) -> dict[str, Any]:
    """Owner unlocks a teammate who lost their authenticator: their TOTP
    factors are deleted, so the next sign-in walks the normal enrollment again.
    Never self-service (you'd need working MFA to call it anyway), and only
    for members of the caller's own org. The owner's own lockout is the
    hosting runbook's job, not an API's."""
    _require_owner(tc)
    if user_id == tc.id:
        raise HTTPException(status_code=422, detail="You can't reset your own authenticator")
    if not any(str(m.get("user_id")) == user_id for m in repo.members(tc.org_id)):
        raise HTTPException(status_code=404, detail="Member not found")
    try:
        removed = mfa.reset_factors(user_id)
    except MfaResetFailed:
        raise HTTPException(
            status_code=502, detail="Could not reset the authenticator; try again shortly"
        ) from None
    _log.info("org.member_mfa_reset org=%s removed=%d", tc.org_id, removed)
    return {"reset": True, "factors_removed": removed}


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
