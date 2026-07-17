"""Live JWKS verification for TC auth (Prompt 7) — synthetic data only.

The project signs sessions with rotating asymmetric keys (ES256), so require_tc
must verify against the project's JWKS, not a shared HS256 secret. This proves,
against the live dev project, that a genuine Supabase-issued token is
signature-verified through that path (and a tampered one is rejected).

The rest of require_tc's contract (role, aal2/MFA) is covered by the synthetic
unit tests in test_auth.py. Skips unless Supabase env is configured; conftest
sets a synthetic SUPABASE_JWT_SECRET, so we drop it here to force the JWKS path.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("SUPABASE_URL")
        and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        and os.environ.get("SUPABASE_ANON_KEY")
    ),
    reason="Supabase env (URL + service role + anon key) not configured; JWKS test skipped",
)


@pytest.fixture()
def genuine_token(monkeypatch):
    """A real Supabase-issued session token, plus the JWKS verification path
    forced on by removing the synthetic HS256 secret. Cleans up the auth user."""
    import uuid

    from supabase import create_client

    import app.common.auth as auth
    from app.master.party_access import SupabasePartyAccessIssuer

    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setattr(auth, "_jwks_cache", None)  # fetch fresh from the live JWKS

    issuer = SupabasePartyAccessIssuer()
    party_id = str(uuid.uuid4())
    result = issuer.issue(party_id=party_id, transaction_id="txn-jwks", email=None)
    yield result["access_token"]

    admin = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    )
    user = SupabasePartyAccessIssuer._find_by_email(
        admin, issuer._auth_email(party_id=party_id, email=None)
    )
    if user is not None:
        admin.auth.admin.delete_user(user.id)


def test_jwks_verifies_a_genuine_supabase_token(genuine_token):
    from app.common.auth import _decode

    claims = _decode(genuine_token)  # raises if the JWKS signature check fails
    assert claims["role"] == "authenticated"
    assert claims["aud"] == "authenticated"


def test_jwks_rejects_a_tampered_token(genuine_token):
    import jwt

    from app.common.auth import _decode

    tampered = genuine_token[:-2] + ("aa" if genuine_token[-2:] != "aa" else "bb")
    with pytest.raises(jwt.InvalidTokenError):
        _decode(tampered)
