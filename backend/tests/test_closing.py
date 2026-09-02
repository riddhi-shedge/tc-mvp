"""Wave 2 closing chain: strictly ordered TC-confirmed steps + the federal
TRID 3-business-day CD review clock (Saturdays count; Sundays and federal
holidays don't — deliberately separate from CA business-day rules)."""

from datetime import date

from app.master.routes import trid_earliest_signing


def _txn(client, tc_headers):
    return client.post(
        "/transactions", json={"property_address": "8 Closing Ct"}, headers=tc_headers
    ).json()["id"]


def _step(client, tc_headers, txn_id, step, occurred_on=None):
    return client.post(
        f"/transactions/{txn_id}/closing/{step}",
        json={"occurred_on": occurred_on} if occurred_on else {},
        headers=tc_headers,
    )


def test_chain_is_strictly_ordered(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    r = _step(client, tc_headers, txn_id, "signed")
    assert r.status_code == 422
    assert "docs_ordered first" in r.json()["detail"]
    assert _step(client, tc_headers, txn_id, "docs_ordered").status_code == 201
    # Same step twice → conflict, not a duplicate row.
    assert _step(client, tc_headers, txn_id, "docs_ordered").status_code == 409


def test_unknown_step_rejected(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    assert _step(client, tc_headers, txn_id, "keys_thrown").status_code == 422


def test_trid_clock_blocks_early_signing(client, tc_headers, repo):
    """CD delivered Thu 2026-09-03: Fri counts (1), Sat counts (2), Sun skipped,
    Mon 9/7 is Labor Day (federal) skipped, Tue 9/8 counts (3) → earliest
    signing 9/8. One date exercises all three TRID rules."""
    assert trid_earliest_signing(date(2026, 9, 3)) == date(2026, 9, 8)

    txn_id = _txn(client, tc_headers)
    assert _step(client, tc_headers, txn_id, "docs_ordered", "2026-09-02").status_code == 201
    assert _step(client, tc_headers, txn_id, "cd_delivered", "2026-09-03").status_code == 201
    early = _step(client, tc_headers, txn_id, "signed", "2026-09-07")
    assert early.status_code == 422 and "TRID" in early.json()["detail"]
    ok = _step(client, tc_headers, txn_id, "signed", "2026-09-08")
    assert ok.status_code == 201

    # The rest of the chain, then verify state + audit.
    assert _step(client, tc_headers, txn_id, "funded", "2026-09-09").status_code == 201
    assert _step(client, tc_headers, txn_id, "recorded", "2026-09-09").status_code == 201
    assert _step(client, tc_headers, txn_id, "keys_released", "2026-09-09").status_code == 201
    state = repo.get_full_state(txn_id)
    assert len(state["closing_events"]) == 6
    assert [a["action"] for a in state["audit_log"]].count("closing.step") == 6
