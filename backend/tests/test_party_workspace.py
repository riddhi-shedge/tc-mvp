"""Each invited stakeholder's own scoped workspace: they see the roster + process
+ THEIR tasks/documents, can complete their tasks and upload docs — and can't
reach the TC API or another deal."""

import base64
import time

import jwt

from tests.conftest import TEST_JWT_SECRET


def _party_token(party_id: str, transaction_id: str, tier: str = "collaborator") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": f"party-{party_id}", "role": "authenticated", "aud": "authenticated",
            "aal": "aal1", "iat": now, "exp": now + 3600,
            "app_metadata": {"party_id": party_id, "transaction_id": transaction_id, "tier": tier},
        },
        TEST_JWT_SECRET, algorithm="HS256",
    )


def _deal_with_agent_and_task(client, tc_headers):
    txn = client.post("/transactions", json={"property_address": "22 Shared Way"}, headers=tc_headers).json()["id"]
    pid = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Basant Somani", "role": "buyer_agent", "email": "agent@ex.test"},
        headers=tc_headers,
    ).json()["id"]
    # a second party so the roster has more than one entry
    client.post(f"/transactions/{txn}/parties", json={"name": "Christina Luk", "role": "seller"}, headers=tc_headers)
    task = client.post(
        f"/transactions/{txn}/tasks",
        json={"title": "Send buyer's proof of funds", "assigned_party_id": pid},
        headers=tc_headers,
    ).json()
    return txn, pid, task["id"]


def test_workspace_scoped_to_party(client, tc_headers):
    txn, pid, task_id = _deal_with_agent_and_task(client, tc_headers)
    h = {"Authorization": f"Bearer {_party_token(pid, txn)}"}
    ws = client.get("/party/workspace", headers=h)
    assert ws.status_code == 200
    body = ws.json()
    assert body["me"]["name"] == "Basant Somani" and body["me"]["role"] == "buyer_agent"
    # everyone sees WHO is involved (names + roles), but no contact/financials
    roster_roles = {p["role"] for p in body["roster"]}
    assert roster_roles == {"buyer_agent", "seller"}
    assert all("email" not in p and "phone" not in p for p in body["roster"])
    # only THEIR task
    assert [t["id"] for t in body["my_tasks"]] == [task_id]
    assert "purchase_price" not in body  # no deal financials leaked


def test_party_completes_own_task(client, tc_headers):
    txn, pid, task_id = _deal_with_agent_and_task(client, tc_headers)
    h = {"Authorization": f"Bearer {_party_token(pid, txn)}"}
    r = client.post(f"/party/tasks/{task_id}/status", json={"status": "done"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "done"


def test_party_cannot_touch_a_task_not_theirs(client, tc_headers):
    txn, pid, _ = _deal_with_agent_and_task(client, tc_headers)
    other = client.post(f"/transactions/{txn}/tasks", json={"title": "TC-only task"}, headers=tc_headers).json()["id"]
    h = {"Authorization": f"Bearer {_party_token(pid, txn)}"}
    assert client.post(f"/party/tasks/{other}/status", json={"status": "done"}, headers=h).status_code == 404


def test_party_uploads_document(client, tc_headers):
    txn, pid, _ = _deal_with_agent_and_task(client, tc_headers)
    h = {"Authorization": f"Bearer {_party_token(pid, txn)}"}
    content = base64.b64encode(b"%PDF-1.4 proof of funds").decode()
    r = client.post(
        "/party/documents",
        json={"filename": "pof.pdf", "content_base64": content, "doc_type": "proof_of_funds"},
        headers=h,
    )
    assert r.status_code == 201
    ws = client.get("/party/workspace", headers=h).json()
    assert any(d["doc_type"] == "proof_of_funds" for d in ws["my_documents"])


def test_party_token_rejected_by_tc_api_and_missing_token_401(client, tc_headers):
    txn, pid, _ = _deal_with_agent_and_task(client, tc_headers)
    h = {"Authorization": f"Bearer {_party_token(pid, txn)}"}
    # the party token must NOT work on a TC endpoint
    assert client.get(f"/transactions/{txn}", headers=h).status_code == 401
    # and the party API needs a party token
    assert client.get("/party/workspace").status_code == 401
    assert client.get("/party/workspace", headers=tc_headers).status_code == 401
