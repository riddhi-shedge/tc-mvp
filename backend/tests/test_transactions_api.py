"""Prompt 1 "done when": create a transaction and read its full state through
the API, with the audit log recording each change. Synthetic data only."""


def _create(client, tc_headers, address="742 Synthetic Ave, Testville CA"):
    r = client.post("/transactions", json={"property_address": address}, headers=tc_headers)
    assert r.status_code == 201
    return r.json()


def test_create_returns_transaction_with_property(client, tc_headers):
    created = _create(client, tc_headers)
    assert created["id"]
    assert created["status"] == "open"
    assert created["property"]["address"] == "742 Synthetic Ave, Testville CA"
    assert created["property"]["state"] == "CA"


def test_create_requires_property_address(client, tc_headers):
    r = client.post("/transactions", json={}, headers=tc_headers)
    assert r.status_code == 422


def test_full_state_reads_back_through_api(client, tc_headers):
    created = _create(client, tc_headers)
    r = client.get(f"/transactions/{created['id']}", headers=tc_headers)
    assert r.status_code == 200
    state = r.json()
    assert state["transaction"]["id"] == created["id"]
    assert state["property"]["address"] == "742 Synthetic Ave, Testville CA"
    # Every §10 collection is present in the deal state, even when empty.
    for key in (
        "parties",
        "documents",
        "payloads",
        "extracted_fields",
        "deadlines",
        "tasks",
        "messages",
        "reminders",
        "risk_flags",
        "approvals",
        "audit_log",
    ):
        assert key in state


def test_unknown_transaction_is_404(client, tc_headers):
    r = client.get("/transactions/00000000-0000-0000-0000-000000000000", headers=tc_headers)
    assert r.status_code == 404


def test_db_failure_returns_clean_502(client, tc_headers, repo, monkeypatch):
    """A DB-boundary failure surfaces as a generic 502 — no internals leaked."""
    from postgrest.exceptions import APIError

    def boom(**kwargs):
        raise APIError({"message": "synthetic failure", "code": "XX000"})

    monkeypatch.setattr(repo, "create_transaction", boom)
    r = client.post(
        "/transactions", json={"property_address": "1 Synthetic Way"}, headers=tc_headers
    )
    assert r.status_code == 502
    assert r.json() == {"detail": "Database operation failed"}


def test_create_writes_audit_row(client, tc_headers, repo):
    created = _create(client, tc_headers)
    actions = [a["action"] for a in repo.audit_log]
    assert "transaction.created" in actions
    row = repo.audit_log[-1]
    assert row["transaction_id"] == created["id"]
    assert row["actor"] == "tc@example.test"
    assert row["created_at"]


def test_cancel_and_reactivate_deal(client, tc_headers):
    txn = client.post("/transactions", json={"property_address": "9 Fell St"}, headers=tc_headers).json()["id"]
    r = client.post(f"/transactions/{txn}/cancel", json={"reason": "buyer backed out"}, headers=tc_headers)
    assert r.status_code == 200 and r.json()["status"] == "canceled"
    # still visible on the board (not hidden like archive), tagged canceled
    board = client.get("/transactions/board", headers=tc_headers).json()
    assert any(d["id"] == txn and d["status"] == "canceled" for d in board)
    # reactivate
    r2 = client.post(f"/transactions/{txn}/reactivate", headers=tc_headers)
    assert r2.status_code == 200 and r2.json()["status"] == "open"
