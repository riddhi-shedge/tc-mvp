"""The runner: blocks on unverified rules; with a synthetic ruleset injected it
reads (fake master) → computes → writes a ComplianceResult."""

from datetime import date

import pytest

from app.compliance.ca_rules import RulesNotVerified, synthetic_ruleset
from app.compliance.service import compute, run_for_transaction
from app.contracts.compliance import ComplianceResult, DealFieldState, DealState


class FakeComplianceMaster:
    def __init__(self, state: DealState | None) -> None:
        self.state = state
        self.written: list[ComplianceResult] = []

    def read_deal_state(self, transaction_id: str) -> DealState | None:
        return self.state

    def write_compliance_result(self, result: ComplianceResult) -> None:
        self.written.append(result)


def _confirmed_deal() -> DealState:
    return DealState(
        transaction_id="txn-1",
        fields=[
            DealFieldState(
                name="acceptance_date", value="2026-07-10", confirmed=True, deadline_driving=True
            ),
            DealFieldState(
                name="inspection_contingency_days",
                value="17",
                confirmed=True,
                deadline_driving=True,
            ),
        ],
    )


def test_runner_blocks_on_unverified_rules(monkeypatch):
    monkeypatch.delenv("CA_RULES_VERIFIED", raising=False)
    master = FakeComplianceMaster(_confirmed_deal())
    # rules=None -> production loader -> raises.
    with pytest.raises(RulesNotVerified):
        run_for_transaction("txn-1", master, rules=None, as_of=date(2026, 7, 10))
    assert master.written == []


def test_runner_computes_and_writes_with_injected_ruleset():
    master = FakeComplianceMaster(_confirmed_deal())
    result = run_for_transaction(
        "txn-1", master, rules=synthetic_ruleset(), as_of=date(2026, 7, 10)
    )
    assert master.written == [result]
    assert any(d.key == "inspection_contingency" for d in result.deadlines)


def test_runner_raises_on_missing_transaction():
    master = FakeComplianceMaster(None)
    with pytest.raises(ValueError, match="not found"):
        run_for_transaction("txn-x", master, rules=synthetic_ruleset())


def test_state_from_slice_maps_the_boundary():
    from app.compliance.master_client import _state_from_slice

    state = _state_from_slice(
        {
            "transaction_id": "txn-1",
            "fields": [
                {
                    "name": "acceptance_date",
                    "value": "2026-07-10",
                    "confirmed": True,
                    "deadline_driving": True,
                }
            ],
            "parties": [{"role": "escrow", "name": "Syn", "email": None}],
            "documents": [{"doc_type": "disclosure", "status": "confirmed"}],
            "tasks": [{"title": "T", "status": "pending"}],
        }
    )
    assert state.fields[0].deadline_driving is True
    assert state.parties[0].role == "escrow"
    assert state.documents[0].status == "confirmed"
    assert state.tasks[0].title == "T"


def test_compute_is_pure_and_deterministic():
    state = _confirmed_deal()
    a = compute(state, synthetic_ruleset(), as_of=date(2026, 7, 10))
    b = compute(state, synthetic_ruleset(), as_of=date(2026, 7, 10))
    assert a.model_dump() == b.model_dump()
