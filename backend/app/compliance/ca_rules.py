"""The California rule VALUES.

*** These came ONLY from a human reading the literal current C.A.R. RPA. ***
VERIFIED_RULESET below was filled from docs/ca-rules-verification.md, which was
verified and signed against the literal C.A.R. RPA revision 6/26 (and cross-
checked against the PDF) by a human on 2026-07-18 (§11, §18). Nothing here was
sourced from memory, blogs, or an AI. Wrong date math silently corrupts every
downstream task, so any future edit must go back through that sheet.

Runtime gate (unchanged discipline): `load_verified_ruleset()` still refuses to
serve the values unless CA_RULES_VERIFIED=true is set in the environment — an
explicit production opt-in acknowledging the rules are current.

The date-engine MECHANICS (date_engine.py, ca_holidays.py) and the compute
framework (timeline.py / risk_flags.py / drafts.py) are also tested against
`synthetic_ruleset()` — a clearly fake set of numbers that must NEVER be
mistaken for the verified values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from app.compliance.ca_holidays import ca_legal_holidays
from app.compliance.date_engine import DayUnit


class RulesNotVerified(Exception):
    """The CA rules have not been human-verified — the service must not run."""


@dataclass(frozen=True)
class Period:
    """A contingency/action period: N days of a given unit after the trigger."""

    days: int
    unit: DayUnit  # "calendar" or "business" (deposit is business days — row C1)


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
    # Legal holidays for the final-day roll [row A6: RPA 6/26 = Civ. §§7/7.1 +
    # Gov. §6700; see ca_holidays.py]. A wide precomputed set for real deals.
    holidays: frozenset[date]
    # §6 risk-flag thresholds — PRODUCT DECISIONS (research §7), you choose them.
    flag_lead_days: dict[str, int]  # case -> "flag this many days before"

    # Backward-from-COE windows — plain calendar subtraction, NO roll [row A7 +
    # the final walk-through]. The form counts these "whether or not" the day is
    # a weekend/holiday (¶14E/¶14G).
    dce_earliest_days_before: int = 3
    dce_min_days_to_close: int = 3
    final_walkthrough_days_before: int = 5
    # Statutory rescission clocks — primary law, separate from the RPA [rows F1,
    # F3]: buyer may terminate within N days of disclosure delivery.
    rescission_personal_days: int = 3
    rescission_mail_or_electronic_days: int = 5
    # 6/26 mechanic [form ¶8A]: a failure to obtain insurance may justify
    # cancellation under the INSURANCE contingency but not the loan contingency.
    loan_cancellation_requires_non_insurance_reason: bool = True

    def period_for(self, field_name: str) -> Period | None:
        return self.default_periods.get(field_name)


# --- The human-verified California ruleset (RPA 6/26) ------------------------
# VERIFIED & signed against the literal C.A.R. RPA revision 6/26 by Riddhi Shedge
# on 2026-07-18 (docs/ca-rules-verification.md — canonical ruleset + sign-off).
# Provenance for each value is the bracketed row id in that sheet.
#
# Years covered by the precomputed holiday set. PRE-GO-LIVE: extend this before
# the upper bound — a deal dated outside the range silently treats those years as
# holiday-free (no runtime bound check exists yet).
_VERIFIED_HOLIDAY_YEARS = range(2024, 2046)
# Non-computable legal holidays (Lunar New Year, Diwali, Governor/President-
# proclaimed days) — add explicit dates here to honor the full §6700 definition
# the human chose. PRE-GO-LIVE / KNOWN GAP: this is empty, so a deadline whose
# final day lands on one of those dates will NOT roll (computed one day early).
# Populate (human-verified dates) before processing real deals. Tracked in
# docs/ca-rules-verification.md.
_OVERRIDE_HOLIDAYS: frozenset[date] = frozenset()

VERIFIED_RULESET: RuleSet | None = RuleSet(
    default_periods={
        # [rows C1–C7] All "N (or __) Days after Acceptance" pre-printed defaults.
        "emd_due_days": Period(3, "business"),  # C1 — deposit is business days
        "inspection_contingency_days": Period(17, "calendar"),  # C2
        "loan_contingency_days": Period(17, "calendar"),  # C3 — 6/26 aligns at 17
        "appraisal_contingency_days": Period(17, "calendar"),  # C4
        "insurance_contingency_days": Period(17, "calendar"),  # C5
        "disclosure_delivery_days": Period(7, "calendar"),  # C6 (rolls — row A5)
        "verification_of_funds_days": Period(3, "calendar"),  # C7
    },
    nbp_earliest_days_before=2,  # D2
    nbp_cure=Period(2, "calendar"),  # D3
    holidays=ca_legal_holidays(_VERIFIED_HOLIDAY_YEARS, extra=_OVERRIDE_HOLIDAYS),
    flag_lead_days={  # §6 product decisions (chosen 2026-07-18)
        "loan_contingency_approaching": 3,
        "closing_near_open_tasks": 5,
        "inspection_not_scheduled": 3,
        "appraisal_not_ordered": 3,
    },
    # Backward windows + statutory clocks + loan/insurance mechanic take their
    # verified defaults (A7: DCE 3/3; walk-through 5; F1/F3: 3 personal / 5 mail).
)


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
