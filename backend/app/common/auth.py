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

import os
import threading
import time
from dataclasses import dataclass

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


def require_party(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> PartyUser:
    """A scoped party session: any authenticated token carrying app_metadata.
    party_id + transaction_id. The party can only ever touch their own deal — the
    transaction_id is taken from the (signed, admin-set) token, never the client."""
    if credentials is None:
        raise _unauthorized("Missing bearer token")
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
