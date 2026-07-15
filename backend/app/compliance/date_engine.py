"""Deterministic date math for CA deadlines — MECHANICS ONLY.

Encodes the well-sourced counting rules (research A1–A3, ca-rules-verification.md):
calendar days, the trigger day is NOT counted, and only the FINAL day rolls
forward off weekends/holidays. It also supports business-day counting for
periods whose unit is business days.

This module contains NO California rule VALUES — no default periods, no holiday
list. The holiday set and the day unit are passed in from the (human-verified)
RuleSet. Nothing here can silently encode an unverified number.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

DayUnit = Literal["calendar", "business"]

_SATURDAY = 5  # Python weekday(): Mon=0 … Sat=5, Sun=6


def is_business_day(d: date, holidays: frozenset[date]) -> bool:
    return d.weekday() < _SATURDAY and d not in holidays


def next_business_day(d: date, holidays: frozenset[date]) -> date:
    """The first business day on or after d."""
    while not is_business_day(d, holidays):
        d += timedelta(days=1)
    return d


def _add_business_days(trigger: date, n: int, holidays: frozenset[date]) -> date:
    """n business days after the trigger (trigger day not counted)."""
    d = trigger
    counted = 0
    while counted < n:
        d += timedelta(days=1)
        if is_business_day(d, holidays):
            counted += 1
    return d


def days_after(
    trigger: date,
    n: int,
    *,
    unit: DayUnit,
    holidays: frozenset[date],
) -> date:
    """Compute a deadline `n` days after `trigger`.

    calendar: add n calendar days (trigger excluded), then roll the FINAL day
    forward to the next business day if it lands on a weekend/holiday.
    business: count n business days forward (each counted day is already a
    business day, so no separate roll).
    """
    if n < 0:
        raise ValueError("day count must be non-negative")
    if unit == "business":
        return _add_business_days(trigger, n, holidays)
    final = trigger + timedelta(days=n)
    return next_business_day(final, holidays)
