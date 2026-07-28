"""TC-created tasks: the coordinator can add their own ad-hoc tasks alongside the
compliance-generated ones, assign them, and change their status."""


def _bare_deal(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "5 Task Ln (synthetic)"}, headers=tc_headers
    ).json()["id"]


def test_create_task_lands_pending_and_tc_sourced(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/tasks", json={"title": "Call the HOA"}, headers=tc_headers
    )
    assert r.status_code == 201
    task = r.json()
    assert task["title"] == "Call the HOA"
    assert task["status"] == "pending"
    assert task["generated_by"] == "tc"

    tasks = client.get(f"/transactions/{txn}", headers=tc_headers).json()["tasks"]
    assert any(t["id"] == task["id"] for t in tasks)


def test_create_task_with_valid_party(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    pid = client.post(
        f"/transactions/{txn}/parties", json={"name": "Esc", "role": "escrow"}, headers=tc_headers
    ).json()["id"]
    r = client.post(
        f"/transactions/{txn}/tasks",
        json={"title": "Confirm escrow opened", "assigned_party_id": pid},
        headers=tc_headers,
    )
    assert r.status_code == 201 and r.json()["assigned_party_id"] == pid


def test_create_task_unknown_party_404(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/tasks",
        json={"title": "x", "assigned_party_id": "00000000-0000-0000-0000-000000000000"},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_create_task_unknown_deal_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/tasks",
        json={"title": "x"},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_mark_task_done(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    tid = client.post(
        f"/transactions/{txn}/tasks", json={"title": "Order NHD"}, headers=tc_headers
    ).json()["id"]
    r = client.patch(f"/transactions/{txn}/tasks/{tid}", json={"status": "done"}, headers=tc_headers)
    assert r.status_code == 200 and r.json()["status"] == "done"


def test_update_task_bad_status_422(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    tid = client.post(
        f"/transactions/{txn}/tasks", json={"title": "t"}, headers=tc_headers
    ).json()["id"]
    r = client.patch(
        f"/transactions/{txn}/tasks/{tid}", json={"status": "finished"}, headers=tc_headers
    )
    assert r.status_code == 422


def test_update_unknown_task_404(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    r = client.patch(
        f"/transactions/{txn}/tasks/00000000-0000-0000-0000-000000000000",
        json={"status": "done"},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_create_task_requires_auth(client):
    r = client.post("/transactions/x/tasks", json={"title": "t"})
    assert r.status_code in (401, 403)


def test_create_task_with_metadata_roundtrips(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/tasks",
        json={
            "title": "Order NHD report",
            "description": "Natural Hazard Disclosure from JCP-LGS before contingency removal.",
            "due_date": "2026-08-05",
            "priority": "high",
        },
        headers=tc_headers,
    )
    assert r.status_code == 201

    tasks = client.get(f"/transactions/{txn}", headers=tc_headers).json()["tasks"]
    t = next(t for t in tasks if t["title"] == "Order NHD report")
    assert t["description"].startswith("Natural Hazard")
    assert t["due_date"] == "2026-08-05"
    assert t["priority"] == "high"


def test_create_task_defaults_priority_normal(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    client.post(f"/transactions/{txn}/tasks", json={"title": "Plain task"}, headers=tc_headers)
    t = next(
        t for t in client.get(f"/transactions/{txn}", headers=tc_headers).json()["tasks"]
        if t["title"] == "Plain task"
    )
    assert t["priority"] == "normal"
    assert t["description"] is None and t["due_date"] is None


def test_create_task_bogus_priority_coerced(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/tasks",
        json={"title": "Weird", "priority": "SUPER-DUPER"},
        headers=tc_headers,
    )
    assert r.status_code == 201
    t = next(
        t for t in client.get(f"/transactions/{txn}", headers=tc_headers).json()["tasks"]
        if t["title"] == "Weird"
    )
    assert t["priority"] == "normal"
