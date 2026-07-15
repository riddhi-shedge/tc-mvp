"""Pure risk-flag detection (part c): the seven §6 cases.

Deterministic given `as_of` (injected, never now()). Every "how soon to warn"
threshold is a PRODUCT DECISION from the RuleSet (research §7: none of these are
RPA rules) — the underlying deadline dates are the only rule-derived inputs.
"""

from __future__ import annotations

from datetime import date

from app.compliance.ca_rules import RuleSet
from app.contracts.compliance import ComputedDeadline, DealState, RiskFlag

_INSPECTOR_ROLES = {
    "inspector_general",
    "inspector_termite",
    "inspector_roof",
    "inspector_sewer",
}


def _deadline(deadlines: list[ComputedDeadline], key: str) -> ComputedDeadline | None:
    return next((d for d in deadlines if d.key == key), None)


def _has_party(state: DealState, roles: set[str]) -> bool:
    return any(p.role in roles for p in state.parties)


def _lead(rules: RuleSet, case: str) -> int:
    return rules.flag_lead_days.get(case, 0)


def detect_risk_flags(
    state: DealState,
    deadlines: list[ComputedDeadline],
    rules: RuleSet,
    *,
    as_of: date,
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []

    # Cases 1 & 2 keep firing past the deadline (an unbooked inspection stays a
    # problem after the window opens); cases 3 & 7 use a 0 <= diff <= lead window
    # so they only warn as the deadline APPROACHES, not indefinitely after.

    # 1. Inspection not scheduled — no inspector party as the deadline nears.
    insp = _deadline(deadlines, "inspection_contingency")
    if insp is not None and not _has_party(state, _INSPECTOR_ROLES):
        if (insp.due_date - as_of).days <= _lead(rules, "inspection_not_scheduled"):
            flags.append(
                RiskFlag(
                    case="inspection_not_scheduled",
                    description="No inspection party is on the deal as the inspection contingency nears.",
                    deadline_key="inspection_contingency",
                )
            )

    # 2. Appraisal not ordered — no appraiser party as the deadline nears.
    appr = _deadline(deadlines, "appraisal_contingency")
    if appr is not None and not _has_party(state, {"appraiser"}):
        if (appr.due_date - as_of).days <= _lead(rules, "appraisal_not_ordered"):
            flags.append(
                RiskFlag(
                    case="appraisal_not_ordered",
                    description="No appraiser is on the deal as the appraisal contingency nears.",
                    deadline_key="appraisal_contingency",
                )
            )

    # 3. Loan contingency approaching.
    loan = _deadline(deadlines, "loan_contingency")
    if loan is not None and 0 <= (loan.due_date - as_of).days <= _lead(
        rules, "loan_contingency_approaching"
    ):
        flags.append(
            RiskFlag(
                case="loan_contingency_approaching",
                description="The loan contingency deadline is approaching.",
                deadline_key="loan_contingency",
            )
        )

    # 4. Earnest money not confirmed — deadline passed, no confirming task done.
    emd = _deadline(deadlines, "emd")
    if emd is not None and emd.due_date <= as_of and not _task_done(state, "earnest"):
        flags.append(
            RiskFlag(
                case="earnest_money_not_confirmed",
                description="The earnest money deposit due date has passed without confirmation.",
                deadline_key="emd",
            )
        )

    # 5. Disclosures unsigned — delivery deadline passed, no disclosure doc confirmed.
    disc = _deadline(deadlines, "disclosure_delivery")
    if disc is not None and disc.due_date <= as_of and not _has_confirmed_doc(state, "disclosure"):
        flags.append(
            RiskFlag(
                case="disclosures_unsigned",
                description="Seller disclosures are not confirmed past their delivery deadline.",
                deadline_key="disclosure_delivery",
            )
        )

    # 6. Missing escrow contact.
    if not _has_party(state, {"escrow"}):
        flags.append(
            RiskFlag(
                case="missing_escrow_contact",
                description="No escrow holder contact is on the deal.",
            )
        )

    # 7. Closing near with open tasks.
    coe = _deadline(deadlines, "coe")
    if coe is not None and 0 <= (coe.due_date - as_of).days <= _lead(
        rules, "closing_near_open_tasks"
    ):
        if any(t.status not in ("done", "complete") for t in state.tasks):
            flags.append(
                RiskFlag(
                    case="closing_near_open_tasks",
                    description="Close of escrow is near while tasks remain open.",
                    deadline_key="coe",
                )
            )

    return flags


def _task_done(state: DealState, keyword: str) -> bool:
    return any(keyword in t.title.lower() and t.status in ("done", "complete") for t in state.tasks)


def _has_confirmed_doc(state: DealState, doc_type: str) -> bool:
    return any(d.doc_type == doc_type and d.status == "confirmed" for d in state.documents)
