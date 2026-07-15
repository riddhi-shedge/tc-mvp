"""The California rule VALUES — WALLED OFF until human-verified.

*** DO NOT fill these in from memory, blogs, or an AI. ***
Every value here must come from a human reading the literal current C.A.R. RPA
(12/25) and NBP/CR forms and signing off on docs/ca-rules-verification.md
(§11, §18). Wrong date math silently corrupts every downstream task.

Until that sign-off:
  - VERIFIED_RULESET is None (empty),
  - `load_verified_ruleset()` raises RulesNotVerified,
  - the compliance service refuses to run in production.

The date-engine MECHANICS (date_engine.py) and the compute framework
(timeline.py / risk_flags.py / drafts.py) are complete and are tested against
`synthetic_ruleset()` — a clearly fake set of numbers that must NEVER be
mistaken for verified values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from app.compliance.date_engine import DayUnit


class RulesNotVerified(Exception):
    """The CA rules have not been human-verified — the service must not run."""


@dataclass(frozen=True)
class Period:
    """A contingency/action period: N days of a given unit after the trigger."""

    days: int
    unit: DayUnit  # "calendar" or "business" — UNVERIFIED which, per row C1


@dataclass(frozen=True)
class RuleSet:
    """The human-verified CA rule values the compute needs. Field-by-field
    provenance is in docs/ca-rules-verification.md (rows in brackets)."""

    # Default contingency/action periods [verification rows C1–C7]. Keyed by the
    # §5 field name that carries the number when the blank IS filled; these are
    # the FALLBACK defaults for when it isn't.
    default_periods: dict[str, Period]
    # NBP mechanics [rows D2, D3].
    nbp_earliest_days_before: int
    nbp_cure: Period
    # Which dates are non-business days [row A6: CA state vs federal — UNVERIFIED].
    holidays: frozenset[date]
    # §6 risk-flag thresholds — PRODUCT DECISIONS (research §7), you choose them.
    flag_lead_days: dict[str, int]  # case -> "flag this many days before"

    def period_for(self, field_name: str) -> Period | None:
        return self.default_periods.get(field_name)


# Filled ONLY after human verification. Stays None until then.
VERIFIED_RULESET: RuleSet | None = None


def _rules_marked_verified() -> bool:
    return os.environ.get("CA_RULES_VERIFIED", "false").lower() == "true"


def load_verified_ruleset() -> RuleSet:
    """Production entry point. Raises until the rules are human-verified AND the
    values above are actually filled in."""
    if not _rules_marked_verified() or VERIFIED_RULESET is None:
        raise RulesNotVerified(
            "California deadline rules are not verified. Fill VERIFIED_RULESET in "
            "app/compliance/ca_rules.py from docs/ca-rules-verification.md and set "
            "CA_RULES_VERIFIED=true. The compliance service will not compute real "
            "deadlines on unverified rules (§11, §18)."
        )
    return VERIFIED_RULESET


# --- Synthetic ruleset — TESTS/DEMOS ONLY. NOT verified. NOT California. ------
# The numbers below are deliberately ARBITRARY placeholders so the engine can be
# exercised. They must never be copied into VERIFIED_RULESET.

_SYNTHETIC_HOLIDAYS: frozenset[date] = frozenset(
    {date(2026, 7, 3), date(2026, 12, 25)}  # arbitrary test holidays
)


def synthetic_ruleset() -> RuleSet:
    """A clearly-fake ruleset for tests and wiring demos ONLY."""
    return RuleSet(
        default_periods={
            "emd_due_days": Period(3, "business"),
            "inspection_contingency_days": Period(17, "calendar"),
            "loan_contingency_days": Period(21, "calendar"),
            "appraisal_contingency_days": Period(17, "calendar"),
            "insurance_contingency_days": Period(17, "calendar"),
            "disclosure_delivery_days": Period(7, "calendar"),
            "verification_of_funds_days": Period(3, "calendar"),
        },
        nbp_earliest_days_before=2,
        nbp_cure=Period(2, "calendar"),
        holidays=_SYNTHETIC_HOLIDAYS,
        flag_lead_days={
            "loan_contingency_approaching": 5,
            "closing_near_open_tasks": 7,
            "inspection_not_scheduled": 3,
            "appraisal_not_ordered": 3,
        },
    )
