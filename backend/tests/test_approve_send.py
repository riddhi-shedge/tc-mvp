"""Approve, edit & send (Rule 3): the ONLY path to 'sent'. Real send is guarded;
tests use the fake mailer so nothing leaves the system."""

import pytest

from app.master.mailer import RecipientNotAllowed, SendDisabled
from tests.fake_mailer import FakeMailer


def _deal_with_draft(client, tc_headers, *, email="lender@example.test") -> tuple[str, str]:
    txn_id = client.post(
        "/transactions", json={"property_address": "1 Send Way"}, headers=tc_headers
    ).json()["id"]
    client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": email},
        headers=tc_headers,
    )
    msg_id = client.post(
        f"/transactions/{txn_id}/messages/draft-lender", headers=tc_headers
    ).json()["message"]["id"]
    return txn_id, msg_id


def test_approval_recorded_before_send_and_edits_applied(client, tc_headers, repo, mailer):
    txn_id, msg_id = _deal_with_draft(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send",
        json={"subject": "Edited subject", "body": "Edited body by the TC"},
        headers=tc_headers,
    )
    assert r.status_code == 200
    sent = r.json()["message"]
    assert sent["status"] == "sent" and sent["sent_at"]
    assert sent["subject"] == "Edited subject"  # the TC's edits are what shipped

    # The mailer received the edited content addressed to the lender.
    assert mailer.sent == [
        {"to": "lender@example.test", "subject": "Edited subject", "body": "Edited body by the TC"}
    ]
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    actions = [a["action"] for a in state["audit_log"]]
    assert actions.index("message.approved") < actions.index("message.sent")
    assert len(state["approvals"]) == 1
    assert len(state["reminders"]) == 1  # follow-up set on send


def test_guarded_postmark_blocks_when_send_disabled(client, tc_headers, repo, monkeypatch):
    """The real mailer refuses when SEND_ENABLED != true — message stays approved."""
    from app.master.mailer import PostmarkMailer
    from app.master.routes import get_mailer
    from app.main import app

    monkeypatch.delenv("SEND_ENABLED", raising=False)
    app.dependency_overrides[get_mailer] = lambda: PostmarkMailer()
    txn_id, msg_id = _deal_with_draft(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send", headers=tc_headers
    )
    assert r.status_code == 503  # SendDisabled
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    msg = next(m for m in state["messages"] if m["id"] == msg_id)
    assert msg["status"] == "approved"  # approved but NOT sent — retryable
    assert not any(m["status"] == "sent" for m in state["messages"])
    # The Approval was still recorded (the human acted); it just didn't send.
    assert len(state["approvals"]) == 1


def test_guarded_postmark_blocks_recipient_not_allowlisted(client, tc_headers, monkeypatch):
    from app.master.mailer import PostmarkMailer
    from app.master.routes import get_mailer
    from app.main import app

    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.setenv("SEND_ALLOWLIST", "someone-else@example.test")
    app.dependency_overrides[get_mailer] = lambda: PostmarkMailer()
    txn_id, msg_id = _deal_with_draft(client, tc_headers, email="not-allowed@example.test")
    r = client.post(
        f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send", headers=tc_headers
    )
    assert r.status_code == 403  # RecipientNotAllowed


def test_send_failure_leaves_message_approved(client, tc_headers):
    from app.master.mailer import SendFailed
    from app.master.routes import get_mailer
    from app.main import app

    app.dependency_overrides[get_mailer] = lambda: FakeMailer(raises=SendFailed("synthetic"))
    txn_id, msg_id = _deal_with_draft(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send", headers=tc_headers
    )
    assert r.status_code == 502
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert next(m for m in state["messages"] if m["id"] == msg_id)["status"] == "approved"


def test_approved_but_unsent_can_be_retried_without_new_approval(client, tc_headers, monkeypatch):
    """A guarded/failed send leaves the message 'approved'; retrying sends it
    with NO second Approval (the human already approved)."""
    from app.master.mailer import PostmarkMailer
    from app.master.routes import get_mailer
    from app.main import app

    # First attempt: guard off -> 503, message stuck 'approved'.
    monkeypatch.delenv("SEND_ENABLED", raising=False)
    app.dependency_overrides[get_mailer] = lambda: PostmarkMailer()
    txn_id, msg_id = _deal_with_draft(client, tc_headers)
    url = f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send"
    assert client.post(url, headers=tc_headers).status_code == 503

    # Retry with a working mailer -> sent; still exactly one Approval.
    sent_mailer = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: sent_mailer
    assert client.post(url, headers=tc_headers).status_code == 200
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert next(m for m in state["messages"] if m["id"] == msg_id)["status"] == "sent"
    assert len(state["approvals"]) == 1  # NOT re-approved on retry
    assert len(sent_mailer.sent) == 1


def test_drafted_wiring_content_is_rejected(client, tc_headers, drafter):
    """Rule 2 defense in depth: a draft that slipped in wiring language is not
    persisted, even though the prompt forbids it."""
    from app.master.drafting import LenderDraft

    txn_id = client.post(
        "/transactions", json={"property_address": "x"}, headers=tc_headers
    ).json()["id"]
    client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "L", "role": "lender", "email": "l@example.test"},
        headers=tc_headers,
    )
    drafter.override = LenderDraft(
        subject="Wire the funds",
        body="Please send the wire to routing number 000.",
        why="x",
    )
    r = client.post(f"/transactions/{txn_id}/messages/draft-lender", headers=tc_headers)
    assert r.status_code == 422
    assert "rule 2" in r.json()["detail"].lower()
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert state["messages"] == []  # nothing persisted


def test_cannot_approve_send_twice(client, tc_headers):
    txn_id, msg_id = _deal_with_draft(client, tc_headers)
    url = f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send"
    assert client.post(url, headers=tc_headers).status_code == 200
    assert client.post(url, headers=tc_headers).status_code == 409


def test_message_without_recipient_is_409(client, tc_headers, repo):
    """A draft whose party has no email can't be sent — ask for a contact."""
    txn_id = client.post(
        "/transactions", json={"property_address": "x"}, headers=tc_headers
    ).json()["id"]
    # Lender with NO email.
    client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "No Email Lender", "role": "lender"},
        headers=tc_headers,
    )
    msg_id = client.post(
        f"/transactions/{txn_id}/messages/draft-lender", headers=tc_headers
    ).json()["message"]["id"]
    r = client.post(
        f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send", headers=tc_headers
    )
    assert r.status_code == 409
    assert "recipient" in r.json()["detail"].lower()


def test_mailer_guard_unit(monkeypatch):
    """The guard itself, without the API."""
    from app.master.mailer import PostmarkMailer

    monkeypatch.delenv("SEND_ENABLED", raising=False)
    with pytest.raises(SendDisabled):
        PostmarkMailer().send(to="a@example.test", subject="s", body="b")

    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.setenv("SEND_ALLOWLIST", "allowed@example.test")
    with pytest.raises(RecipientNotAllowed):
        PostmarkMailer().send(to="other@example.test", subject="s", body="b")
