"""P2 — reply detection + chases. An inbound email that references a message the
SOR sent (In-Reply-To/References ↔ provider_message_id) marks it replied,
auto-clears its follow-up reminder, and drops the "no reply" chase from the
decision queue. Chasing a silent recipient produces a DRAFT (Rule 3) — never a
send. Synthetic content only."""

from __future__ import annotations

import uuid

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"


def _sent_message(client, tc_headers, repo) -> tuple[str, str, str]:
    """A deal with one SENT message (via the real approve path) + its due reminder."""
    txn = client.post(
        "/transactions", json={"property_address": "5 Reply Rd"}, headers=tc_headers
    ).json()["id"]
    client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": "lender@example.test"},
        headers=tc_headers,
    )
    msg_id = client.post(
        f"/transactions/{txn}/messages/draft-lender", headers=tc_headers
    ).json()["message"]["id"]
    r = client.post(
        f"/transactions/{txn}/messages/{msg_id}/approve-and-send", json={}, headers=tc_headers
    )
    assert r.status_code == 200
    provider_id = repo.messages[msg_id]["provider_message_id"]
    # make the auto-created follow-up reminder due NOW so it shows in the queue
    for rem in repo.reminders:
        if rem["message_id"] == msg_id:
            rem["remind_at"] = "2020-01-01T00:00:00+00:00"
    return txn, msg_id, provider_id


def test_reply_marks_message_clears_reminder_and_chase(client, tc_headers, repo):
    txn, msg_id, provider_id = _sent_message(client, tc_headers, repo)
    before = client.get("/transactions/attention", headers=tc_headers).json()
    assert any(i["kind"] == "reminder" and i["messageId"] == msg_id for i in before["items"])

    body = postmark_inbound(subject="Re: loan status")
    body["Headers"] = [{"Name": "In-Reply-To", "Value": f"<{provider_id}@mtasv.net>"}]
    r = client.post(URL, json=body)
    assert r.status_code == 200
    assert r.json()["replied_to"] == [msg_id]

    assert repo.messages[msg_id]["replied_at"]  # marked answered
    assert all(rem["message_id"] != msg_id for rem in repo.reminders)  # reminder cleared
    assert any(a["action"] == "message.replied" for a in repo.audit_log)

    after = client.get("/transactions/attention", headers=tc_headers).json()
    assert not any(i["kind"] == "reminder" and i.get("messageId") == msg_id for i in after["items"])


def test_unrelated_references_match_nothing(client, tc_headers, repo):
    _sent_message(client, tc_headers, repo)
    body = postmark_inbound()
    body["Headers"] = [{"Name": "In-Reply-To", "Value": f"<{uuid.uuid4()}@mtasv.net>"}]
    r = client.post(URL, json=body)
    assert r.status_code == 200
    assert r.json()["replied_to"] == []
    assert not any(a["action"] == "message.replied" for a in repo.audit_log)


def test_draft_chase_creates_a_draft_never_sends(client, tc_headers, repo):
    txn, msg_id, _ = _sent_message(client, tc_headers, repo)
    r = client.post(f"/transactions/{txn}/messages/{msg_id}/draft-chase", headers=tc_headers)
    assert r.status_code == 201
    chase = r.json()["message"]
    assert repo.messages[chase["id"]]["status"] == "draft"  # a draft in the queue — not sent

    # the chase shows up as an approvable decision with its reasoning
    q = client.get("/transactions/attention", headers=tc_headers).json()
    row = next(i for i in q["items"] if i["kind"] == "draft" and i["id"] == chase["id"])
    assert row["body"]  # full content for Rule-3 review

    # chasing an already-answered message is refused
    repo.messages[msg_id]["replied_at"] = "2026-08-31T00:00:00+00:00"
    r2 = client.post(f"/transactions/{txn}/messages/{msg_id}/draft-chase", headers=tc_headers)
    assert r2.status_code == 409
