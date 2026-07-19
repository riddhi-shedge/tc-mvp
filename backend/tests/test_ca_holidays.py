"""CA legal-holiday calendar (Phase 5) — the deterministic §7/§7.1/§6700 set."""

from __future__ import annotations

from datetime import date

from app.compliance.ca_holidays import ca_legal_holidays, ca_legal_holidays_for_year


def test_fixed_and_weekday_holidays_2027():
    h = ca_legal_holidays_for_year(2027)
    assert date(2027, 1, 1) in h       # New Year's
    assert date(2027, 3, 31) in h      # Cesar Chavez Day (CA-specific)
    assert date(2027, 6, 19) in h      # Juneteenth
    assert date(2027, 7, 4) in h       # Independence Day
    assert date(2027, 12, 25) in h     # Christmas
    assert date(2027, 1, 18) in h      # MLK: 3rd Mon Jan 2027
    assert date(2027, 5, 31) in h      # Memorial: last Mon May 2027
    assert date(2027, 9, 6) in h       # Labor: 1st Mon Sep 2027
    assert date(2027, 10, 11) in h     # Columbus: 2nd Mon Oct 2027 (optional bank)
    assert date(2027, 11, 25) in h     # Thanksgiving: 4th Thu Nov 2027
    assert date(2027, 11, 26) in h     # Day after Thanksgiving


def test_weekend_observation():
    # 2027-12-25 is a Saturday → observed Friday 12-24.
    h = ca_legal_holidays_for_year(2027)
    assert date(2027, 12, 25).weekday() == 5
    assert date(2027, 12, 24) in h
    # 2028-12-25 is a Monday (no shift); 2022-12-25 was a Sunday → observed Mon 26.
    assert date(2022, 12, 26) in ca_legal_holidays_for_year(2022)


def test_good_friday_and_lunar_excluded():
    # Good Friday 2027 is Mar 26 — must NOT be present (partial holiday).
    assert date(2027, 3, 26) not in ca_legal_holidays_for_year(2027)


def test_extra_override_dates_are_unioned():
    diwali = date(2027, 10, 29)  # supplied via override, not computed
    h = ca_legal_holidays([2027], extra=[diwali])
    assert diwali in h
    assert date(2027, 7, 4) in h  # computed ones still present


def test_multi_year_union():
    h = ca_legal_holidays([2026, 2027])
    assert date(2026, 7, 4) in h and date(2027, 7, 4) in h


def test_new_year_on_saturday_observes_previous_dec_31():
    # 2028-01-01 is a Saturday → observed on Fri 2027-12-31 (previous year).
    assert date(2028, 1, 1).weekday() == 5
    assert date(2027, 12, 31) in ca_legal_holidays_for_year(2028)


def test_business_day_counting_skips_a_holiday():
    from app.compliance.date_engine import days_after

    holidays = ca_legal_holidays([2027])
    # Jul 4 2027 is a Sunday → observed Monday 2027-07-05 is a holiday.
    assert date(2027, 7, 5) in holidays
    # 3 business days after Fri 2027-07-02 skips Sat/Sun AND the observed holiday.
    assert days_after(date(2027, 7, 2), 3, unit="business", holidays=holidays) == date(2027, 7, 8)
