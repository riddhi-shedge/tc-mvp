"""Rule-3 hardening: a message can be approved exactly once — a double-click or
concurrent duplicate never records a second Approval or reaches the mailer twice.
"""

import time

import jwt

from app.master.repo import _message_lock
from tests.conftest import TEST_JWT_SECRET


def _agent_token(party_id: str, transaction_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": f"party-{party_id}", "role": "authenticated", "aud": "authenticated",
            "aal": "aal1", "iat": now, "exp": now + 3600,
            "app_metadata": {"party_id": party_id, "transaction_id": transaction_id, "tier": "collaborator"},
        },
        TEST_JWT_SECRET, algorithm="HS256",
    )


def _deal_with_agent_draft(client, tc_headers):
    txn = client.post(
        "/transactions", json={"property_address": "9 Race Ct"}, headers=tc_headers
    ).json()["id"]
    agent_id = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Dinesh Shedge", "role": "buyer_agent", "email": "agent@ex.test"},
        headers=tc_headers,
    ).json()["id"]
    client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": "lender@ex.test"},
        headers=tc_headers,
    )
    msg_id = client.post(
        f"/transactions/{txn}/messages/draft-lender", headers=tc_headers
    ).json()["message"]["id"]
    return txn, agent_id, msg_id


def test_double_approve_records_exactly_one_approval(client, tc_headers, repo):
    txn, agent_id, msg_id = _deal_with_agent_draft(client, tc_headers)
    h = {"Authorization": f"Bearer {_agent_token(agent_id, txn)}"}

    r1 = client.post(f"/agent/approvals/{msg_id}/approve", json={"transaction_id": txn}, headers=h)
    assert r1.status_code == 201
    # The duplicate (double-click / concurrent loser) is idempotent, not a second Approval.
    r2 = client.post(f"/agent/approvals/{msg_id}/approve", json={"transaction_id": txn}, headers=h)
    assert r2.status_code == 201

    approvals = [a for a in repo.approvals if a["message_id"] == msg_id]
    assert len(approvals) == 1  # exactly one Approval record
    audits = [
        a for a in repo.audit_log
        if a["action"] == "message.approved" and a["entity_id"] == msg_id
    ]
    assert len(audits) == 1  # and exactly one audit event


def test_reapprove_applies_edits_without_new_approval(client, tc_headers, repo):
    txn, agent_id, msg_id = _deal_with_agent_draft(client, tc_headers)
    h = {"Authorization": f"Bearer {_agent_token(agent_id, txn)}"}
    client.post(f"/agent/approvals/{msg_id}/approve", json={"transaction_id": txn}, headers=h)
    client.post(
        f"/agent/approvals/{msg_id}/approve",
        json={"transaction_id": txn, "body": "Edited after approval"},
        headers=h,
    )
    assert repo.messages[msg_id]["body"] == "Edited after approval"
    assert len([a for a in repo.approvals if a["message_id"] == msg_id]) == 1


def test_message_lock_is_per_message():
    a1 = _message_lock("msg-a")
    a2 = _message_lock("msg-a")
    b = _message_lock("msg-b")
    assert a1 is a2  # same message -> same lock (serializes approve+send)
    assert a1 is not b  # different messages don't contend
