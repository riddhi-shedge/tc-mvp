"""Task assignment endpoint (Prompt 7) — TC assigns a task to a party.

Assignment is what makes a task belong to a receiving-end party; RLS then keys
off that party_id. Here we assert the assignment, its audit trail, auth, and 404s.
"""

from __future__ import annotations


def _txn(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "1 Assign Way"}, headers=tc_headers
    ).json()["id"]


def _party(client, tc_headers, txn_id) -> str:
    return client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Inspector", "role": "inspector_general"},
        headers=tc_headers,
    ).json()["id"]


def _seed_task(repo, txn_id, task_id="task-1") -> str:
    repo.tasks.append(
        {
            "id": task_id,
            "transaction_id": txn_id,
            "title": "Schedule inspection",
            "status": "pending",
            "assigned_party_id": None,
        }
    )
    return task_id


def test_assign_requires_auth(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    party_id = _party(client, tc_headers, txn_id)
    task_id = _seed_task(repo, txn_id)
    r = client.post(
        f"/transactions/{txn_id}/tasks/{task_id}/assign", json={"party_id": party_id}
    )
    assert r.status_code == 401


def test_assign_sets_party_and_audits(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    party_id = _party(client, tc_headers, txn_id)
    task_id = _seed_task(repo, txn_id)
    r = client.post(
        f"/transactions/{txn_id}/tasks/{task_id}/assign",
        json={"party_id": party_id},
        headers=tc_headers,
    )
    assert r.status_code == 200
    assert r.json()["assigned_party_id"] == party_id
    assert any(
        a["action"] == "task.assigned" and a["entity_id"] == task_id for a in repo.audit_log
    )


def test_assign_unknown_party_is_404(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    task_id = _seed_task(repo, txn_id)
    r = client.post(
        f"/transactions/{txn_id}/tasks/{task_id}/assign",
        json={"party_id": "00000000-0000-0000-0000-000000000000"},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_assign_unknown_task_is_404(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    party_id = _party(client, tc_headers, txn_id)
    r = client.post(
        f"/transactions/{txn_id}/tasks/unknown-task/assign",
        json={"party_id": party_id},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_dashboard_requires_auth(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    r = client.get(f"/transactions/{txn_id}/dashboard")
    assert r.status_code == 401


def test_dashboard_unknown_transaction_is_404(client, tc_headers):
    r = client.get(
        "/transactions/00000000-0000-0000-0000-000000000000/dashboard", headers=tc_headers
    )
    assert r.status_code == 404


def test_dashboard_returns_drilldown_after_assign(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    party_id = _party(client, tc_headers, txn_id)
    task_id = _seed_task(repo, txn_id)
    client.post(
        f"/transactions/{txn_id}/tasks/{task_id}/assign",
        json={"party_id": party_id},
        headers=tc_headers,
    )
    dash = client.get(f"/transactions/{txn_id}/dashboard", headers=tc_headers).json()
    view = next(v for v in dash["parties"] if v["party"]["id"] == party_id)
    assert {t["id"] for t in view["open_tasks"]} == {task_id}
