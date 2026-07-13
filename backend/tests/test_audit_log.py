"""Audit log behavior at the repo boundary: a row on every state change,
carrying actor + action + entity + timestamp. Append-only enforcement at the
database itself is covered in test_db_integration.py (trigger)."""

from app.contracts.payload import ExtractedField, Payload


def test_every_state_change_writes_one_audit_row(repo):
    created = repo.create_transaction(property_address="9 Synthetic Ct", actor="tc@example.test")
    assert len(repo.audit_log) == 1

    payload = Payload(
        document_id="synthetic-doc-2",
        transaction_id=created["id"],
        extracted_fields=[
            ExtractedField(name="acceptance_date", value="2026-07-01", confidence=0.9)
        ],
    )
    repo.write_payload(transaction_id=created["id"], payload=payload, actor="tc@example.test")
    assert len(repo.audit_log) == 2


def test_audit_rows_carry_who_what_when(repo):
    created = repo.create_transaction(property_address="9 Synthetic Ct", actor="tc@example.test")
    row = repo.audit_log[0]
    assert row["actor"] == "tc@example.test"
    assert row["action"] == "transaction.created"
    assert row["entity_type"] == "transaction"
    assert row["entity_id"] == created["id"]
    assert row["created_at"]


def test_audit_log_returned_in_full_state(repo):
    created = repo.create_transaction(property_address="9 Synthetic Ct", actor="tc@example.test")
    state = repo.get_full_state(created["id"])
    assert len(state["audit_log"]) == 1
    assert state["audit_log"][0]["action"] == "transaction.created"
