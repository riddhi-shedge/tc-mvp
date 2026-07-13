"""Stub lender draft + Approve & Send (FAKE — Rule 3 shape, no real email).

The approve-and-send endpoint IS the human approval: an Approval row is
recorded before any 'sent' transition, and the send is fake (audit-only).
"""


def _txn(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "742 Synthetic Ave"}, headers=tc_headers
    ).json()["id"]


def _draft(client, tc_headers, txn_id) -> dict:
    r = client.post(f"/transactions/{txn_id}/messages/draft-stub", headers=tc_headers)
    assert r.status_code == 201
    return r.json()


def test_draft_stub_creates_draft_message_with_why(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    body = _draft(client, tc_headers, txn_id)
    assert body["message"]["status"] == "draft"
    assert "lender" in body["message"]["subject"].lower()
    assert "(stub)" in body["message"]["body"]
    assert body["why"]  # the AI panel explains WHY this draft exists


def test_draft_stub_writes_audit_row(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    _draft(client, tc_headers, txn_id)
    assert any(a["action"] == "message.drafted" for a in repo.audit_log)


def test_draft_unknown_transaction_is_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/messages/draft-stub",
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_approve_and_send_records_approval_before_sent(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    msg_id = _draft(client, tc_headers, txn_id)["message"]["id"]

    r = client.post(
        f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send", headers=tc_headers
    )
    assert r.status_code == 200
    sent = r.json()["message"]
    assert sent["status"] == "sent"
    assert sent["sent_at"] is not None

    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    approvals = state["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["message_id"] == msg_id
    assert approvals[0]["approved_by"] == "tc@example.test"

    actions = [a["action"] for a in state["audit_log"]]
    assert actions.index("message.approved") < actions.index("message.sent")
    sent_row = next(a for a in state["audit_log"] if a["action"] == "message.sent")
    assert sent_row["details"]["fake"] is True  # Phase 2 sends nothing real


def test_approve_and_send_twice_is_409(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    msg_id = _draft(client, tc_headers, txn_id)["message"]["id"]
    url = f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send"
    assert client.post(url, headers=tc_headers).status_code == 200
    assert client.post(url, headers=tc_headers).status_code == 409


def test_approve_and_send_unknown_message_is_404(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/messages/00000000-0000-0000-0000-000000000000/approve-and-send",
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_approve_and_send_requires_auth(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    msg_id = _draft(client, tc_headers, txn_id)["message"]["id"]
    r = client.post(f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send")
    assert r.status_code == 401
