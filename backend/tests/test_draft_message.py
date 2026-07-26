"""Personalized drafts to any party: recipient chosen from the deal, the draft is
specific to the deal (buyers/property), a recipient without an email is refused,
and the Rule 2 money guard still applies."""


def _deal_with_agent(client, tc_headers) -> tuple[str, str]:
    txn = client.post(
        "/transactions", json={"property_address": "1057 Foxglove Pl (synthetic)"}, headers=tc_headers
    ).json()["id"]
    pid = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Basant Somani", "role": "buyer_agent", "email": "agent@example.test"},
        headers=tc_headers,
    ).json()["id"]
    return txn, pid


def test_draft_message_is_personalized(client, tc_headers):
    txn, pid = _deal_with_agent(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/messages/draft",
        json={"party_id": pid, "purpose": "lender_status"},
        headers=tc_headers,
    )
    assert r.status_code == 201
    msg = r.json()["message"]
    # References the recipient + the property (personalized, not generic).
    assert "Basant Somani" in msg["body"]
    assert "Foxglove" in msg["body"]
    assert msg["party_id"] == pid
    assert msg["status"] == "draft"


def test_draft_requires_recipient_email(client, tc_headers):
    txn = client.post(
        "/transactions", json={"property_address": "1 A St"}, headers=tc_headers
    ).json()["id"]
    pid = client.post(
        f"/transactions/{txn}/parties", json={"name": "No Email", "role": "escrow"}, headers=tc_headers
    ).json()["id"]
    r = client.post(
        f"/transactions/{txn}/messages/draft",
        json={"party_id": pid, "purpose": "escrow_checkin"},
        headers=tc_headers,
    )
    assert r.status_code == 409


def test_draft_unknown_party_404(client, tc_headers):
    txn = client.post(
        "/transactions", json={"property_address": "1 A St"}, headers=tc_headers
    ).json()["id"]
    r = client.post(
        f"/transactions/{txn}/messages/draft",
        json={"party_id": "00000000-0000-0000-0000-000000000000", "purpose": "general"},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_draft_money_guard(client, tc_headers, drafter):
    from app.master.drafting import MessageDraft

    # Force the drafter to emit wiring language — the master must reject it.
    def _bad(ctx):
        return MessageDraft(subject="Wire the funds", body="Send the wire to account 123", why="x")

    drafter.draft_message = _bad  # type: ignore[assignment]
    txn, pid = _deal_with_agent(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/messages/draft",
        json={"party_id": pid, "purpose": "general"},
        headers=tc_headers,
    )
    assert r.status_code == 422


def test_draft_requires_auth(client):
    r = client.post("/transactions/x/messages/draft", json={"party_id": "y", "purpose": "general"})
    assert r.status_code in (401, 403)
