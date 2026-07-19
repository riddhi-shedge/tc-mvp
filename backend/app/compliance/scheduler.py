"""The compliance scheduler (part c) — sweep every open deal on an interval.

A daily cron/Modal job invokes `python -m app.compliance.scheduler`. For each
open deal it runs the compliance service with `as_of = today`, so approaching-
deadline risk flags fire and reminder drafts appear as time passes (nothing here
sends — drafts still need a human approval, Rule 3).

Decoupling holds: the scheduler talks to the master ONLY through the compliance-
scoped endpoints (service-token auth), never its DB. The verified ruleset is
loaded ONCE up front, so a closed CA_RULES_VERIFIED gate stops the whole sweep
before any deal is touched. `apply_compliance_result` is idempotent per deal, so
re-running daily is safe.

Wiring (infra, outside this code): run once a day, e.g. a cron entry
    0 7 * * *  cd /app/backend && python -m app.compliance.scheduler
or a Modal scheduled function — with COMPLIANCE_SERVICE_TOKEN, MASTER_API_BASE,
and CA_RULES_VERIFIED=true set in that job's environment. Exit code is non-zero
if any deal (or setup) failed, so the scheduler surfaces problems to the cron log.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any, Protocol

from app.compliance.ca_rules import RuleSet, load_verified_ruleset
from app.compliance.service import ComplianceMasterClient, run_for_transaction


class SchedulerMaster(ComplianceMasterClient, Protocol):
    """A compliance client that can also enumerate the open deals to sweep."""

    def list_active_transactions(self) -> list[str]: ...


def run_all(
    master: SchedulerMaster,
    *,
    as_of: date | None = None,
    rules: RuleSet | None = None,
) -> list[dict[str, Any]]:
    """Run compliance for every open deal. Loads the verified ruleset once (raises
    if the gate is closed). One deal failing is isolated and reported, never
    aborts the sweep. Returns a per-deal summary."""
    ruleset = rules if rules is not None else load_verified_ruleset()
    when = as_of or date.today()

    summary: list[dict[str, Any]] = []
    for txn_id in master.list_active_transactions():
        try:
            result = run_for_transaction(txn_id, master, as_of=when, rules=ruleset)
            summary.append(
                {
                    "transaction_id": txn_id,
                    "status": "ok",
                    "deadlines": len(result.deadlines),
                    "risk_flags": len(result.risk_flags),
                }
            )
        except Exception as exc:  # isolate: a bad deal must not stop the others
            # Generic label only — no deal content in logs (Rule 5).
            summary.append(
                {"transaction_id": txn_id, "status": "error", "error": type(exc).__name__}
            )
    return summary


def main(argv: list[str] | None = None) -> int:
    from app.compliance.master_client import HttpComplianceMasterClient

    try:
        summary = run_all(HttpComplianceMasterClient())
    except Exception as exc:
        # Setup-level failure (rules gate closed, master unreachable, list failed).
        # Print only the error TYPE — never a traceback that could carry a URL/id
        # (Rule 5). Non-zero exit so the cron job surfaces it.
        print(f"compliance scheduler: could not run ({type(exc).__name__})")
        return 1

    ok = sum(1 for r in summary if r["status"] == "ok")
    print(f"compliance scheduler: {ok}/{len(summary)} open deals ran OK")
    for r in summary:
        if r["status"] != "ok":
            print(f"  ERROR {r['transaction_id']}: {r['error']}")
    return 0 if ok == len(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
