"""Phase 5 done-when: the HUMAN-VERIFIED CA ruleset (RPA 6/26) produces correct
real deadlines — including the 6/26 corrections (loan = 17, not 21) and a roll
off a real California legal holiday.

Uses load_verified_ruleset() with the production opt-in flag, so this exercises
the actual VERIFIED_RULESET, not the synthetic one.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.compliance.ca_rules import load_verified_ruleset
from app.compliance.date_engine import days_before
from app.compliance.timeline import compute_timeline
from app.contracts.compliance import DealFieldState, DealState


@pytest.fixture()
def verified_rules(monkeypatch):
    monkeypatch.setenv("CA_RULES_VERIFIED", "true")
    return load_verified_ruleset()


def _field(name, value):
    return DealFieldState(name=name, value=value, confirmed=True, deadline_driving=True)


def test_verified_6_26_deadlines(verified_rules):
    # Acceptance 2026-08-03 (Mon); the +17 window lands on a holiday-free weekday.
    state = DealState(
        transaction_id="txn-verified",
        fields=[
            _field("acceptance_date", "2026-08-03"),
            _field("inspection_contingency_days", "per contract"),  # -> default 17
            _field("loan_contingency_days", "per contract"),        # -> default 17
            _field("emd_due_days", "per contract"),                 # -> default 3 business
            _field("disclosure_delivery_days", "per contract"),     # -> default 7
            _field("verification_of_funds_days", "per contract"),   # -> default 3
            _field("close_of_escrow", "2026-09-15"),
        ],
    )
    by_key = {d.key: d for d in compute_timeline(state, verified_rules)[0]}

    # The 6/26 correction: loan is 17 Days (== inspection), NOT the old 21.
    assert by_key["loan_contingency"].due_date == date(2026, 8, 20)
    assert by_key["inspection_contingency"].due_date == date(2026, 8, 20)
    assert by_key["loan_contingency"].due_date == by_key["inspection_contingency"].due_date
    # Deposit is counted in BUSINESS days (row C1): 3 business days after Mon 8/3.
    assert by_key["emd"].due_date == date(2026, 8, 6)
    assert by_key["disclosure_delivery"].due_date == date(2026, 8, 10)  # +7 calendar
    assert by_key["verification_of_funds"].due_date == date(2026, 8, 6)  # +3 calendar
    # Final walk-through: 5 days BEFORE COE, straight subtraction (no roll).
    assert by_key["final_walkthrough"].due_date == date(2026, 9, 10)


def test_deadline_rolls_off_a_real_ca_holiday(verified_rules):
    # Acceptance 2026-12-08 → inspection (+17) = Fri 2026-12-25 (Christmas) →
    # rolls past the holiday and the weekend to Mon 2026-12-28.
    state = DealState(
        transaction_id="txn-holiday",
        fields=[
            _field("acceptance_date", "2026-12-08"),
            _field("inspection_contingency_days", "per contract"),
        ],
    )
    by_key = {d.key: d for d in compute_timeline(state, verified_rules)[0]}
    assert date(2026, 12, 25) in verified_rules.holidays  # Christmas is a holiday
    assert by_key["inspection_contingency"].due_date == date(2026, 12, 28)


def test_backward_window_does_not_roll(verified_rules):
    # A backward COE window is a plain calendar subtraction even onto a weekend.
    coe = date(2026, 9, 15)
    assert days_before(coe, verified_rules.final_walkthrough_days_before) == date(2026, 9, 10)
    # DCE earliest-delivery day = 3 days before COE, unrolled.
    assert days_before(coe, verified_rules.dce_earliest_days_before) == date(2026, 9, 12)


def test_override_lunar_holidays_are_live(verified_rules):
    # Non-computable §6700 holidays supplied via the override list.
    assert date(2026, 2, 17) in verified_rules.holidays   # Lunar New Year 2026
    assert date(2027, 10, 29) in verified_rules.holidays  # Diwali 2027
    assert date(2030, 2, 3) in verified_rules.holidays     # Lunar New Year 2030


def test_deadline_rolls_off_diwali(verified_rules):
    from app.compliance.date_engine import days_after

    # Oct 17 2028 is Diwali (Tue). A deadline landing there rolls to Wed 10/18.
    assert days_after(
        date(2028, 10, 16), 1, unit="calendar", holidays=verified_rules.holidays
    ) == date(2028, 10, 18)


def test_statutory_rescission_and_mechanic_present(verified_rules):
    assert verified_rules.rescission_personal_days == 3
    assert verified_rules.rescission_mail_or_electronic_days == 5
    assert verified_rules.loan_cancellation_requires_non_insurance_reason is True
