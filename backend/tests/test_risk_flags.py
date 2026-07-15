"""Each of the seven §6 risk-flag cases fires (and doesn't false-fire).
Deterministic via an injected as_of date; thresholds from the synthetic ruleset."""

from datetime import date

from app.compliance.ca_rules import synthetic_ruleset
from app.compliance.risk_flags import detect_risk_flags
from app.contracts.compliance import (
    ComputedDeadline,
    DealDocState,
    DealPartyState,
    DealState,
    DealTaskState,
)

RULES = synthetic_ruleset()


def _dl(key, due) -> ComputedDeadline:
    return ComputedDeadline(key=key, name=key, due_date=due, source_field=key)


def _cases(state, deadlines, as_of):
    return {f.case for f in detect_risk_flags(state, deadlines, RULES, as_of=as_of)}


def test_missing_escrow_contact_always_flags_when_absent():
    state = DealState(transaction_id="t")
    assert "missing_escrow_contact" in _cases(state, [], date(2026, 7, 10))


def test_escrow_present_clears_that_flag():
    state = DealState(transaction_id="t", parties=[DealPartyState(role="escrow", name="Syn")])
    assert "missing_escrow_contact" not in _cases(state, [], date(2026, 7, 10))


def test_inspection_not_scheduled_within_lead():
    state = DealState(transaction_id="t", parties=[DealPartyState(role="escrow")])
    dls = [_dl("inspection_contingency", date(2026, 7, 12))]
    # lead is 3 days; as_of 7/10 is 2 days out -> flags.
    assert "inspection_not_scheduled" in _cases(state, dls, date(2026, 7, 10))


def test_inspection_scheduled_clears_flag():
    state = DealState(
        transaction_id="t",
        parties=[DealPartyState(role="escrow"), DealPartyState(role="inspector_general")],
    )
    dls = [_dl("inspection_contingency", date(2026, 7, 12))]
    assert "inspection_not_scheduled" not in _cases(state, dls, date(2026, 7, 10))


def test_appraisal_not_ordered_within_lead():
    state = DealState(transaction_id="t", parties=[DealPartyState(role="escrow")])
    dls = [_dl("appraisal_contingency", date(2026, 7, 12))]
    assert "appraisal_not_ordered" in _cases(state, dls, date(2026, 7, 10))


def test_loan_contingency_approaching():
    state = DealState(transaction_id="t", parties=[DealPartyState(role="escrow")])
    dls = [_dl("loan_contingency", date(2026, 7, 14))]  # 4 days out, lead 5
    assert "loan_contingency_approaching" in _cases(state, dls, date(2026, 7, 10))


def test_loan_contingency_not_yet_approaching():
    state = DealState(transaction_id="t", parties=[DealPartyState(role="escrow")])
    dls = [_dl("loan_contingency", date(2026, 7, 30))]  # 20 days out
    assert "loan_contingency_approaching" not in _cases(state, dls, date(2026, 7, 10))


def test_earnest_money_not_confirmed_after_due():
    state = DealState(transaction_id="t", parties=[DealPartyState(role="escrow")])
    dls = [_dl("emd", date(2026, 7, 9))]  # due yesterday, no confirming task
    assert "earnest_money_not_confirmed" in _cases(state, dls, date(2026, 7, 10))


def test_earnest_money_confirmed_clears_flag():
    state = DealState(
        transaction_id="t",
        parties=[DealPartyState(role="escrow")],
        tasks=[DealTaskState(title="Confirm earnest money deposited", status="done")],
    )
    dls = [_dl("emd", date(2026, 7, 9))]
    assert "earnest_money_not_confirmed" not in _cases(state, dls, date(2026, 7, 10))


def test_disclosures_unsigned_after_delivery_deadline():
    state = DealState(transaction_id="t", parties=[DealPartyState(role="escrow")])
    dls = [_dl("disclosure_delivery", date(2026, 7, 9))]
    assert "disclosures_unsigned" in _cases(state, dls, date(2026, 7, 10))


def test_disclosures_confirmed_doc_clears_flag():
    state = DealState(
        transaction_id="t",
        parties=[DealPartyState(role="escrow")],
        documents=[DealDocState(doc_type="disclosure", status="confirmed")],
    )
    dls = [_dl("disclosure_delivery", date(2026, 7, 9))]
    assert "disclosures_unsigned" not in _cases(state, dls, date(2026, 7, 10))


def test_closing_near_with_open_tasks():
    state = DealState(
        transaction_id="t",
        parties=[DealPartyState(role="escrow")],
        tasks=[DealTaskState(title="Something", status="pending")],
    )
    dls = [_dl("coe", date(2026, 7, 15))]  # 5 days out, lead 7
    assert "closing_near_open_tasks" in _cases(state, dls, date(2026, 7, 10))


def test_closing_near_but_all_tasks_done():
    state = DealState(
        transaction_id="t",
        parties=[DealPartyState(role="escrow")],
        tasks=[DealTaskState(title="Something", status="done")],
    )
    dls = [_dl("coe", date(2026, 7, 15))]
    assert "closing_near_open_tasks" not in _cases(state, dls, date(2026, 7, 10))
