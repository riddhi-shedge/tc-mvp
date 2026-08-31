"""TC authentication for the master API.

Verifies a Supabase-issued JWT on every route and requires the session to have
completed MFA (aal2) — MFA is on for the TC.

Verification strategy, in order:
  * If SUPABASE_JWT_SECRET is set, verify HS256 with it. Used by the test suite
    (synthetic tokens) and any project still on a shared JWT secret.
  * Otherwise, verify against the project's JWKS (the asymmetric signing keys
    Supabase now issues by default — ES256/RS256), fetched from
    {SUPABASE_URL}/auth/v1/.well-known/jwks.json and cached.
  * If neither is configured, fail closed.

Set REQUIRE_MFA=false only in local experiments; it defaults to true.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)

_JWKS_TTL_SECONDS = 600
_ASYMMETRIC_ALGS = ["ES256", "RS256"]

# Cached JWKS (Supabase's asymmetric signing keys), refreshed on TTL expiry.
_jwks_lock = threading.Lock()
_jwks_cache: tuple[float, jwt.PyJWKSet] | None = None


@dataclass(frozen=True)
class TCUser:
    id: str
    email: str

    @property
    def actor(self) -> str:
        """Identity recorded in the audit log."""
        return self.email or self.id


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _jwks() -> jwt.PyJWKSet:
    """Fetch and cache the project's JWKS. Fetched with httpx so it uses the same
    (certifi-backed) TLS trust store as the rest of the app.

    The network fetch happens OUTSIDE the lock — a JWKS outage then fails each
    request fast (as a 401, fail-closed) instead of serializing every
    authenticated request behind a lock held across a multi-second call."""
    cached = _jwks_cache  # atomic read; refresh when past TTL
    if cached is not None and time.time() - cached[0] < _JWKS_TTL_SECONDS:
        return cached[1]
    try:
        base = os.environ["SUPABASE_URL"].rstrip("/")
        resp = httpx.get(f"{base}/auth/v1/.well-known/jwks.json", timeout=10.0)
        resp.raise_for_status()
        keyset = jwt.PyJWKSet.from_dict(resp.json())
    except (httpx.HTTPError, ValueError, KeyError, jwt.PyJWTError) as exc:
        # Includes malformed key material (PyJWKError family). Fail closed as a
        # 401 rather than letting an unexpected error surface as a 500.
        raise jwt.InvalidTokenError(f"JWKS unavailable: {exc}") from exc
    with _jwks_lock:
        globals()["_jwks_cache"] = (time.time(), keyset)
    return keyset


def _signing_key(token: str) -> object:
    """The JWKS key whose `kid` matches the token header."""
    kid = jwt.get_unverified_header(token).get("kid")
    try:
        for key in _jwks().keys:
            if key.key_id == kid:
                return key.key  # PyJWK builds the key lazily here
    except jwt.PyJWTError as exc:
        raise jwt.InvalidTokenError(f"Bad JWKS key: {exc}") from exc
    raise jwt.InvalidTokenError(f"No JWKS key for kid={kid!r}")


def _decode(token: str) -> dict:
    """Verify the token's signature and standard claims, returning its payload.

    Raises jwt.InvalidTokenError on any verification failure."""
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if secret:
        # A shared HS256 secret is a test/dev convenience. In production the
        # project signs with rotating asymmetric keys and anyone holding this
        # secret could mint TC tokens — refuse it there and force JWKS.
        if os.environ.get("APP_ENV", "").lower() == "production":
            raise jwt.InvalidTokenError(
                "SUPABASE_JWT_SECRET must not be set in production; verify via JWKS"
            )
        return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")

    if os.environ.get("SUPABASE_URL"):
        return jwt.decode(
            token,
            _signing_key(token),
            algorithms=_ASYMMETRIC_ALGS,
            audience="authenticated",
        )

    raise jwt.InvalidTokenError("Auth not configured")


@dataclass(frozen=True)
class PartyUser:
    """An outside party (agent, escrow, lender, inspector, buyer/seller…) on a
    scoped invite session. Their app_metadata pins them to one party + one deal."""

    party_id: str
    transaction_id: str
    tier: str

    @property
    def actor(self) -> str:
        return f"party:{self.party_id}"


# ---- Permanent invite tokens (pi_…) -----------------------------------------
# Opaque credentials stored HASHED in party_invites, permanent until revoked
# (re-minting revokes the prior link). Resolved via a pluggable lookup so tests
# inject the fake repo; production lazily builds a service-role resolver.

INVITE_TOKEN_PREFIX = "pi_"
_invite_resolver: "Callable[[str], dict | None] | None" = None


def set_invite_resolver(fn: "Callable[[str], dict | None]") -> None:
    global _invite_resolver
    _invite_resolver = fn


def _resolve_invite(token: str) -> PartyUser | None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    resolver = _invite_resolver
    if resolver is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            return None
        from supabase import create_client

        client = create_client(url, key)

        def resolver(h: str):  # type: ignore[misc]
            rows = (
                client.table("party_invites")
                .select("party_id, transaction_id, tier")
                .eq("token_hash", h)
                .is_("revoked_at", "null")
                .limit(1)
                .execute()
                .data
            )
            return rows[0] if rows else None

    try:
        row = resolver(token_hash)
    except Exception:
        return None  # infra failure reads as unauthorized, never a 500 leak
    if not row:
        return None
    return PartyUser(
        party_id=str(row["party_id"]),
        transaction_id=str(row["transaction_id"]),
        tier=str(row.get("tier") or "receiving_end"),
    )


def require_party(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> PartyUser:
    """A scoped party session: EITHER a permanent invite token (pi_…, resolved
    against its stored hash) or a Supabase session JWT carrying app_metadata.
    party_id + transaction_id. Either way the party can only ever touch their own
    deal — the binding comes from the credential, never the client."""
    if credentials is None:
        raise _unauthorized("Missing bearer token")
    if credentials.credentials.startswith(INVITE_TOKEN_PREFIX):
        user = _resolve_invite(credentials.credentials)
        if user is None:
            raise _unauthorized("Invite link is invalid or was revoked")
        return user
    try:
        claims = _decode(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid or expired token") from None
    if claims.get("role") != "authenticated":
        raise _unauthorized("Not an authenticated session")
    app_metadata = claims.get("app_metadata")
    if not isinstance(app_metadata, dict):
        raise _unauthorized("Not a party session")
    party_id = app_metadata.get("party_id")
    transaction_id = app_metadata.get("transaction_id")
    if not party_id or not transaction_id:
        raise _unauthorized("Not a party session")
    return PartyUser(
        party_id=str(party_id),
        transaction_id=str(transaction_id),
        tier=str(app_metadata.get("tier") or "receiving_end"),
    )


def require_agent_portfolio(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> PartyUser:
    """A buyer's-agent (or broker) session for the cross-deal command center. It's a
    normal party session, but only the collaborator tier — agents/broker — may reach
    the whole-book portfolio. Aggregation runs service-role in the backend; the token
    authenticates the agent, and receiving-end (buyer/seller/vendor) tiers are refused."""
    party = require_party(credentials)
    if party.tier != "collaborator":
        raise _unauthorized("Portfolio access is for agents and brokers only")
    return party


def require_tc(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TCUser:
    if credentials is None:
        raise _unauthorized("Missing bearer token")

    try:
        claims = _decode(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid or expired token") from None

    if claims.get("role") != "authenticated":
        raise _unauthorized("Not an authenticated user session")

    # Defense in depth: a receiving-end party session (carries app_metadata.
    # party_id) is never a TC — reject it outright, not only via the MFA gate.
    app_metadata = claims.get("app_metadata")
    if isinstance(app_metadata, dict) and app_metadata.get("party_id"):
        raise _unauthorized("Receiving-end token cannot access the TC API")

    require_mfa = os.environ.get("REQUIRE_MFA", "true").lower() != "false"
    if require_mfa and claims.get("aal") != "aal2":
        raise HTTPException(status_code=403, detail="MFA required: session is not aal2")

    return TCUser(id=claims.get("sub", ""), email=claims.get("email", ""))
