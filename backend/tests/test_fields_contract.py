"""Pins the HUMAN-VERIFIED §5 v2 field list (2026-07-13). If this test needs a
change, the list needs a new human verification first — do not just update the
expectations (docs/s5-field-verification.md)."""

from app.contracts.fields import (
    DEADLINE_DRIVING,
    EXTRACTABLE_FIELD_NAMES,
    S5_FIELDS,
    is_deadline_driving,
    is_extractable_field,
)

VERIFIED_DEADLINE_DRIVING = {
    "acceptance_date",
    "close_of_escrow",
    "possession_date",
    "emd_due_days",
    "inspection_contingency_days",
    "loan_contingency_days",
    "appraisal_contingency_days",
    "insurance_contingency_days",
    "disclosure_delivery_days",
    "verification_of_funds_days",
}


def test_deadline_driving_set_is_exactly_the_verified_one():
    assert DEADLINE_DRIVING == VERIFIED_DEADLINE_DRIVING


def test_insurance_contingency_added_in_v2():
    assert "insurance_contingency_days" in EXTRACTABLE_FIELD_NAMES
    assert "insurance_contingency_present" in EXTRACTABLE_FIELD_NAMES


def test_contingency_removal_dates_are_not_extractable():
    """Removed in v2: removals arrive as separate CR/CR-B documents."""
    assert not any("removal" in name for name in EXTRACTABLE_FIELD_NAMES)


def test_no_wiring_shaped_field_names():
    """Rule 2 by construction: the whitelist contains no money-movement names."""
    for banned in ("wire", "wiring", "routing", "account_number", "iban", "swift"):
        assert not any(banned in name for name in EXTRACTABLE_FIELD_NAMES)


def test_verification_of_funds_is_deadline_driving():
    assert is_deadline_driving("verification_of_funds_days")  # Maybe -> Yes in v2


def test_field_count_and_uniqueness():
    names = [f.name for f in S5_FIELDS]
    assert len(names) == len(set(names))
    # 30 verified v2 + 5 v3 (items, home-warranty, other_terms) + 4 v4 agent
    # contact fields (buyer/listing agent email+phone) + 2 lender_contact
    # email/phone (preapproval officer) — v3/v4 non-deadline-driving.
    assert len(names) == 41


def test_membership_helpers():
    assert is_extractable_field("purchase_price")
    assert not is_extractable_field("wire_routing_number")
    assert not is_deadline_driving("purchase_price")
