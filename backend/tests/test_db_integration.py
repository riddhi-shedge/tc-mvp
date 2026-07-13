"""DB-integration tests against the dev Supabase project — synthetic data only.

Skipped automatically unless SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are set
(e.g. `set -a; source ../.env; set +a; pytest tests/test_db_integration.py`).

Covers what the fake cannot: the §10 schema exists, the audit_log is
append-only at the database (trigger), and the real write path round-trips.
Audit rows are intentionally left behind — the audit log outlives its entities.
"""

from __future__ import annotations

import os

import pytest

from app.contracts.payload import ExtractedField, Payload

pytestmark = pytest.mark.skipif(
    not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
    reason="Supabase env not configured; DB-integration tests skipped",
)

TABLES = [
    "transactions",
    "properties",
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
]


@pytest.fixture(scope="module")
def db():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@pytest.fixture(scope="module")
def live_repo():
    from app.master.repo import SupabaseRepo

    return SupabaseRepo()


@pytest.fixture()
def txn(db, live_repo):
    created = live_repo.create_transaction(
        property_address="1 Integration Test Way (synthetic)", actor="pytest-synthetic"
    )
    yield created
    db.table("transactions").delete().eq("id", created["id"]).execute()


@pytest.mark.parametrize("table", TABLES)
def test_schema_table_exists(db, table):
    db.table(table).select("*").limit(0).execute()  # raises if the table is missing


def test_audit_log_is_append_only_update_blocked(db, txn):
    from postgrest.exceptions import APIError

    rows = db.table("audit_log").select("id").eq("transaction_id", txn["id"]).execute().data
    assert rows, "creating a transaction must write an audit row"
    with pytest.raises(APIError, match="append-only"):
        db.table("audit_log").update({"action": "tampered"}).eq("id", rows[0]["id"]).execute()


def test_audit_log_is_append_only_delete_blocked(db, txn):
    from postgrest.exceptions import APIError

    rows = db.table("audit_log").select("id").eq("transaction_id", txn["id"]).execute().data
    with pytest.raises(APIError, match="append-only"):
        db.table("audit_log").delete().eq("id", rows[0]["id"]).execute()


def test_real_write_path_round_trips(live_repo, txn):
    payload = Payload(
        document_id="integration-synthetic-doc",
        transaction_id=txn["id"],
        extracted_fields=[
            ExtractedField(name="close_of_escrow", value="2026-09-01", confidence=0.9)
        ],
    )
    live_repo.write_payload(transaction_id=txn["id"], payload=payload, actor="pytest-synthetic")

    state = live_repo.get_full_state(txn["id"])
    assert state["transaction"]["id"] == txn["id"]
    assert state["property"]["address"] == "1 Integration Test Way (synthetic)"
    assert len(state["payloads"]) == 1
    assert state["documents"][0]["external_ref"] == "integration-synthetic-doc"
    assert state["extracted_fields"][0]["name"] == "close_of_escrow"
    actions = [a["action"] for a in state["audit_log"]]
    assert "transaction.created" in actions and "payload.written" in actions


def test_messages_sent_requires_sent_at_and_vice_versa(db, txn):
    """Schema guard behind Rule 3's audit trail: sent_at iff status='sent'."""
    from postgrest.exceptions import APIError

    with pytest.raises(APIError, match="messages_sent_at_check"):
        db.table("messages").insert(
            {"transaction_id": txn["id"], "subject": "synthetic", "status": "sent"}
        ).execute()
    with pytest.raises(APIError, match="messages_sent_at_check"):
        db.table("messages").insert(
            {
                "transaction_id": txn["id"],
                "subject": "synthetic",
                "status": "draft",
                "sent_at": "2026-07-12T00:00:00Z",
            }
        ).execute()


def test_properties_state_must_be_ca(db, txn):
    """Rule 4 enforced by the schema, not just the API surface."""
    from postgrest.exceptions import APIError

    with pytest.raises(APIError, match="properties_state_ca_check"):
        db.table("properties").update({"state": "NV"}).eq("transaction_id", txn["id"]).execute()


def test_anon_key_reads_nothing(txn):
    """RLS deny-by-default: the anon key must not see SOR rows (frontend safety)."""
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not anon_key:
        pytest.skip("SUPABASE_ANON_KEY not set")
    from supabase import create_client

    anon = create_client(os.environ["SUPABASE_URL"], anon_key)
    assert anon.table("transactions").select("*").eq("id", txn["id"]).execute().data == []
