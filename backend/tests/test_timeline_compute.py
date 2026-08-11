"""Pure timeline compute against synthetic state + the synthetic ruleset. Dates
are computed by the (well-sourced) engine; the periods come from the synthetic
ruleset (17/21/17/17/7/3, arbitrary test values — NOT verified CA rules)."""

from datetime import date

from app.compliance.ca_rules import synthetic_ruleset
from app.compliance.timeline import compute_timeline
from app.contracts.compliance import DealFieldState, DealState


def _field(name, value, *, confirmed=True, dd=True) -> DealFieldState:
    return DealFieldState(name=name, value=value, confirmed=confirmed, deadline_driving=dd)


def _state(fields) -> DealState:
    return DealState(transaction_id="txn-1", fields=fields)


def test_removed_contingency_produces_no_deadline():
    # A Contingency Removal form overrides the day-field to "removed"; the timeline
    # skips it (like a waiver), so no deadline/task is created for it.
    state = _state(
        [
            _field("acceptance_date", "2026-07-10"),
            _field("inspection_contingency_days", "removed"),
            _field("loan_contingency_days", "21 days"),
        ]
    )
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    keys = {d.key for d in deadlines}
    assert "inspection_contingency" not in keys
    assert "loan_contingency" in keys


def test_contingency_deadlines_use_field_value_over_default():
    state = _state(
        [
            _field("acceptance_date", "2026-07-10"),
            _field("inspection_contingency_days", "17 days"),
            _field("loan_contingency_days", "21 days"),
        ]
    )
    deadlines, tasks = compute_timeline(state, synthetic_ruleset())
    by_key = {d.key: d for d in deadlines}
    assert by_key["inspection_contingency"].due_date == date(2026, 7, 27)
    assert by_key["loan_contingency"].due_date == date(2026, 7, 31)
    # Each deadline gets a task tied to it.
    assert {t.deadline_key for t in tasks} >= {"inspection_contingency", "loan_contingency"}


def test_missing_period_value_falls_back_to_ruleset_default():
    # Field present but non-numeric -> use the synthetic default (17 calendar).
    state = _state(
        [
            _field("acceptance_date", "2026-07-10"),
            _field("inspection_contingency_days", "per addendum"),
        ]
    )
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    assert deadlines[0].due_date == date(2026, 7, 27)


def test_business_day_unit_from_ruleset():
    # emd default is 3 BUSINESS days in the synthetic ruleset.
    state = _state(
        [_field("acceptance_date", "2026-07-10"), _field("emd_due_days", "not-a-number")]
    )
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    emd = next(d for d in deadlines if d.key == "emd")
    # 7/10 Fri + 3 business days (no holidays in this state's ruleset weekdays) = 7/15 Wed.
    assert emd.due_date == date(2026, 7, 15)


def test_coe_as_days_after_acceptance():
    state = _state(
        [
            _field("acceptance_date", "2026-07-10"),
            _field("close_of_escrow", "30 days after acceptance"),
        ]
    )
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    coe = next(d for d in deadlines if d.key == "coe")
    # 7/10 + 30 cal = 8/9 Sun -> rolls to Mon 8/10.
    assert coe.due_date == date(2026, 8, 10)


def test_coe_as_explicit_date():
    state = _state([_field("close_of_escrow", "2026-08-14")])
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    assert next(d for d in deadlines if d.key == "coe").due_date == date(2026, 8, 14)


def test_unconfirmed_fields_are_not_used():
    state = _state(
        [
            _field("acceptance_date", "2026-07-10"),
            _field("inspection_contingency_days", "17", confirmed=False),
        ]
    )
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    assert not any(d.key == "inspection_contingency" for d in deadlines)


def test_no_acceptance_date_means_no_contingency_deadlines():
    state = _state([_field("inspection_contingency_days", "17")])
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    assert deadlines == []


def test_possession_at_coe_resolves_to_coe_date():
    state = _state(
        [
            _field("acceptance_date", "2026-07-10"),
            _field("close_of_escrow", "2026-08-14"),
            _field("possession_date", "at close of escrow, 6:00 PM"),
        ]
    )
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    poss = next(d for d in deadlines if d.key == "possession")
    assert poss.due_date == date(2026, 8, 14)  # tracks COE


def test_possession_explicit_date():
    state = _state([_field("possession_date", "2026-08-20")])
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    assert next(d for d in deadlines if d.key == "possession").due_date == date(2026, 8, 20)


def test_waived_contingency_creates_no_deadline():
    state = _state(
        [
            _field("acceptance_date", "2026-07-10"),
            _field("loan_contingency_days", "waived"),
            _field("inspection_contingency_days", "17"),
        ]
    )
    deadlines, _ = compute_timeline(state, synthetic_ruleset())
    keys = {d.key for d in deadlines}
    assert "loan_contingency" not in keys
    assert "inspection_contingency" in keys
