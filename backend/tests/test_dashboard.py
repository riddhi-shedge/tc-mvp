"""Dashboard aggregation (Prompt 7) — pure view over the SOR full-state.

Exercised against the in-memory repo: build a synthetic transaction with
parties, tasks, documents, messages and risk flags, then assert the drill-down,
role rollups, prioritized alerts and communication grouping.
"""

from __future__ import annotations

from app.master.dashboard import build_dashboard
from tests.fake_repo import InMemoryRepo


def _seed() -> tuple[InMemoryRepo, str, dict]:
    repo = InMemoryRepo()
    txn = repo.create_transaction(property_address="1 Dashboard Way", actor="tc@example.test")
    txn_id = txn["id"]
    buyer1 = repo.add_party(transaction_id=txn_id, name="Buyer One", role="buyer")
    buyer2 = repo.add_party(transaction_id=txn_id, name="Buyer Two", role="buyer")
    inspector = repo.add_party(transaction_id=txn_id, name="Inspector", role="inspector_general")

    # Tasks: inspector has one open + one done; an unassigned task exists.
    repo.tasks.extend(
        [
            {"id": "t1", "transaction_id": txn_id, "title": "Schedule inspection",
             "status": "pending", "assigned_party_id": inspector["id"]},
            {"id": "t2", "transaction_id": txn_id, "title": "Upload report",
             "status": "done", "assigned_party_id": inspector["id"]},
            {"id": "t3", "transaction_id": txn_id, "title": "Unassigned chore",
             "status": "pending", "assigned_party_id": None},
        ]
    )

    # Documents: 1 of 2 buyers has confirmed proof_of_funds; disclosure confirmed.
    repo.documents.update(
        {
            "d1": {"id": "d1", "transaction_id": txn_id, "doc_type": "proof_of_funds",
                   "status": "confirmed"},
            "d2": {"id": "d2", "transaction_id": txn_id, "doc_type": "proof_of_funds",
                   "status": "pending"},
            "d3": {"id": "d3", "transaction_id": txn_id, "doc_type": "disclosure",
                   "status": "confirmed"},
        }
    )

    # Messages to the inspector: a sent one, then a later draft — inserted
    # newest-first to prove the dashboard orders by created_at, not insertion.
    repo.messages.update(
        {
            "m2": {"id": "m2", "transaction_id": txn_id, "subject": "s2", "body": "b2",
                   "party_id": inspector["id"], "status": "sent", "sent_at": "2026-07-16",
                   "created_at": "2026-07-15T10:00:00Z"},
            "m1": {"id": "m1", "transaction_id": txn_id, "subject": "s", "body": "b",
                   "party_id": inspector["id"], "status": "draft", "sent_at": None,
                   "created_at": "2026-07-16T10:00:00Z"},
        }
    )

    # Risk flags: a resolved one (dropped) plus warning/critical/info unresolved.
    repo.risk_flags.extend(
        [
            {"id": "r0", "transaction_id": txn_id, "severity": "critical",
             "description": "resolved already", "resolved": True},
            {"id": "r1", "transaction_id": txn_id, "severity": "warning",
             "description": "warn", "resolved": False},
            {"id": "r2", "transaction_id": txn_id, "severity": "critical",
             "description": "crit", "resolved": False},
            {"id": "r3", "transaction_id": txn_id, "severity": "info",
             "description": "fyi", "resolved": False},
        ]
    )
    return repo, txn_id, {"buyer1": buyer1, "buyer2": buyer2, "inspector": inspector}


def test_transaction_id_echoed():
    repo, txn_id, _ = _seed()
    dash = build_dashboard(repo.get_full_state(txn_id))
    assert dash["transaction_id"] == txn_id


def test_party_drilldown_splits_open_and_done():
    repo, txn_id, ids = _seed()
    dash = build_dashboard(repo.get_full_state(txn_id))
    inspector_view = next(
        v for v in dash["parties"] if v["party"]["id"] == ids["inspector"]["id"]
    )
    assert {t["id"] for t in inspector_view["open_tasks"]} == {"t1"}
    assert {t["id"] for t in inspector_view["done_tasks"]} == {"t2"}
    # Latest message by created_at wins — the draft (m1), not the older sent one.
    assert inspector_view["last_message_status"] == "draft"


def test_party_with_no_messages_has_none_status():
    repo, txn_id, ids = _seed()
    dash = build_dashboard(repo.get_full_state(txn_id))
    buyer_view = next(v for v in dash["parties"] if v["party"]["id"] == ids["buyer1"]["id"])
    assert buyer_view["last_message_status"] is None
    assert buyer_view["open_tasks"] == []


def test_role_rollups_count_confirmed_docs():
    repo, txn_id, _ = _seed()
    dash = build_dashboard(repo.get_full_state(txn_id))
    progress = dash["party_progress"]
    assert progress["buyers_total"] == 2
    assert progress["proof_of_funds_confirmed"] == 1  # only the confirmed doc
    assert progress["disclosures_confirmed"] == 1


def test_risk_alerts_drop_resolved_and_sort_by_severity():
    repo, txn_id, _ = _seed()
    dash = build_dashboard(repo.get_full_state(txn_id))
    alerts = dash["risk_alerts"]
    assert [a["id"] for a in alerts] == ["r2", "r1", "r3"]  # critical, warning, info
    assert all(not a["resolved"] for a in alerts)


def test_communication_groups_sent_and_pending():
    repo, txn_id, _ = _seed()
    dash = build_dashboard(repo.get_full_state(txn_id))
    comms = dash["communication"]
    assert {m["id"] for m in comms["sent"]} == {"m2"}
    assert {m["id"] for m in comms["pending"]} == {"m1"}
    assert comms["replies"] == []  # inbound threading is a future feature
