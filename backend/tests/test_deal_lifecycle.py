"""Archiving (soft, reversible, keeps the audit trail) and hard-deleting (cascades
everything) a deal."""


def _deal(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "9 Gone Ct (synthetic)"}, headers=tc_headers
    ).json()["id"]


def test_archive_then_unarchive(client, tc_headers, repo):
    txn = _deal(client, tc_headers)
    r = client.post(f"/transactions/{txn}/archive", headers=tc_headers)
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert repo.transactions[txn]["status"] == "archived"
    # audit trail kept
    assert any(a["action"] == "transaction.archived" for a in repo.audit_log)

    r = client.post(f"/transactions/{txn}/unarchive", headers=tc_headers)
    assert r.status_code == 200 and r.json()["status"] == "open"


def test_archived_deal_is_not_compliance_active(client, tc_headers, repo):
    txn = _deal(client, tc_headers)
    assert txn in repo.list_active_transaction_ids()
    client.post(f"/transactions/{txn}/archive", headers=tc_headers)
    assert txn not in repo.list_active_transaction_ids()


def test_hard_delete_removes_deal_and_children(client, tc_headers, repo):
    txn = _deal(client, tc_headers)
    client.post(
        f"/transactions/{txn}/parties", json={"name": "P", "role": "buyer"}, headers=tc_headers
    )
    client.post(f"/transactions/{txn}/tasks", json={"title": "t"}, headers=tc_headers)

    r = client.delete(f"/transactions/{txn}", headers=tc_headers)
    assert r.status_code == 204

    assert client.get(f"/transactions/{txn}", headers=tc_headers).status_code == 404
    assert txn not in repo.transactions
    assert not any(p["transaction_id"] == txn for p in repo.parties.values())
    assert not any(t["transaction_id"] == txn for t in repo.tasks)
    assert not any(a["transaction_id"] == txn for a in repo.audit_log)


def test_delete_unknown_deal_404(client, tc_headers):
    r = client.delete(
        "/transactions/00000000-0000-0000-0000-000000000000", headers=tc_headers
    )
    assert r.status_code == 404


def test_archive_unknown_deal_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/archive", headers=tc_headers
    )
    assert r.status_code == 404


def test_lifecycle_requires_auth(client):
    assert client.delete("/transactions/x").status_code in (401, 403)
    assert client.post("/transactions/x/archive").status_code in (401, 403)
