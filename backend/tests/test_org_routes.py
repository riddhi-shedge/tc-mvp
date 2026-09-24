"""Org workspace routes (Track A6): signup gating, teammate invites, members,
send settings. Candidate sessions (verified + MFA, no org) use subs starting
with 'cand-' — the fake org directory gives those no default membership."""

from __future__ import annotations

from tests.conftest import ORG_B_SUB, make_token
from tests.fake_repo import TEST_ORG_ID


def _headers(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


OWNER = _headers()  # default sub: org A owner
OWNER_B = _headers(sub=ORG_B_SUB, email="tc-b@example.test")


# ---- signup gating ------------------------------------------------------------


def test_org_creation_is_closed_by_default(client):
    r = client.post(
        "/orgs", json={"name": "New TC Co"}, headers=_headers(sub="cand-alice", email="a@x.test")
    )
    assert r.status_code == 403
    assert client.get("/orgs/config").json() == {"signup_mode": "closed"}


def test_org_creation_when_open(client, monkeypatch):
    monkeypatch.setenv("SIGNUP_MODE", "open")
    assert client.get("/orgs/config").json() == {"signup_mode": "open"}
    headers = _headers(sub="cand-alice", email="alice@newco.test")
    r = client.post("/orgs", json={"name": "New TC Co"}, headers=headers)
    assert r.status_code == 201
    assert r.json()["role"] == "owner"

    # She is now a full TC of her own (empty) workspace…
    me = client.get("/orgs/me", headers=headers).json()
    assert me["name"] == "New TC Co" and me["role"] == "owner"
    assert client.get("/transactions", headers=headers).json() == []

    # …and cannot create a second workspace (single-org-per-user v1).
    assert client.post("/orgs", json={"name": "Another"}, headers=headers).status_code == 409


def test_membered_account_cannot_create_an_org(client, monkeypatch):
    monkeypatch.setenv("SIGNUP_MODE", "open")
    assert client.post("/orgs", json={"name": "Dup"}, headers=OWNER).status_code == 409


# ---- teammate invites -----------------------------------------------------------


def _invite(client, email="carol@teammate.test", role="member") -> dict:
    r = client.post("/orgs/members/invites", json={"email": email, "role": role}, headers=OWNER)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("oi_")
    return body


def test_invite_accept_happy_path(client):
    invite = _invite(client)
    carol = _headers(sub="cand-carol", email="carol@teammate.test")

    r = client.post("/orgs/members/accept", json={"token": invite["token"]}, headers=carol)
    assert r.status_code == 200
    assert r.json() == {"org_id": TEST_ORG_ID, "role": "member"}

    # Carol is now a member of org A: she can list its (empty) book, and
    # /orgs/me shows her role without owner-only keys.
    assert client.get("/transactions", headers=carol).status_code == 200
    me = client.get("/orgs/me", headers=carol).json()
    assert me["role"] == "member"
    assert "invites" not in me and "settings" not in me

    # The token is single-use: replay reads as revoked/invalid.
    replay = _headers(sub="cand-dave", email="carol@teammate.test")
    assert (
        client.post("/orgs/members/accept", json={"token": invite["token"]}, headers=replay)
        .status_code
        == 404
    )


def test_invite_is_bound_to_the_invited_email(client):
    invite = _invite(client, email="carol@teammate.test")
    wrong = _headers(sub="cand-mallory", email="mallory@elsewhere.test")
    r = client.post("/orgs/members/accept", json={"token": invite["token"]}, headers=wrong)
    assert r.status_code == 403


def test_revoked_invite_cannot_be_accepted_and_reinvite_rotates(client):
    first = _invite(client)
    revoke = client.post(
        f"/orgs/members/invites/{first['id']}/revoke", headers=OWNER
    )
    assert revoke.status_code == 200
    carol = _headers(sub="cand-carol", email="carol@teammate.test")
    assert (
        client.post("/orgs/members/accept", json={"token": first["token"]}, headers=carol)
        .status_code
        == 404
    )

    # Re-inviting mints a fresh link and kills any prior pending one implicitly.
    second = _invite(client)
    third = _invite(client)
    assert (
        client.post("/orgs/members/accept", json={"token": second["token"]}, headers=carol)
        .status_code
        == 404  # rotated away by the third invite
    )
    assert (
        client.post("/orgs/members/accept", json={"token": third["token"]}, headers=carol)
        .status_code
        == 200
    )


def test_only_owners_manage_invites_and_settings(client):
    invite = _invite(client)
    carol = _headers(sub="cand-carol", email="carol@teammate.test")
    client.post("/orgs/members/accept", json={"token": invite["token"]}, headers=carol)

    assert (
        client.post(
            "/orgs/members/invites", json={"email": "x@y.test"}, headers=carol
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/orgs/settings",
            json={"send_mode": "open", "send_allowlist": []},
            headers=carol,
        ).status_code
        == 403
    )


def test_cross_org_invite_revoke_reads_as_not_found(client):
    invite = _invite(client)
    r = client.post(f"/orgs/members/invites/{invite['id']}/revoke", headers=OWNER_B)
    assert r.status_code == 404


def test_member_removal(client, orgs_repo):
    invite = _invite(client)
    carol = _headers(sub="cand-carol", email="carol@teammate.test")
    client.post("/orgs/members/accept", json={"token": invite["token"]}, headers=carol)

    r = client.request("DELETE", "/orgs/members/cand-carol", headers=OWNER)
    assert r.status_code == 200
    assert orgs_repo.membership_of("cand-carol") is None
    # Her next request has no membership: fail closed.
    assert client.get("/transactions", headers=carol).status_code == 403


def test_settings_validation_and_roundtrip(client):
    bad_mode = client.patch(
        "/orgs/settings", json={"send_mode": "yolo", "send_allowlist": []}, headers=OWNER
    )
    assert bad_mode.status_code == 422
    bad_email = client.patch(
        "/orgs/settings",
        json={"send_mode": "allowlist", "send_allowlist": ["not-an-email"]},
        headers=OWNER,
    )
    assert bad_email.status_code == 422

    ok = client.patch(
        "/orgs/settings",
        json={"send_mode": "allowlist", "send_allowlist": ["Escrow@Title.test", "escrow@title.test"]},
        headers=OWNER,
    )
    assert ok.status_code == 200
    assert ok.json() == {"send_mode": "allowlist", "send_allowlist": ["escrow@title.test"]}

    me = client.get("/orgs/me", headers=OWNER).json()
    assert me["settings"] == {"send_mode": "allowlist", "send_allowlist": ["escrow@title.test"]}
    assert me["settings_configured"] is True
