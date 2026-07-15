"""The compliance/timeline runner (part c) — thin wiring around the pure compute.

Interval-run (scheduler calls `run_for_transaction` per open deal). It reaches
the master ONLY through the master API (a client protocol, like ingestion's) —
never the master's tables. It refuses to run until the CA rules are
human-verified (load_verified_ruleset raises RulesNotVerified).

`compute` is the pure heart and is what the "done when" tests exercise against
synthetic state + a synthetic ruleset; `run_for_transaction` is the I/O shell.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.compliance.ca_rules import RuleSet, load_verified_ruleset
from app.compliance.drafts import draft_reminders
from app.compliance.risk_flags import detect_risk_flags
from app.compliance.timeline import compute_timeline
from app.contracts.compliance import ComplianceResult, DealState


def compute(state: DealState, rules: RuleSet, *, as_of: date) -> ComplianceResult:
    """Pure: DealState + RuleSet -> ComplianceResult. No I/O."""
    deadlines, tasks = compute_timeline(state, rules)
    flags = detect_risk_flags(state, deadlines, rules, as_of=as_of)
    drafts = draft_reminders(flags)
    return ComplianceResult(
        transaction_id=state.transaction_id,
        deadlines=deadlines,
        tasks=tasks,
        risk_flags=flags,
        draft_reminders=drafts,
    )


class ComplianceMasterClient(Protocol):
    """Part (c)'s window onto the master — read confirmed state, write results.
    Implemented over HTTP in prod (service-token auth); faked in tests."""

    def read_deal_state(self, transaction_id: str) -> DealState | None: ...

    def write_compliance_result(self, result: ComplianceResult) -> None: ...


def run_for_transaction(
    transaction_id: str,
    master: ComplianceMasterClient,
    *,
    as_of: date | None = None,
    rules: RuleSet | None = None,
) -> ComplianceResult:
    """Run the service for one deal. `rules` is injected only in tests/demos;
    production passes None and the verified loader is used (raises if unverified)."""
    ruleset = rules if rules is not None else load_verified_ruleset()
    state = master.read_deal_state(transaction_id)
    if state is None:
        raise ValueError(f"transaction {transaction_id} not found")
    result = compute(state, ruleset, as_of=as_of or date.today())
    master.write_compliance_result(result)
    return result
