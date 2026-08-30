"""The CA-calendar-day invariant (Rule 4): deadline logic evaluates 'today' in
America/Los_Angeles, never the server's local date. On a UTC host, date.today()
runs a day ahead from 4-5pm PT — early enough to flag a deadline missed while a
California agent is still at their desk."""

from datetime import date, datetime, timezone

from app.common import dates as ca_dates
from app.compliance.ca_rules import synthetic_ruleset
from app.compliance.service import run_for_transaction

from tests.test_compliance_service import FakeComplianceMaster, _confirmed_deal


class _FrozenDatetime:
    """datetime whose now(tz) is pinned to a fixed UTC instant."""

    def __init__(self, utc_now: datetime) -> None:
        self._utc = utc_now

    def now(self, tz=None):  # mirrors datetime.now(tz)
        return self._utc.astimezone(tz) if tz else self._utc.replace(tzinfo=None)


def test_ca_today_is_the_california_calendar_day(monkeypatch):
    # 03:00 UTC on Mar 2 is still the evening of Mar 1 in California.
    monkeypatch.setattr(
        ca_dates, "datetime", _FrozenDatetime(datetime(2026, 3, 2, 3, 0, tzinfo=timezone.utc))
    )
    assert ca_dates.ca_today() == date(2026, 3, 1)

    # 15:00 UTC the same day IS Mar 2 in California (morning).
    monkeypatch.setattr(
        ca_dates, "datetime", _FrozenDatetime(datetime(2026, 3, 2, 15, 0, tzinfo=timezone.utc))
    )
    assert ca_dates.ca_today() == date(2026, 3, 2)


def test_compliance_runner_defaults_to_ca_today(monkeypatch):
    """run_for_transaction(as_of=None) must evaluate against the CA day."""
    seen: dict[str, date] = {}
    from app.compliance import service as svc

    real_compute = svc.compute

    def spy_compute(state, ruleset, *, as_of):
        seen["as_of"] = as_of
        return real_compute(state, ruleset, as_of=as_of)

    monkeypatch.setattr(svc, "compute", spy_compute)
    monkeypatch.setattr(svc, "ca_today", lambda: date(2026, 7, 15))

    run_for_transaction("txn-1", FakeComplianceMaster(_confirmed_deal()), rules=synthetic_ruleset())
    assert seen["as_of"] == date(2026, 7, 15)
