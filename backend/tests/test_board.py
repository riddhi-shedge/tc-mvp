"""The Deals pipeline board: per-deal rollups, stage moves, and the cross-deal
deadline calendar feed."""


def _deal(client, tc_headers, addr="1 Pipeline Way") -> str:
    return client.post("/transactions", json={"property_address": addr}, headers=tc_headers).json()["id"]


def test_new_deal_starts_at_stage_new(client, tc_headers):
    txn = _deal(client, tc_headers)
    board = client.get("/transactions/board", headers=tc_headers).json()
    row = next(d for d in board if d["id"] == txn)
    assert row["stage"] == "new"
    assert row["property_address"] == "1 Pipeline Way"
    assert row["open_tasks"] == 0 and row["risk_count"] == 0


def test_move_stage(client, tc_headers):
    txn = _deal(client, tc_headers)
    r = client.post(f"/transactions/{txn}/stage", json={"stage": "closing"}, headers=tc_headers)
    assert r.status_code == 200 and r.json()["stage"] == "closing"
    board = client.get("/transactions/board", headers=tc_headers).json()
    assert next(d for d in board if d["id"] == txn)["stage"] == "closing"


def test_invalid_stage_422(client, tc_headers):
    txn = _deal(client, tc_headers)
    r = client.post(f"/transactions/{txn}/stage", json={"stage": "sold"}, headers=tc_headers)
    assert r.status_code == 422


def test_stage_unknown_deal_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/stage",
        json={"stage": "closing"}, headers=tc_headers,
    )
    assert r.status_code == 404


def test_board_rolls_up_tasks_and_risks(client, tc_headers):
    txn = _deal(client, tc_headers)
    t1 = client.post(f"/transactions/{txn}/tasks", json={"title": "a"}, headers=tc_headers).json()["id"]
    client.post(f"/transactions/{txn}/tasks", json={"title": "b"}, headers=tc_headers)
    client.patch(f"/transactions/{txn}/tasks/{t1}", json={"status": "done"}, headers=tc_headers)
    row = next(d for d in client.get("/transactions/board", headers=tc_headers).json() if d["id"] == txn)
    assert row["total_tasks"] == 2 and row["done_tasks"] == 1 and row["open_tasks"] == 1


def test_archived_deal_off_the_board(client, tc_headers):
    txn = _deal(client, tc_headers)
    client.post(f"/transactions/{txn}/archive", headers=tc_headers)
    board = client.get("/transactions/board", headers=tc_headers).json()
    assert all(d["id"] != txn for d in board)


def test_calendar_feed_shape(client, tc_headers, repo):
    txn = _deal(client, tc_headers)
    # inject a deadline directly (compliance would normally create these)
    repo.deadlines.append(
        {"id": "d1", "transaction_id": txn, "name": "Close of escrow", "due_date": "2026-08-15",
         "compute_key": "coe"}
    )
    cal = client.get("/transactions/calendar", headers=tc_headers).json()
    hit = next(d for d in cal if d["transaction_id"] == txn)
    assert hit["due_date"] == "2026-08-15" and hit["property_address"] == "1 Pipeline Way"


def test_board_requires_auth(client):
    assert client.get("/transactions/board").status_code in (401, 403)


def test_open_tasks_feed(client, tc_headers):
    txn = _deal(client, tc_headers)
    t1 = client.post(f"/transactions/{txn}/tasks", json={"title": "Call HOA"}, headers=tc_headers).json()["id"]
    client.post(f"/transactions/{txn}/tasks", json={"title": "Order NHD"}, headers=tc_headers)
    client.patch(f"/transactions/{txn}/tasks/{t1}", json={"status": "done"}, headers=tc_headers)
    tasks = client.get("/transactions/tasks", headers=tc_headers).json()
    mine = [t for t in tasks if t["transaction_id"] == txn]
    assert len(mine) == 1 and mine[0]["title"] == "Order NHD"  # done task excluded
    assert mine[0]["property_address"] == "1 Pipeline Way"


def test_open_tasks_requires_auth(client):
    assert client.get("/transactions/tasks").status_code in (401, 403)
