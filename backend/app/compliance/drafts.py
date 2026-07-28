"""Pure draft-reminder generation (part c): risk flags -> draft messages.

Rule 3: every message is a DRAFT requiring human approval — nothing here sends.
Rule 1: these are plain status reminders; NONE generates a C.A.R. form or the
contingency-removal document.
"""

from __future__ import annotations

from app.contracts.compliance import DraftReminder, RiskFlag

# case -> (to_role, subject, body). Plain reminders only — never a form.
_TEMPLATES: dict[str, tuple[str | None, str, str]] = {
    "inspection_not_scheduled": (
        "buyer",
        "Schedule inspections soon",
        "The inspection contingency window is approaching and no inspection is "
        "on file yet. Please schedule inspections so we can meet the deadline.",
    ),
    "appraisal_not_ordered": (
        "lender",
        "Appraisal status",
        "The appraisal contingency window is approaching. Could you confirm the "
        "appraisal has been ordered and share the expected completion date?",
    ),
    "loan_contingency_approaching": (
        "lender",
        "Loan contingency deadline approaching",
        "The loan contingency deadline is near. Please confirm the current loan "
        "status and whether the contingency can be removed on time.",
    ),
    "earnest_money_not_confirmed": (
        "escrow",
        "Earnest money confirmation",
        "Could you confirm receipt of the buyer's earnest money deposit? Our "
        "records don't yet show it confirmed past the due date.",
    ),
    "disclosures_unsigned": (
        "buyer",
        "Outstanding disclosures",
        "Seller disclosures are not yet confirmed as reviewed. Please review and "
        "acknowledge the disclosure package.",
    ),
    "insurance_info_pending": (
        "buyer",
        "Homeowner's insurance binder needed",
        "Your homeowner's insurance isn't on file yet and the insurance contingency "
        "is approaching. Please send your insurance binder so we can confirm coverage "
        "before the deadline.",
    ),
    "seller_forms_incomplete": (
        "listing_agent",
        "Seller disclosures due soon",
        "The seller disclosure package is due soon and isn't confirmed delivered yet. "
        "Please complete and deliver the seller disclosures so the buyer's review "
        "period can begin on time.",
    ),
    "missing_escrow_contact": (
        None,
        "Escrow contact needed",
        "No escrow holder contact is on this deal yet. Please add the escrow "
        "company and officer so we can coordinate.",
    ),
    "closing_near_open_tasks": (
        None,
        "Open items before closing",
        "Close of escrow is near and some tasks are still open. Please review the "
        "outstanding items so we can close on time.",
    ),
}


def draft_reminders(flags: list[RiskFlag]) -> list[DraftReminder]:
    drafts: list[DraftReminder] = []
    for flag in flags:
        template = _TEMPLATES.get(flag.case)
        if template is None:
            continue
        to_role, subject, body = template
        drafts.append(
            DraftReminder(flag_case=flag.case, to_role=to_role, subject=subject, body=body)
        )
    return drafts
