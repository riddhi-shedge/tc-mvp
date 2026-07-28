"""Follow-up reminders (Feature B): the TC can dismiss a come-due reminder."""

from tests.fake_repo import InMemoryRepo


def test_dismiss_reminder_removes_it_and_audits():
    repo = InMemoryRepo()
    txn = repo.create_transaction(property_address="1 A St", actor="tc")["id"]
    repo.reminders.append(
        {"id": "rem1", "transaction_id": txn, "message_id": None,
         "remind_at": "2026-01-01T00:00:00Z", "note": "No reply yet"}
    )
    assert repo.delete_reminder(transaction_id=txn, reminder_id="rem1", actor="tc") is True
    assert not any(r["id"] == "rem1" for r in repo.reminders)
    assert any(a["action"] == "reminder.dismissed" for a in repo.audit_log)


def test_dismiss_unknown_reminder_is_false():
    repo = InMemoryRepo()
    txn = repo.create_transaction(property_address="1 A St", actor="tc")["id"]
    assert repo.delete_reminder(transaction_id=txn, reminder_id="nope", actor="tc") is False
