"""Real lender draft (Prompt 6, via the fake drafter): needs a lender contact."""


def _txn(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "742 Lender Ave"}, headers=tc_headers
    ).json()["id"]


def _add_lender(client, tc_headers, txn_id, email="lender@example.test"):
    return client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": email},
        headers=tc_headers,
    )


def test_draft_lender_without_contact_is_409(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    r = client.post(f"/transactions/{txn_id}/messages/draft-lender", headers=tc_headers)
    assert r.status_code == 409
    assert "lender contact" in r.json()["detail"].lower()


def test_draft_lender_creates_draft_to_the_lender(client, tc_headers, repo, drafter):
    txn_id = _txn(client, tc_headers)
    lender = _add_lender(client, tc_headers, txn_id).json()
    r = client.post(f"/transactions/{txn_id}/messages/draft-lender", headers=tc_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["message"]["status"] == "draft"
    assert body["message"]["party_id"] == lender["id"]
    assert body["why"]
    assert drafter.calls  # the drafter seam was exercised
    assert any(a["action"] == "message.drafted" for a in repo.audit_log)


def test_draft_lender_passes_property_and_deadline_to_the_drafter(client, tc_headers, drafter):
    txn_id = _txn(client, tc_headers)
    _add_lender(client, tc_headers, txn_id)
    client.post(f"/transactions/{txn_id}/messages/draft-lender", headers=tc_headers)
    ctx = drafter.calls[-1]
    assert ctx.property_address == "742 Lender Ave"
    assert ctx.lender_name == "Synthetic Lender"


def test_draft_lender_unknown_transaction_is_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/messages/draft-lender",
        headers=tc_headers,
    )
    assert r.status_code == 404
