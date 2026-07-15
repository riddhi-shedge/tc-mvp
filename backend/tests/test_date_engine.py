"""Date-engine mechanics (the well-sourced calendar/roll logic). These pin the
math, NOT any CA rule value — periods and holidays are passed in."""

from datetime import date

import pytest

from app.compliance.date_engine import (
    days_after,
    is_business_day,
    next_business_day,
)

NO_HOLIDAYS: frozenset[date] = frozenset()


def test_calendar_days_exclude_the_trigger_day():
    # Fri 2026-07-10 + 3 calendar days -> Mon 2026-07-13 (13th is a Monday).
    assert days_after(date(2026, 7, 10), 3, unit="calendar", holidays=NO_HOLIDAYS) == date(
        2026, 7, 13
    )


def test_final_day_rolls_off_weekend():
    # Wed 2026-07-08 + 3 calendar days -> Sat 7/11 -> rolls to Mon 7/13.
    assert days_after(date(2026, 7, 8), 3, unit="calendar", holidays=NO_HOLIDAYS) == date(
        2026, 7, 13
    )


def test_intermediate_weekends_still_count():
    # 17 calendar days spanning weekends; only the FINAL day rolls.
    # 2026-07-10 (Fri) + 17 = 2026-07-27 (Mon) — a business day, no roll.
    assert days_after(date(2026, 7, 10), 17, unit="calendar", holidays=NO_HOLIDAYS) == date(
        2026, 7, 27
    )


def test_final_day_rolls_off_holiday():
    holidays = frozenset({date(2026, 7, 13)})  # Monday holiday
    # Wed 7/8 + 3 -> Sat 7/11 -> Sun 7/12 -> Mon 7/13 (holiday) -> Tue 7/14.
    assert days_after(date(2026, 7, 8), 3, unit="calendar", holidays=holidays) == date(2026, 7, 14)


def test_business_days_skip_weekends_and_holidays():
    # Fri 2026-07-10 + 3 business days, with Mon 7/13 a holiday:
    # skip Sat/Sun, 7/13 holiday -> count 7/14(1), 7/15(2), 7/16(3).
    holidays = frozenset({date(2026, 7, 13)})
    assert days_after(date(2026, 7, 10), 3, unit="business", holidays=holidays) == date(2026, 7, 16)


def test_zero_days_is_the_trigger_rolled():
    # 0 calendar days: the trigger day itself, rolled if it's a weekend.
    assert days_after(date(2026, 7, 11), 0, unit="calendar", holidays=NO_HOLIDAYS) == date(
        2026, 7, 13
    )


def test_negative_days_rejected():
    with pytest.raises(ValueError):
        days_after(date(2026, 7, 10), -1, unit="calendar", holidays=NO_HOLIDAYS)


def test_business_day_helpers():
    assert is_business_day(date(2026, 7, 10), NO_HOLIDAYS) is True  # Friday
    assert is_business_day(date(2026, 7, 11), NO_HOLIDAYS) is False  # Saturday
    assert next_business_day(date(2026, 7, 11), NO_HOLIDAYS) == date(2026, 7, 13)
