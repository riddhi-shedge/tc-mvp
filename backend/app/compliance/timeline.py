"""Pure timeline computation (part c): (DealState, RuleSet) -> deadlines+tasks.

No I/O, no config values — the RuleSet supplies every number. Only confirmed
fields are read (the master enforces the §11 gate before this ever runs). A
field the deal doesn't have is simply skipped.
"""

from __future__ import annotations

import re
from datetime import date

from app.compliance.ca_rules import RuleSet
from app.compliance.date_engine import days_after, days_before
from app.contracts.compliance import ComputedDeadline, ComputedTask, DealState

# Each deadline-driving contingency field -> (deadline key, human name). The
# period comes from the field's value if numeric, else the RuleSet default.
# Dates (acceptance/COE/possession) are handled separately below. The *task*
# title is generated per-deal from the confirmed facts (names, amounts, address,
# the computed date) so it reads specifically — see _task_title.
_CONTINGENCY_FIELDS: dict[str, tuple[str, str]] = {
    "emd_due_days": ("emd", "Earnest money deposit due"),
    "inspection_contingency_days": ("inspection_contingency", "Inspection contingency ends"),
    "loan_contingency_days": ("loan_contingency", "Loan contingency ends"),
    "appraisal_contingency_days": ("appraisal_contingency", "Appraisal contingency ends"),
    "insurance_contingency_days": ("insurance_contingency", "Insurance contingency ends"),
    "disclosure_delivery_days": ("disclosure_delivery", "Seller disclosure delivery due"),
    "verification_of_funds_days": ("verification_of_funds", "Verification of funds due"),
}

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_date(d: date) -> str:
    """Short, scannable date for a task title, e.g. 'Aug 11'."""
    return f"{_MONTHS[d.month]} {d.day}"


def _short_address(raw: str | None) -> str:
    return raw.split(",")[0].strip() if raw else ""


def _first_names(raw: str | None, max_n: int = 2) -> str:
    """A concise personal label from a names field ('Marcus Chen; Priya Patel'
    -> 'Marcus & Priya'), so titles name the actual people on the deal."""
    if not raw:
        return ""
    parts = re.split(r"[;,&/]| and ", raw)
    firsts = [p.strip().split()[0] for p in parts if p.strip()][:max_n]
    return " & ".join(firsts)


def _task_title(key: str, st: DealState, due: date | None) -> str:
    """A specific, personalized task title built from the deal's confirmed facts."""
    buyer = _first_names(st.confirmed_value("buyer_names")) or "the buyer"
    seller = _first_names(st.confirmed_value("seller_names")) or "the seller"
    addr = _short_address(st.confirmed_value("property_address"))
    ends = f" — ends {_fmt_date(due)}" if due else ""
    duw = f" — due {_fmt_date(due)}" if due else ""

    if key == "emd":
        amt = st.confirmed_value("initial_deposit_amount")
        head = f"Confirm {amt} earnest money" if amt else "Confirm earnest money"
        return f"{head} wired to escrow{duw}"
    if key == "inspection_contingency":
        at = f" at {addr}" if addr else ""
        return f"Complete inspections{at} and release inspection contingency{ends}"
    if key == "loan_contingency":
        amt = st.confirmed_value("loan_amount")
        loan = f" ({amt} loan)" if amt else ""
        return f"Confirm {buyer}'s loan approval{loan} and release loan contingency{ends}"
    if key == "appraisal_contingency":
        price = st.confirmed_value("purchase_price")
        at = f" at {price}" if price else ""
        return f"Confirm appraisal{at} and release appraisal contingency{ends}"
    if key == "insurance_contingency":
        return f"Bind homeowner's insurance and release insurance contingency{ends}"
    if key == "disclosure_delivery":
        return f"Confirm {seller} delivered disclosures to {buyer}{duw}"
    if key == "verification_of_funds":
        return f"Confirm {buyer}'s proof of funds received{duw}"
    return f"Confirm {key}{ends}"


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
        for field_name, (key, name) in _CONTINGENCY_FIELDS.items():
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
            tasks.append(
                ComputedTask(key=f"task_{key}", title=_task_title(key, state, due), deadline_key=key)
            )

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
        _addr = _short_address(state.confirmed_value("property_address"))
        _at = f" for {_addr}" if _addr else ""
        tasks.append(
            ComputedTask(
                key="task_coe",
                title=f"Confirm closing preparations complete{_at} — COE {_fmt_date(coe_date)}",
                deadline_key="coe",
            )
        )

        # Final walk-through ("Verification of Condition") — a fixed number of
        # days BEFORE COE, counted straight (no weekend/holiday roll; row A7).
        walkthrough = days_before(coe_date, rules.final_walkthrough_days_before)
        deadlines.append(
            ComputedDeadline(
                key="final_walkthrough",
                name="Final walk-through (verification of condition)",
                due_date=walkthrough,
                source_field="close_of_escrow",
            )
        )
        _buyer = _first_names(state.confirmed_value("buyer_names")) or "the buyer"
        tasks.append(
            ComputedTask(
                key="task_final_walkthrough",
                title=f"Final walk-through with {_buyer} — {_fmt_date(walkthrough)}",
                deadline_key="final_walkthrough",
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
            _pbuyer = _first_names(state.confirmed_value("buyer_names")) or "the buyer"
            tasks.append(
                ComputedTask(
                    key="task_possession",
                    title=f"Coordinate key handover to {_pbuyer} — {_fmt_date(possession_date)}",
                    deadline_key="possession",
                )
            )

    return deadlines, tasks


def _references_coe(value: str) -> bool:
    v = value.lower()
    return "close of escrow" in v or "coe" in v or "at close" in v
