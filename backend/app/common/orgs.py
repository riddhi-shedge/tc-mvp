"""Org directory: which org a TC user belongs to, and which org an inbound
email address routes to.

This is the only code (outside migrations) that reads orgs/org_members.
Pluggable (set_directory) so tests run without a database; the default
directory queries Supabase with the service-role key. Membership lookups are
cached with a short TTL so require_tc costs one DB read per user per minute,
not per request — same tradeoff as the JWKS cache. Failures fail CLOSED: a
user whose membership can't be resolved gets no org, and no org means 403.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Protocol

_CACHE_TTL_SECONDS = 60
_CACHE_MAX_ENTRIES = 4096

DEMO_ORG_ID = "00000000-0000-4000-8000-000000000001"


class OrgDirectory(Protocol):
    def membership(self, user_id: str) -> dict[str, Any] | None:
        """{"org_id", "role"} for the user's org, or None (no membership)."""
        ...

    def org_for_inbound_key(self, key: str) -> str | None:
        """Org id owning this inbound plus-address tag, or None."""
        ...

    def sole_org_id(self) -> str | None:
        """The org id iff EXACTLY one org exists (single-tenant deployments
        route untagged inbound mail to it); None when zero or several."""
        ...


class _SupabaseDirectory:
    """Service-role reads of orgs/org_members. Client built lazily per thread."""

    def __init__(self) -> None:
        from app.common.db import ThreadLocalSupabase

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("Org directory needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        self._db = ThreadLocalSupabase(url, key)

    def membership(self, user_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.client.table("org_members")
            .select("org_id, role")
            .eq("user_id", user_id)
            .order("created_at")
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def org_for_inbound_key(self, key: str) -> str | None:
        rows = (
            self._db.client.table("orgs").select("id").eq("inbound_key", key).limit(1).execute().data
        )
        return str(rows[0]["id"]) if rows else None

    def sole_org_id(self) -> str | None:
        rows = self._db.client.table("orgs").select("id").limit(2).execute().data
        return str(rows[0]["id"]) if len(rows) == 1 else None


_lock = threading.Lock()
_directory: OrgDirectory | None = None
# user_id -> (fetched_at, membership row or None). Negative results cache too.
_membership_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def set_directory(directory: OrgDirectory | None) -> None:
    """Install a directory (tests) or reset to the lazy Supabase default (None).
    Always clears the membership cache so stale entries can't cross fixtures."""
    global _directory
    with _lock:
        _directory = directory
        _membership_cache.clear()


def _get_directory() -> OrgDirectory | None:
    global _directory
    with _lock:
        if _directory is not None:
            return _directory
    try:
        built = _SupabaseDirectory()
    except RuntimeError:
        return None  # unconfigured -> callers fail closed
    with _lock:
        if _directory is None:
            _directory = built
        return _directory


def membership_for_user(user_id: str) -> dict[str, Any] | None:
    """The user's org membership, TTL-cached. None ⇒ no org ⇒ caller rejects."""
    if not user_id:
        return None
    now = time.time()
    with _lock:
        hit = _membership_cache.get(user_id)
        if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]
    directory = _get_directory()
    if directory is None:
        return None
    try:
        row = directory.membership(user_id)
    except Exception:
        return None  # infra failure reads as no membership (fail closed), never a 500
    with _lock:
        if len(_membership_cache) >= _CACHE_MAX_ENTRIES:
            _membership_cache.clear()
        _membership_cache[user_id] = (now, row)
    return row


def org_for_inbound_key(key: str) -> str | None:
    directory = _get_directory()
    if directory is None:
        return None
    try:
        return directory.org_for_inbound_key(key)
    except Exception:
        return None


def sole_org_id() -> str | None:
    directory = _get_directory()
    if directory is None:
        return None
    try:
        return directory.sole_org_id()
    except Exception:
        return None
