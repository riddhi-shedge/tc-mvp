"""TC authentication for the master API.

Verifies a Supabase-issued JWT (HS256, `SUPABASE_JWT_SECRET`) on every route and
requires the session to have completed MFA (aal2) — MFA is on for the TC.
Set REQUIRE_MFA=false only in local experiments; it defaults to true.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)


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


def require_tc(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TCUser:
    if credentials is None:
        raise _unauthorized("Missing bearer token")

    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if not secret:
        # Fail closed: no verification secret means no access.
        raise _unauthorized("Auth not configured")

    try:
        claims = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid or expired token") from None

    if claims.get("role") != "authenticated":
        raise _unauthorized("Not an authenticated user session")

    require_mfa = os.environ.get("REQUIRE_MFA", "true").lower() != "false"
    if require_mfa and claims.get("aal") != "aal2":
        raise HTTPException(status_code=403, detail="MFA required: session is not aal2")

    return TCUser(id=claims.get("sub", ""), email=claims.get("email", ""))
