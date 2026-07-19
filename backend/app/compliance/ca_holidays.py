"""California legal holidays for deadline counting.

The RPA 6/26 defines "Legal Holiday" (¶ Definitions rule 4/5) as any holiday or
optional bank holiday under Civil Code §§ 7 and 7.1, plus any holiday under
Government Code § 6700. This module generates the DETERMINISTIC ones (fixed-date
and weekday-rule, including optional bank holidays such as Columbus Day) with the
standard weekend observation (Sat → prior Fri, Sun → following Mon).

NOT included here, by design (KNOWN LIMITATIONS — see the pre-go-live items in
docs/ca-rules-verification.md):
  * Lunar New Year and Diwali — set by lunar calendars, not computable by
    formula. Supply them (and any Governor/President-proclaimed day) via the
    `extra` override list in the verified RuleSet. Until populated, a deadline
    whose final day lands on one of these will NOT roll — populate before go-live.
  * Good Friday — a partial (noon–3 p.m.) holiday, not a full-day closure.
  * Every Sunday — handled by the weekend logic in date_engine, not here.
  * The COE-only extra rule (form ¶ rule 5: days the County Recorder / lender /
    closing agent are closed also push the Close-of-Escrow allowable day) — needs
    county/lender-specific closure data; out of scope for this engine.

Verified against docs/ca-rules-verification.md (row A6), RPA 6/26.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

_MON, _FRI = 0, 4  # date.weekday(): Mon=0 … Sun=6
_THU = 3

# Fixed-date CA holidays (month, day). Cesar Chavez Day (3/31), Lincoln Day
# (2/12) and Admission Day (9/9) are California-specific state holidays.
_FIXED: tuple[tuple[int, int], ...] = (
    (1, 1),    # New Year's Day
    (2, 12),   # Lincoln Day
    (3, 31),   # Cesar Chavez Day
    (6, 19),   # Juneteenth
    (7, 4),    # Independence Day
    (9, 9),    # Admission Day
    (11, 11),  # Veterans Day
    (12, 25),  # Christmas Day
)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th `weekday` of a month (n≥1), or the last one if n == -1."""
    if n == -1:
        nxt = date(year + (month == 12), (month % 12) + 1, 1)
        last = nxt - timedelta(days=1)
        offset = (last.weekday() - weekday) % 7
        return last - timedelta(days=offset)
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _observed(d: date) -> date:
    """Weekend observation: Saturday → prior Friday, Sunday → following Monday."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def ca_legal_holidays_for_year(year: int) -> set[date]:
    """The deterministic CA legal holidays observed in `year` (nominal date plus
    the observed weekday when a fixed-date holiday lands on a weekend)."""
    days: set[date] = set()
    for month, day in _FIXED:
        nominal = date(year, month, day)
        days.add(nominal)
        days.add(_observed(nominal))  # no-op when it's already a weekday
    days.add(_nth_weekday(year, 1, _MON, 3))    # MLK Jr. Day
    days.add(_nth_weekday(year, 2, _MON, 3))    # Presidents' / Washington Day
    days.add(_nth_weekday(year, 5, _MON, -1))   # Memorial Day (last Monday)
    days.add(_nth_weekday(year, 9, _MON, 1))    # Labor Day
    days.add(_nth_weekday(year, 9, _FRI, 4))    # Native American Day (4th Friday)
    days.add(_nth_weekday(year, 10, _MON, 2))   # Columbus Day (optional bank, §7.1)
    thanksgiving = _nth_weekday(year, 11, _THU, 4)
    days.add(thanksgiving)
    days.add(thanksgiving + timedelta(days=1))  # Day after Thanksgiving
    return days


def ca_legal_holidays(
    years: Iterable[int], extra: Iterable[date] = ()
) -> frozenset[date]:
    """CA legal holidays across `years`, unioned with `extra` override dates
    (Lunar New Year / Diwali / proclaimed days that can't be computed)."""
    out: set[date] = set()
    for y in years:
        out |= ca_legal_holidays_for_year(y)
    out |= set(extra)
    return frozenset(out)
