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
    events = agent_activity(_LOG, deal_id="d1")
    by_id = {e["id"]: e for e in events}
    assert by_id["3"]["mode"] == "needs_you" and by_id["3"]["actorRole"] == "ai"
    assert by_id["2"]["mode"] == "autonomous"
    assert all(e["dealId"] == "d1" for e in events)
    assert "4" not in by_id  # internal still filtered


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
