"""Repair loop (Wave 1): TC-created repair items, human-only resolution."""


def _txn(client, tc_headers):
    return client.post(
        "/transactions", json={"property_address": "4 Repair Rd"}, headers=tc_headers
    ).json()["id"]


def test_repair_lifecycle_with_audit(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/repairs",
        json={"description": "Section 1 termite clearance — rear fascia"},
        headers=tc_headers,
    )
    assert r.status_code == 201
    rid = r.json()["id"]
    state = repo.get_full_state(txn_id)
    assert state["repairs"][0]["status"] == "open"

    done = client.post(f"/transactions/{txn_id}/repairs/{rid}/resolve", headers=tc_headers)
    assert done.status_code == 200
    assert done.json()["status"] == "resolved"
    actions = [a["action"] for a in repo.get_full_state(txn_id)["audit_log"]]
    assert "repair.added" in actions and "repair.resolved" in actions
    # Resolving twice: the open row no longer exists.
    again = client.post(f"/transactions/{txn_id}/repairs/{rid}/resolve", headers=tc_headers)
    assert again.status_code == 404


def test_rr_doc_type_detected_from_filename(client, tc_headers):
    import base64
    item = client.post(
        "/ingestion/manual-upload",
        json={
            "filename": "Request for Repairs - 4 Repair Rd.pdf",
            "content_base64": base64.b64encode(b"PDF-synthetic-rr").decode(),
        },
        headers=tc_headers,
    ).json()
    assert item["detected_doc_type"] == "request_for_repairs"


def test_nbp_notice_lifecycle(client, tc_headers, repo):
    """NBP tracker: D2 too-early guard, D3 cure clock, human cure, audit."""
    from datetime import timedelta
    from app.common.dates import ca_today

    txn_id = _txn(client, tc_headers)
    due = (ca_today() + timedelta(days=5)).isoformat()
    repo.deadlines.append(
        {"id": "dl-1", "transaction_id": txn_id, "name": "Inspection contingency", "due_date": due}
    )
    # Too early: 3 days before the deadline (earliest allowed is due-2).
    early = (ca_today() + timedelta(days=1)).isoformat()
    r = client.post(
        f"/transactions/{txn_id}/notices",
        json={"deadline_id": "dl-1", "served_date": early},
        headers=tc_headers,
    )
    assert r.status_code == 422 and "D2" in r.json()["detail"]
    # Valid: exactly 2 days before.
    ok_day = (ca_today() + timedelta(days=3)).isoformat()
    r = client.post(
        f"/transactions/{txn_id}/notices",
        json={"deadline_id": "dl-1", "served_date": ok_day},
        headers=tc_headers,
    )
    assert r.status_code == 201
    n = r.json()
    assert n["cure_expires"] == (ca_today() + timedelta(days=5)).isoformat()  # served+2 (D3)
    cured = client.post(f"/transactions/{txn_id}/notices/{n['id']}/cure", headers=tc_headers)
    assert cured.status_code == 200 and cured.json()["status"] == "cured"
    actions = [a["action"] for a in repo.get_full_state(txn_id)["audit_log"]]
    assert "notice.served" in actions and "notice.cured" in actions
