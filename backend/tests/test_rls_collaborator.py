"""Collaborator RLS permission test (agents/broker) — synthetic data only.

Proves, against the live dev DB, that a collaborator token (a Supabase session
whose admin-set app_metadata carries tier='collaborator' + transaction_id) gets a
READ-ONLY, transaction-scoped view:

  1. reads the deal's timeline (deadlines), tasks, parties, property, risks, docs;
  2. reads NOTHING internal — messages, extracted_fields, audit_log, payloads;
  3. sees only ITS OWN deal, never a second deal's rows;
  4. cannot WRITE — updating a task it isn't assigned changes nothing.

Skips unless SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY + SUPABASE_ANON_KEY are set.
Everything created (two deals, party, auth user) is torn down.
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
    reason="Supabase env not configured; collaborator RLS test skipped",
)


@pytest.fixture(scope="module")
def db():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@pytest.fixture()
def scenario(db):
    from app.master.repo import SupabaseRepo

    repo = SupabaseRepo()
    deal = repo.create_transaction(property_address="1 Collab Way (synthetic)", actor="pytest")
    other = repo.create_transaction(property_address="2 Other Way (synthetic)", actor="pytest")
    agent = repo.create_party(
        transaction_id=deal["id"], name="Synthetic Agent", role="buyer_agent",
        email=None, permission_tier="collaborator", actor="pytest",
    )
    db.table("deadlines").insert(
        {"transaction_id": deal["id"], "name": "Inspection contingency ends", "due_date": "2026-08-11"}
    ).execute()
    db.table("tasks").insert(
        {"transaction_id": deal["id"], "title": "Schedule inspection (synthetic)", "status": "pending"}
    ).execute()
    db.table("deadlines").insert(
        {"transaction_id": other["id"], "name": "Other deal COE", "due_date": "2026-09-01"}
    ).execute()
    yield {"deal": deal["id"], "other": other["id"], "agent": agent["id"]}
    db.table("transactions").delete().eq("id", deal["id"]).execute()
    db.table("transactions").delete().eq("id", other["id"]).execute()


@pytest.fixture()
def collab_client(scenario, db):
    from supabase import create_client

    from app.master.party_access import SupabasePartyAccessIssuer

    issuer = SupabasePartyAccessIssuer()
    result = issuer.issue(
        party_id=scenario["agent"], transaction_id=scenario["deal"], email=None, tier="collaborator"
    )
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    client.postgrest.auth(result["access_token"])
    yield client
    user = SupabasePartyAccessIssuer._find_by_email(
        db, issuer._auth_email(party_id=scenario["agent"], email=None)
    )
    if user is not None:
        db.auth.admin.delete_user(user.id)


def test_collaborator_reads_the_deal_timeline(collab_client, scenario):
    assert len(collab_client.table("deadlines").select("id").execute().data) == 1
    assert len(collab_client.table("tasks").select("id").execute().data) == 1
    assert len(collab_client.table("parties").select("id").execute().data) == 1
    assert len(collab_client.table("transactions").select("id").execute().data) == 1
    assert len(collab_client.table("properties").select("id").execute().data) == 1


@pytest.mark.parametrize("table", ["messages", "extracted_fields", "audit_log", "payloads", "approvals", "reminders"])
def test_collaborator_reads_no_internal_surface(collab_client, table):
    assert collab_client.table(table).select("*").execute().data == []


def test_collaborator_sees_only_its_own_deal(collab_client, scenario):
    txn_ids = {d["transaction_id"] for d in collab_client.table("deadlines").select("transaction_id").execute().data}
    assert txn_ids == {scenario["deal"]}  # never the second deal


def test_collaborator_cannot_write(collab_client, db, scenario):
    task = db.table("tasks").select("id").eq("transaction_id", scenario["deal"]).execute().data[0]
    collab_client.table("tasks").update({"status": "done"}).eq("id", task["id"]).execute()
    # Not assigned to this collaborator → policy matches no row → unchanged.
    row = db.table("tasks").select("status").eq("id", task["id"]).execute().data[0]
    assert row["status"] == "pending"
