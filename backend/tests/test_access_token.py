"""Receiving-end access-token endpoint (Prompt 7, §8).

The TC issues a scoped, party-keyed credential (a Supabase-issued session whose
app_metadata.party_id RLS keys off — the real provisioning lives behind the
PartyAccessIssuer seam, faked here). This asserts the endpoint is TC-authed,
delegates to the issuer with the right party/transaction, and its 404s. The live
proof that such a token can touch only its own task is in test_rls_permissions.py.
"""

from __future__ import annotations


def _txn(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "1 Token Way"}, headers=tc_headers
    ).json()["id"]


def _party(client, tc_headers, txn_id) -> str:
    return client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Inspector", "role": "inspector_general"},
        headers=tc_headers,
    ).json()["id"]


def test_access_token_requires_auth(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    party_id = _party(client, tc_headers, txn_id)
    r = client.post(f"/transactions/{txn_id}/parties/{party_id}/access-token")
    assert r.status_code == 401


def test_access_token_delegates_to_issuer_and_audits(client, tc_headers, party_access_issuer, repo):
    txn_id = _txn(client, tc_headers)
    party_id = _party(client, tc_headers, txn_id)
    r = client.post(
        f"/transactions/{txn_id}/parties/{party_id}/access-token", headers=tc_headers
    )
    assert r.status_code == 201
    body = r.json()
    assert body["party_id"] == party_id
    assert body["access_token"] == f"fake-token-{party_id}"
    # The issuer was called with this exact party + transaction.
    assert party_access_issuer.calls == [
        {"party_id": party_id, "transaction_id": txn_id, "email": None, "tier": "receiving_end"}
    ]
    # Rule 5: issuing a live credential is audited (never the token itself).
    audit = [a for a in repo.audit_log if a["action"] == "party.access_token_issued"]
    assert len(audit) == 1 and audit[0]["entity_id"] == party_id


def test_access_token_issued_for_every_party_scoped_tier(client, tc_headers, party_access_issuer):
    """Every party now gets their own scoped workspace token. A lender (not an
    agent/broker) gets one at the locked 'receiving_end' DB tier."""
    txn_id = _txn(client, tc_headers)
    lender_id = client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "L", "role": "lender", "email": "l@example.test"},
        headers=tc_headers,
    ).json()["id"]
    r = client.post(
        f"/transactions/{txn_id}/parties/{lender_id}/access-token", headers=tc_headers
    )
    assert r.status_code == 201
    assert party_access_issuer.calls[-1]["tier"] == "receiving_end"


def test_access_token_unknown_party_is_404(client, tc_headers, party_access_issuer):
    txn_id = _txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/parties/00000000-0000-0000-0000-000000000000/access-token",
        headers=tc_headers,
    )
    assert r.status_code == 404
    assert party_access_issuer.calls == []  # never issue for an unknown party


def test_access_token_party_from_other_transaction_is_404(client, tc_headers):
    txn_a = _txn(client, tc_headers)
    txn_b = _txn(client, tc_headers)
    party_b = _party(client, tc_headers, txn_b)
    r = client.post(
        f"/transactions/{txn_a}/parties/{party_b}/access-token", headers=tc_headers
    )
    assert r.status_code == 404


# ---- email invite -----------------------------------------------------------

def _agent(client, tc_headers, txn_id, email="agent@example.test"):
    return client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Basant", "role": "buyer_agent", **({"email": email} if email else {})},
        headers=tc_headers,
    ).json()["id"]


def test_invite_email_sends_with_the_link(client, tc_headers, mailer):
    txn = _txn(client, tc_headers)
    agent = _agent(client, tc_headers, txn)
    r = client.post(
        f"/transactions/{txn}/parties/{agent}/invite-email",
        json={"base_url": "https://app.test/"}, headers=tc_headers,
    )
    assert r.status_code == 200 and r.json()["sent"] is True
    assert len(mailer.sent) == 1 and mailer.sent[0]["to"] == "agent@example.test"
    assert "#invite=" in mailer.sent[0]["body"]  # the personalized link is in the email


def test_invite_email_requires_an_address(client, tc_headers):
    txn = _txn(client, tc_headers)
    agent = _agent(client, tc_headers, txn, email=None)
    r = client.post(
        f"/transactions/{txn}/parties/{agent}/invite-email",
        json={"base_url": "https://app.test/"}, headers=tc_headers,
    )
    assert r.status_code == 422


def test_invite_email_works_for_any_party_with_email(client, tc_headers):
    """Every party can be emailed their own scoped workspace link now."""
    txn = _txn(client, tc_headers)
    lender = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "L", "role": "lender", "email": "l@example.test"}, headers=tc_headers,
    ).json()["id"]
    r = client.post(
        f"/transactions/{txn}/parties/{lender}/invite-email",
        json={"base_url": "https://app.test/"}, headers=tc_headers,
    )
    assert r.status_code == 200 and r.json().get("sent") is True


def test_invite_email_disabled_returns_link_for_manual_share(client, tc_headers):
    from app.main import app
    from app.master.mailer import SendDisabled
    from app.master.routes import get_mailer
    from tests.fake_mailer import FakeMailer

    app.dependency_overrides[get_mailer] = lambda: FakeMailer(raises=SendDisabled("off"))
    txn = _txn(client, tc_headers)
    agent = _agent(client, tc_headers, txn)
    r = client.post(
        f"/transactions/{txn}/parties/{agent}/invite-email",
        json={"base_url": "https://app.test/"}, headers=tc_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is False and body["reason"] == "disabled" and "#invite=" in body["link"]
