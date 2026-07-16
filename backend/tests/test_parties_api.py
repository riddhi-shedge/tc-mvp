"""Party-create endpoint (TC-authed) — the lender contact and future parties."""


def _txn(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "1 Party Way"}, headers=tc_headers
    ).json()["id"]


def test_create_party_requires_auth(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "X", "role": "lender", "email": "l@example.test"},
    )
    assert r.status_code == 401


def test_create_party_appears_in_state_with_audit(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": "lender@example.test"},
        headers=tc_headers,
    )
    assert r.status_code == 201
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert [p["role"] for p in state["parties"]] == ["lender"]
    assert any(a["action"] == "party.added" for a in repo.audit_log)


def test_role_defaults_permission_tier(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    lender = client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "L", "role": "lender", "email": "l@example.test"},
        headers=tc_headers,
    ).json()
    inspector = client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "I", "role": "inspector_general"},
        headers=tc_headers,
    ).json()
    assert lender["permission_tier"] == "email_participant"
    assert inspector["permission_tier"] == "receiving_end"


def test_create_party_unknown_transaction_is_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/parties",
        json={"name": "X", "role": "lender"},
        headers=tc_headers,
    )
    assert r.status_code == 404
