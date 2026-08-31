"""Tests for the cross-surface event catalog (§4) and authority matrix (§5)."""

from __future__ import annotations

from app.master.authority import (
    NEVER_BY_MACHINE,
    can_originate,
    require_originate,
    requires_principal_decision,
)
from app.master.event_catalog import agent_activity, event_type, principal_activity

import pytest

_LOG = [
    {"id": "1", "action": "party.deposit_verified", "created_at": "2026-07-03T10:00:00Z", "details": {"party_id": "b"}},
    {"id": "2", "action": "compliance.run", "created_at": "2026-07-02T10:00:00Z"},
    {"id": "3", "action": "message.drafted", "created_at": "2026-07-01T10:00:00Z"},  # AI op
    {"id": "4", "action": "risk_flag.internal", "created_at": "2026-07-04T10:00:00Z"},  # never surfaces
]


def test_same_event_renders_role_relative_text():
    # the buyer performed the deposit → sees first person; the seller sees third person
    buyer = {e["id"]: e["text"] for e in principal_activity(_LOG, "buyer")}
    seller = {e["id"]: e["text"] for e in principal_activity(_LOG, "seller")}
    assert buyer["1"] == "You confirmed your earnest-money deposit"
    assert seller["1"] == "The buyer confirmed their earnest-money deposit"


def test_principal_feed_hides_ai_ops_and_internal_events():
    ids = {e["id"] for e in principal_activity(_LOG, "buyer")}
    assert "3" not in ids   # message.drafted is an AI op — never shown to principals
    assert "4" not in ids   # unmapped internal event


def test_agent_feed_shows_ai_ops_with_mode():
    events = agent_activity(_LOG + [{"id": "5", "action": "wholly.internal", "created_at": "2026-07-05T10:00:00Z"}], deal_id="d1")
    by_id = {e["id"]: e for e in events}
    assert by_id["3"]["mode"] == "needs_you" and by_id["3"]["actorRole"] == "ai"
    assert by_id["2"]["mode"] == "autonomous"
    assert all(e["dealId"] == "d1" for e in events)
    # risk_flag.* family: escalates in the AGENT feed (needs_you), never principals
    assert by_id["4"]["mode"] == "needs_you" and "risk" in by_id["4"]["text"].lower()
    assert "5" not in by_id  # unmapped internal actions still never surface


def test_event_type_mapping():
    assert event_type("party.deposit_verified") == "emd_received"
    assert event_type("party.disclosure_attested") == "disclosures_delivered"
    assert event_type("risk_flag.internal") is None


def test_authority_matrix_core_rules():
    assert can_originate("contingency.remove", "buyer")
    assert not can_originate("contingency.remove", "seller")
    assert can_originate("disclosure.deliver", "listing_agent")
    assert not can_originate("disclosure.deliver", "buyer_agent")
    assert can_originate("approval.approve_send", "buyer_agent")


def test_never_by_machine_invariant():
    assert {"offer.accept", "repair.resolve"} <= NEVER_BY_MACHINE
    # only the seller may accept an offer / resolve a repair — never ai or system
    assert can_originate("offer.accept", "seller")
    assert not can_originate("offer.accept", "ai")
    assert not can_originate("repair.resolve", "system")
    assert requires_principal_decision("offer.accept")
    assert not requires_principal_decision("task.done")


def test_task_done_is_owner_scoped():
    assert can_originate("task.done", "buyer", owner_role="buyer")
    assert not can_originate("task.done", "buyer", owner_role="seller")
    with pytest.raises(Exception):
        require_originate("task.done", "buyer", owner_role="seller")


def test_deal_state_carries_catalog_digest(client, tc_headers):
    """P8: /transactions/{id} ships a digest rendered from the shared catalog."""
    txn = client.post(
        "/transactions", json={"property_address": "8 Digest Dr"}, headers=tc_headers
    ).json()["id"]
    state = client.get(f"/transactions/{txn}", headers=tc_headers).json()
    assert "digest" in state
    # creating the deal logged catalog-visible events with friendly operator text
    assert all(set(e) >= {"id", "text", "mode", "occurredAt"} for e in state["digest"])


def test_previously_dead_mappings_now_fire():
    """Regression: the catalog listened for party.created / transaction.stage but
    the SOR emits party.added / transaction.staged — joins and stage changes were
    invisible on every surface."""
    log = [
        {"id": "1", "action": "party.added", "created_at": "2026-07-01T10:00:00Z"},
        {"id": "2", "action": "transaction.staged", "created_at": "2026-07-02T10:00:00Z"},
        {"id": "3", "action": "task.status_changed", "created_at": "2026-07-03T10:00:00Z"},
    ]
    texts = [e["text"] for e in principal_activity(log, "buyer")]
    assert "Someone joined your deal team" in texts
    assert "Your deal moved to a new stage" in texts
    assert "A to-do on your deal was updated" in texts
    assert event_type("transaction.staged") == "escrow_opened"
    assert event_type("transaction.canceled") == "deal_cancelled"


def test_party_write_authority_enforced(client, tc_headers):
    """§5 dynamically enforced: a SELLER token cannot verify the buyer's deposit;
    a BUYER token cannot attest a seller disclosure."""
    import time

    import jwt

    from tests.conftest import TEST_JWT_SECRET

    def tok(pid, txn):
        now = int(time.time())
        return jwt.encode(
            {"sub": f"party-{pid}", "role": "authenticated", "aud": "authenticated", "aal": "aal1",
             "iat": now, "exp": now + 3600,
             "app_metadata": {"party_id": pid, "transaction_id": txn, "tier": "collaborator"}},
            TEST_JWT_SECRET, algorithm="HS256",
        )

    txn = client.post("/transactions", json={"property_address": "5 Authority Way"}, headers=tc_headers).json()["id"]
    buyer = client.post(f"/transactions/{txn}/parties", json={"name": "B", "role": "buyer"}, headers=tc_headers).json()["id"]
    seller = client.post(f"/transactions/{txn}/parties", json={"name": "S", "role": "seller"}, headers=tc_headers).json()["id"]

    # wrong roles -> 403
    assert client.post("/party/deposit/verify", headers={"Authorization": f"Bearer {tok(seller, txn)}"}).status_code == 403
    assert client.post("/party/disclosure/attest", json={"kind": "tds"}, headers={"Authorization": f"Bearer {tok(buyer, txn)}"}).status_code == 403
    assert client.post("/party/disbursement/verify", headers={"Authorization": f"Bearer {tok(buyer, txn)}"}).status_code == 403
    # right roles -> 201
    assert client.post("/party/deposit/verify", headers={"Authorization": f"Bearer {tok(buyer, txn)}"}).status_code == 201
    assert client.post("/party/disclosure/attest", json={"kind": "tds"}, headers={"Authorization": f"Bearer {tok(seller, txn)}"}).status_code == 201
    assert client.post("/party/disbursement/verify", headers={"Authorization": f"Bearer {tok(seller, txn)}"}).status_code == 201


def test_decision_draft_guard():
    """§6.3 executable: decision-carrying draft purposes demand a recorded
    authorization id; ordinary purposes don't."""
    from app.master.authority import UnauthorizedWrite, validate_draft_purpose

    validate_draft_purpose("client_update", None)  # fine
    validate_draft_purpose("offer_response", "auth-123")  # fine — decision linked
    with pytest.raises(UnauthorizedWrite):
        validate_draft_purpose("offer_response", None)
