"""Wave 3A ops lanes: one ordered->done mini-chain per lane, TC-advanced only."""


def _txn(client, tc_headers):
    return client.post(
        "/transactions", json={"property_address": "3 Ops Way"}, headers=tc_headers
    ).json()["id"]


def _adv(client, tc_headers, txn_id, lane, status, occurred_on=None):
    body = {"status": status}
    if occurred_on:
        body["occurred_on"] = occurred_on
    return client.post(f"/transactions/{txn_id}/ops/{lane}", json=body, headers=tc_headers)


def test_lane_lifecycle_and_audit(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    # done before ordered → invalid
    assert _adv(client, tc_headers, txn_id, "hoa", "done").status_code == 409
    r = _adv(client, tc_headers, txn_id, "hoa", "ordered", "2026-09-02")
    assert r.status_code == 201 and r.json()["status"] == "ordered"
    # ordering twice → invalid (one chain per lane)
    assert _adv(client, tc_headers, txn_id, "hoa", "ordered").status_code == 409
    done = _adv(client, tc_headers, txn_id, "hoa", "done", "2026-09-05")
    assert done.status_code == 201 and done.json()["completed_on"] == "2026-09-05"
    # done twice → invalid
    assert _adv(client, tc_headers, txn_id, "hoa", "done").status_code == 409

    state = repo.get_full_state(txn_id)
    assert state["ops_items"][0]["lane"] == "hoa"
    assert [a["action"] for a in state["audit_log"]].count("ops.advanced") == 2


def test_lanes_are_independent_and_validated(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    assert _adv(client, tc_headers, txn_id, "gardening", "ordered").status_code == 422
    for lane in ("warranty", "nhd", "utilities"):
        assert _adv(client, tc_headers, txn_id, lane, "ordered").status_code == 201
    assert len(repo.get_full_state(txn_id)["ops_items"]) == 3


def test_cancellation_unwind(client, tc_headers, repo):
    """Wave 4B: unwind only on a canceled deal; disposition is a status word."""
    txn_id = _txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/cancellation",
        json={"deposit_disposition": "released_to_buyer"},
        headers=tc_headers,
    )
    assert r.status_code == 409  # not canceled yet
    client.post(
        f"/transactions/{txn_id}/cancel", json={"reason": "buyer withdrew"}, headers=tc_headers
    )
    r = client.post(
        f"/transactions/{txn_id}/cancellation",
        json={"deposit_disposition": "released_to_buyer", "canceled_on": "2026-09-01"},
        headers=tc_headers,
    )
    assert r.status_code == 200
    assert r.json()["deposit_disposition"] == "released_to_buyer"
    assert r.json()["canceled_on"] == "2026-09-01"
    actions = [a["action"] for a in repo.get_full_state(txn_id)["audit_log"]]
    assert "cancellation.recorded" in actions
    # Amounts can never sneak in through the enum.
    bad = client.post(
        f"/transactions/{txn_id}/cancellation",
        json={"deposit_disposition": "$15,000 to buyer"},
        headers=tc_headers,
    )
    assert bad.status_code == 422
