"""P1 — the TC decision queue: every pending decision across the book, worst
first, with the full draft body + recipient riding along (Rule 3: nothing is
approvable without seeing exactly what would go out)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.common.dates import ca_today
from app.master.attention import build_attention


def _iso(days: int) -> str:
    return (ca_today() + timedelta(days=days)).isoformat()


def _state(tid: str = "d1", **over) -> dict:
    base = {
        "transaction": {"id": tid, "status": "open", "stage": "cont"},
        "property": {"address": "21989 McClellan Rd"},
        "effective_fields": {},
        "parties": [{"id": "p1", "name": "Wells Fargo", "role": "lender"}],
        "messages": [], "reminders": [], "risk_flags": [], "deadlines": [],
        "timeline_gate": {"ready": True, "missing_fields": [], "unconfirmed_fields": []},
    }
    base.update(over)
    return base


def test_draft_rows_carry_recipient_and_full_body():
    st = _state(messages=[{
        "id": "m1", "status": "draft", "subject": "Loan status?", "body": "Full draft body here",
        "party_id": "p1", "created_at": "2026-08-30T10:00:00Z",
    }])
    out = build_attention([st])
    assert out["counts"]["drafts"] == 1
    row = next(i for i in out["items"] if i["kind"] == "draft")
    assert row["body"] == "Full draft body here"          # Rule 3: full content in the queue
    assert row["recipientName"] == "Wells Fargo" and row["recipientRole"] == "lender"


def test_due_reminder_surfaces_and_future_or_replied_do_not():
    now = datetime.now(timezone.utc)
    st = _state(
        messages=[
            {"id": "m1", "status": "sent", "subject": "Sent A", "party_id": "p1"},
            {"id": "m2", "status": "sent", "subject": "Sent B", "party_id": "p1",
             "replied_at": now.isoformat()},  # answered — P2 clears the chase
        ],
        reminders=[
            {"id": "r1", "message_id": "m1", "remind_at": (now - timedelta(days=1)).isoformat(), "note": None},
            {"id": "r2", "message_id": "m1", "remind_at": (now + timedelta(days=3)).isoformat(), "note": None},
            {"id": "r3", "message_id": "m2", "remind_at": (now - timedelta(days=1)).isoformat(), "note": None},
        ],
    )
    out = build_attention([st])
    ids = {i["id"] for i in out["items"] if i["kind"] == "reminder"}
    assert ids == {"r1"}  # due + unanswered only
    assert out["counts"]["remindersDue"] == 1


def test_gate_and_risk_rows():
    st = _state(
        timeline_gate={"ready": False, "missing_fields": ["acceptance_date"], "unconfirmed_fields": ["purchase_price"]},
        deadlines=[{"id": "dl1", "name": "Loan contingency", "due_date": _iso(1)}],
        risk_flags=[
            {"id": "f1", "deadline_id": "dl1", "severity": "critical", "description": "Loan contingency at risk", "resolved": False},
            {"id": "f2", "deadline_id": None, "severity": "warning", "description": "Old", "resolved": True},
        ],
    )
    out = build_attention([st])
    kinds = {i["kind"] for i in out["items"]}
    assert {"gate", "risk"} <= kinds
    assert out["counts"]["gateBlockedDeals"] == 1 and out["counts"]["riskFlags"] == 1
    gate = next(i for i in out["items"] if i["kind"] == "gate")
    assert set(gate["fields"]) == {"acceptance_date", "purchase_price"}


def test_queue_sorted_worst_first_and_horizon_includes_overdue():
    st = _state(
        deadlines=[
            {"id": "a", "name": "Overdue thing", "due_date": _iso(-2)},
            {"id": "b", "name": "Far thing", "due_date": _iso(60)},
        ],
        risk_flags=[
            {"id": "f1", "deadline_id": "a", "severity": "critical", "description": "Overdue", "resolved": False},
            {"id": "f2", "deadline_id": "b", "severity": "warning", "description": "Far", "resolved": False},
        ],
    )
    out = build_attention([st])
    risks = [i for i in out["items"] if i["kind"] == "risk"]
    assert risks[0]["id"] == "f1"  # overdue outranks later
    labels = {h["label"] for h in out["horizon"]}
    assert "Overdue thing" in labels and "Far thing" not in labels  # horizon is bounded


def test_attention_route_rolls_up_the_book(client, tc_headers):
    txn = client.post(
        "/transactions", json={"property_address": "7 Queue Way"}, headers=tc_headers
    ).json()["id"]
    client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": "lender@ex.test"},
        headers=tc_headers,
    )
    client.post(f"/transactions/{txn}/messages/draft-lender", headers=tc_headers)

    r = client.get("/transactions/attention", headers=tc_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["drafts"] >= 1
    draft = next(i for i in body["items"] if i["kind"] == "draft")
    assert draft["dealId"] == txn and draft["body"]  # full content rides along (Rule 3)
    assert "horizonCutoff" in body


def test_closed_and_archived_deals_are_excluded():
    closed = _state(tid="c1", transaction={"id": "c1", "status": "open", "stage": "closed"},
                    messages=[{"id": "m", "status": "draft", "subject": "x", "body": "y", "party_id": None}])
    archived = _state(tid="a1", transaction={"id": "a1", "status": "archived", "stage": "cont"},
                      messages=[{"id": "m2", "status": "draft", "subject": "x", "body": "y", "party_id": None}])
    out = build_attention([closed, archived])
    assert out["total"] == 0 and out["counts"]["drafts"] == 0
