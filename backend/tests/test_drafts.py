"""Draft reminders: Rule 3 (draft only) and Rule 1 (never a C.A.R. form)."""

from app.compliance.drafts import draft_reminders
from app.contracts.compliance import RiskFlag


def test_each_flag_yields_a_draft_reminder():
    flags = [
        RiskFlag(case="loan_contingency_approaching", description="x"),
        RiskFlag(case="missing_escrow_contact", description="y"),
    ]
    drafts = draft_reminders(flags)
    assert {d.flag_case for d in drafts} == {
        "loan_contingency_approaching",
        "missing_escrow_contact",
    }


def test_drafts_never_reference_a_car_form_or_removal_doc():
    all_flags = [
        RiskFlag(case=c, description="x")
        for c in (
            "inspection_not_scheduled",
            "appraisal_not_ordered",
            "loan_contingency_approaching",
            "earnest_money_not_confirmed",
            "disclosures_unsigned",
            "missing_escrow_contact",
            "closing_near_open_tasks",
        )
    ]
    for d in draft_reminders(all_flags):
        text = f"{d.subject} {d.body}".lower()
        assert "c.a.r." not in text and "contingency removal" not in text
        assert "form cr" not in text and "removal form" not in text


def test_unknown_flag_case_is_skipped():
    assert draft_reminders([RiskFlag(case="totally-made-up", description="x")]) == []
