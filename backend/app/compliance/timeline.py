"""Pure timeline computation (part c): (DealState, RuleSet) -> deadlines+tasks.

No I/O, no config values — the RuleSet supplies every number. Only confirmed
fields are read (the master enforces the §11 gate before this ever runs). A
field the deal doesn't have is simply skipped.
"""

from __future__ import annotations

from datetime import date

from app.compliance.ca_rules import RuleSet
from app.compliance.date_engine import days_after
from app.contracts.compliance import ComputedDeadline, ComputedTask, DealState

# Each deadline-driving contingency field -> (deadline key, human name, task
# title). The period comes from the field's value if numeric, else the RuleSet
# default. Dates (acceptance/COE/possession) are handled separately below.
_CONTINGENCY_FIELDS: dict[str, tuple[str, str, str]] = {
    "emd_due_days": ("emd", "Earnest money deposit due", "Confirm earnest money deposited"),
    "inspection_contingency_days": (
        "inspection_contingency",
        "Inspection contingency ends",
        "Complete inspections and decide on inspection contingency",
    ),
    "loan_contingency_days": (
        "loan_contingency",
        "Loan contingency ends",
        "Confirm loan approval and decide on loan contingency",
    ),
    "appraisal_contingency_days": (
        "appraisal_contingency",
        "Appraisal contingency ends",
        "Confirm appraisal and decide on appraisal contingency",
    ),
    "insurance_contingency_days": (
        "insurance_contingency",
        "Insurance contingency ends",
        "Confirm insurability and decide on insurance contingency",
    ),
    "disclosure_delivery_days": (
        "disclosure_delivery",
        "Seller disclosure delivery due",
        "Confirm seller disclosures delivered",
    ),
    "verification_of_funds_days": (
        "verification_of_funds",
        "Verification of funds due",
        "Confirm buyer's verification of funds",
    ),
}


# Values that mean "this contingency does not apply" — no deadline is created.
_WAIVED = {"waived", "n/a", "na", "none", "waive"}


def _is_waived(value: str) -> bool:
    return value.strip().lower() in _WAIVED


def _parse_days(value: str) -> int | None:
    """Extract a leading integer day-count from a field value like '17 days'."""
    token = value.strip().split()[0] if value.strip() else ""
    try:
        return int(token)
    except ValueError:
        return None


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def compute_timeline(
    state: DealState, rules: RuleSet
) -> tuple[list[ComputedDeadline], list[ComputedTask]]:
    acceptance = state.confirmed_value("acceptance_date")
    acceptance_date = _parse_iso_date(acceptance) if acceptance else None

    deadlines: list[ComputedDeadline] = []
    tasks: list[ComputedTask] = []

    # Contingency/action periods (need an acceptance date to anchor to).
    if acceptance_date is not None:
        for field_name, (key, name, task_title) in _CONTINGENCY_FIELDS.items():
            raw = state.confirmed_value(field_name)
            if raw is None or _is_waived(raw):
                continue  # absent or waived -> no deadline
            default = rules.period_for(field_name)
            n = _parse_days(raw)
            if n is None:
                if default is None:
                    continue  # no value and no rule default -> can't compute
                n, period_unit = default.days, default.unit
            else:
                period_unit = default.unit if default else "calendar"
            due = days_after(acceptance_date, n, unit=period_unit, holidays=rules.holidays)
            deadlines.append(
                ComputedDeadline(key=key, name=name, due_date=due, source_field=field_name)
            )
            tasks.append(ComputedTask(key=f"task_{key}", title=task_title, deadline_key=key))

    # Close of escrow: either a specific date, or "N days after acceptance".
    coe_raw = state.confirmed_value("close_of_escrow")
    coe_date: date | None = None
    if coe_raw is not None:
        coe_date = _parse_iso_date(coe_raw)
        if coe_date is None and acceptance_date is not None:
            n = _parse_days(coe_raw)
            if n is not None:
                coe_date = days_after(acceptance_date, n, unit="calendar", holidays=rules.holidays)
    if coe_date is not None:
        deadlines.append(
            ComputedDeadline(
                key="coe",
                name="Close of escrow",
                due_date=coe_date,
                source_field="close_of_escrow",
            )
        )
        tasks.append(
            ComputedTask(
                key="task_coe",
                title="Confirm closing preparations complete",
                deadline_key="coe",
            )
        )

    # Possession (a deadline-driving field, so it's confirmed by the time we run):
    # an explicit date, or "at close of escrow" -> the COE date.
    possession_raw = state.confirmed_value("possession_date")
    if possession_raw is not None and not _is_waived(possession_raw):
        possession_date = _parse_iso_date(possession_raw)
        if possession_date is None and _references_coe(possession_raw) and coe_date is not None:
            possession_date = coe_date
        if possession_date is not None:
            deadlines.append(
                ComputedDeadline(
                    key="possession",
                    name="Possession delivered",
                    due_date=possession_date,
                    source_field="possession_date",
                )
            )
            tasks.append(
                ComputedTask(
                    key="task_possession",
                    title="Coordinate possession / key handover",
                    deadline_key="possession",
                )
            )

    return deadlines, tasks


def _references_coe(value: str) -> bool:
    v = value.lower()
    return "close of escrow" in v or "coe" in v or "at close" in v
