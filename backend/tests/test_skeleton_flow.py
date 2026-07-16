"""Phase 2 "done when" at the API level: a synthetic email walks the whole
slice and a fake "sent" lands in the audit log. Synthetic data only."""

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound


def test_full_walking_skeleton(client, tc_headers, repo):
    # 1 Detect — synthetic email hits the dedicated deal address
    hook = client.post(
        f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}", json=postmark_inbound()
    )
    item_id = hook.json()["id"]
    assert repo.transactions == {}  # nothing committed yet (HITL)

    # 2 Create (HITL) — TC confirms "new deal"
    txn_id = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]

    # 3 Extract (stub) + 4 Confirm
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    field_ids = [f["id"] for f in state["extracted_fields"]]
    assert field_ids
    r = client.post(
        f"/transactions/{txn_id}/fields/confirm",
        json={"field_ids": field_ids},
        headers=tc_headers,
    )
    assert r.json()["confirmed"] == len(field_ids)

    # 5 Timeline (hardcoded stub)
    assert (
        client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers).status_code == 201
    )

    # 6 Draft (stub lender follow-up) — needs a lender contact to send to
    client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": "lender@example.test"},
        headers=tc_headers,
    )
    msg_id = client.post(f"/transactions/{txn_id}/messages/draft-stub", headers=tc_headers).json()[
        "message"
    ]["id"]

    # 7 Send (via the test mailer) — only after human approval
    r = client.post(
        f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send", headers=tc_headers
    )
    assert r.status_code == 200

    # Done when: every step is in the audit log and the message sent.
    final = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    actions = [a["action"] for a in final["audit_log"]]
    for expected in (
        "transaction.created",
        "payload.written",
        "field.confirmed",
        "timeline.stub_generated",
        "message.drafted",
        "message.approved",
        "message.sent",
    ):
        assert expected in actions, f"missing audit action: {expected}"
    sent_row = next(a for a in final["audit_log"] if a["action"] == "message.sent")
    assert sent_row["details"]["provider_message_id"]  # a real (test) send id
    assert any(m["status"] == "sent" for m in final["messages"])
    assert len(final["approvals"]) == 1
