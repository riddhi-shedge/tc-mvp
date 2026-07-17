"""TC auth: every route requires a valid Supabase JWT with MFA (aal2).

Tokens here are synthetic, signed with the synthetic test secret from conftest.
"""

from tests.conftest import make_token


def test_no_token_is_401(client):
    assert (
        client.post("/transactions", json={"property_address": "1 Synthetic Way"}).status_code
        == 401
    )


def test_garbage_token_is_401(client):
    r = client.post(
        "/transactions",
        json={"property_address": "1 Synthetic Way"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert r.status_code == 401


def test_wrong_signature_is_401(client):
    token = make_token(secret="some-other-synthetic-secret-0123456789abcdef")
    r = client.post(
        "/transactions",
        json={"property_address": "1 Synthetic Way"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_expired_token_is_401(client):
    token = make_token(expires_in=-60)
    r = client.post(
        "/transactions",
        json={"property_address": "1 Synthetic Way"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_wrong_role_is_401(client):
    token = make_token(role="anon")
    r = client.post(
        "/transactions",
        json={"property_address": "1 Synthetic Way"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_mfa_not_completed_is_403(client):
    """A session that hasn't completed MFA (aal1) is rejected — MFA is on for the TC."""
    token = make_token(aal="aal1")
    r = client.post(
        "/transactions",
        json={"property_address": "1 Synthetic Way"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "mfa" in r.json()["detail"].lower()


def test_receiving_end_party_token_is_rejected(client):
    """A party session (app_metadata.party_id), even if it somehow had aal2, must
    never reach the TC API — it's for the receiving-end, DB-scoped by RLS."""
    import time

    import jwt

    from tests.conftest import TEST_JWT_SECRET

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "party-1",
            "role": "authenticated",
            "aud": "authenticated",
            "aal": "aal2",
            "app_metadata": {"party_id": "some-party-id"},
            "iat": now,
            "exp": now + 3600,
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    r = client.get(
        "/transactions/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_valid_mfa_token_passes(client, tc_headers):
    r = client.post(
        "/transactions", json={"property_address": "1 Synthetic Way"}, headers=tc_headers
    )
    assert r.status_code == 201


def test_read_route_also_requires_auth(client):
    assert client.get("/transactions/00000000-0000-0000-0000-000000000000").status_code == 401
