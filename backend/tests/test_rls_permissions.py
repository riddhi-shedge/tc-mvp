"""Receiving-end RLS permission test (Prompt 7 done-when) — synthetic data only.

The load-bearing Phase 7 requirement: the §8 tiers are enforced by Postgres
row-level security, NOT the UI. A receiving-end party presents a scoped access
token (a genuine Supabase-issued session whose admin-set app_metadata.party_id
RLS keys off) directly to Supabase; RLS decides what it may touch. This proves,
against the live dev DB, that such a token can:

  1. SELECT only its own assigned task (and no other task);
  2. UPDATE that task's status to 'done' — allowed;
  3. NOT update a task assigned to someone else (0 rows / denied);
  4. NOT change a column other than status (column grant) — denied;
  5. read nothing else (transactions, messages, other parties) — [].

Skips unless SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY + SUPABASE_ANON_KEY are
all set. Everything created (deal, parties, tasks, auth user) is torn down.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("SUPABASE_URL")
        and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        and os.environ.get("SUPABASE_ANON_KEY")
    ),
    reason="Supabase env (URL + service role + anon key) not configured; RLS test skipped",
)


@pytest.fixture(scope="module")
def db():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@pytest.fixture()
def scenario(db):
    """Service-role setup: a deal, an inspector (receiving-end), an assigned task
    and a second task assigned to a different party."""
    from app.master.repo import SupabaseRepo

    repo = SupabaseRepo()
    txn = repo.create_transaction(
        property_address="1 RLS Test Way (synthetic)", actor="pytest-synthetic"
    )
    txn_id = txn["id"]
    inspector = repo.create_party(
        transaction_id=txn_id,
        name="Synthetic Inspector",
        role="inspector_general",
        email=None,
        permission_tier="receiving_end",
        actor="pytest-synthetic",
    )
    other = repo.create_party(
        transaction_id=txn_id,
        name="Synthetic Appraiser",
        role="appraiser",
        email=None,
        permission_tier="receiving_end",
        actor="pytest-synthetic",
    )
    mine = (
        db.table("tasks")
        .insert(
            {
                "transaction_id": txn_id,
                "title": "My inspection task (synthetic)",
                "status": "pending",
                "assigned_party_id": inspector["id"],
            }
        )
        .execute()
        .data[0]
    )
    theirs = (
        db.table("tasks")
        .insert(
            {
                "transaction_id": txn_id,
                "title": "Their appraisal task (synthetic)",
                "status": "pending",
                "assigned_party_id": other["id"],
            }
        )
        .execute()
        .data[0]
    )
    yield {"txn_id": txn_id, "inspector": inspector, "mine": mine, "theirs": theirs}
    db.table("transactions").delete().eq("id", txn_id).execute()


@pytest.fixture()
def party_client(scenario, db):
    """An anon Supabase client authed as the receiving-end party — a real
    Supabase-issued session (app_metadata.party_id), via the production issuer.
    Tears down the auth user it provisions."""
    from supabase import create_client

    from app.master.party_access import SupabasePartyAccessIssuer

    issuer = SupabasePartyAccessIssuer()
    result = issuer.issue(
        party_id=scenario["inspector"]["id"],
        transaction_id=scenario["txn_id"],
        email=None,
    )
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    client.postgrest.auth(result["access_token"])
    yield client
    # Remove the provisioned auth user (keyed on the synthetic party address).
    user = SupabasePartyAccessIssuer._find_by_email(
        db, issuer._auth_email(party_id=scenario["inspector"]["id"], email=None)
    )
    if user is not None:
        db.auth.admin.delete_user(user.id)


def test_receiving_end_sees_only_its_own_task(party_client, scenario):
    rows = party_client.table("tasks").select("id").execute().data
    assert [r["id"] for r in rows] == [scenario["mine"]["id"]]


def test_receiving_end_can_mark_its_task_done(party_client, db, scenario):
    party_client.table("tasks").update({"status": "done"}).eq(
        "id", scenario["mine"]["id"]
    ).execute()
    # Confirm with the service role (RLS-bypassing) that it actually changed.
    row = (
        db.table("tasks").select("status").eq("id", scenario["mine"]["id"]).execute().data[0]
    )
    assert row["status"] == "done"


def test_receiving_end_cannot_touch_another_partys_task(party_client, db, scenario):
    party_client.table("tasks").update({"status": "done"}).eq(
        "id", scenario["theirs"]["id"]
    ).execute()  # matches no visible row → affects nothing
    row = (
        db.table("tasks").select("status").eq("id", scenario["theirs"]["id"]).execute().data[0]
    )
    assert row["status"] == "pending"  # unchanged


def test_receiving_end_cannot_change_non_status_column(party_client, db, scenario):
    from postgrest.exceptions import APIError

    with pytest.raises(APIError):  # column grant covers status only
        party_client.table("tasks").update({"title": "hijacked"}).eq(
            "id", scenario["mine"]["id"]
        ).execute()
    row = db.table("tasks").select("title").eq("id", scenario["mine"]["id"]).execute().data[0]
    assert row["title"] == "My inspection task (synthetic)"


@pytest.mark.parametrize(
    "table",
    [
        "transactions",
        "properties",
        "parties",
        "documents",
        "payloads",
        "extracted_fields",
        "deadlines",
        "messages",
        "reminders",
        "risk_flags",
        "approvals",
        "audit_log",
    ],
)
def test_receiving_end_reads_nothing_else(party_client, table):
    """Every SOR table except `tasks` is deny-by-default for a receiving-end token."""
    assert party_client.table(table).select("*").limit(5).execute().data == []


def test_token_without_party_id_sees_no_tasks(db, scenario):
    """A Supabase-authenticated token that carries no app_metadata.party_id
    (the NULL::uuid case) matches no task row — the policy can't be satisfied by
    simply being logged in."""
    import uuid

    from supabase import create_client

    url, anon = os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"]
    email = f"noparty-{uuid.uuid4()}@example.test"
    password = f"Synthetic-NoParty-{uuid.uuid4()}"
    user = db.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )  # no app_metadata → no party_id claim
    try:
        cli = create_client(url, anon)
        session = cli.auth.sign_in_with_password({"email": email, "password": password})
        cli.postgrest.auth(session.session.access_token)
        assert cli.table("tasks").select("id").execute().data == []
    finally:
        db.auth.admin.delete_user(user.user.id)
