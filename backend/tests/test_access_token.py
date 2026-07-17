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
        {"party_id": party_id, "transaction_id": txn_id, "email": None}
    ]
    # Rule 5: issuing a live credential is audited (never the token itself).
    audit = [a for a in repo.audit_log if a["action"] == "party.access_token_issued"]
    assert len(audit) == 1 and audit[0]["entity_id"] == party_id


def test_access_token_only_for_receiving_end_parties(client, tc_headers, party_access_issuer):
    """A non-receiving-end party (lender = email_participant) gets no live token."""
    txn_id = _txn(client, tc_headers)
    lender_id = client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "L", "role": "lender", "email": "l@example.test"},
        headers=tc_headers,
    ).json()["id"]
    r = client.post(
        f"/transactions/{txn_id}/parties/{lender_id}/access-token", headers=tc_headers
    )
    assert r.status_code == 409
    assert party_access_issuer.calls == []  # never mint for an out-of-scope tier


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
