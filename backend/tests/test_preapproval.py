"""Preapproval / underwriter-letter validation (new-docs pipeline).

The master checks a preapproval against the deal: same borrower, approved for at
least the contract loan, and valid through closing — each failure a risk flag.
"""

from __future__ import annotations

from datetime import date

from app.contracts.payload import PreapprovalMeta
from app.master.repo import evaluate_preapproval_flags


def _cases(flags) -> set[str]:
    return {f["case_key"] for f in flags}


def test_valid_preapproval_raises_no_flags():
    meta = PreapprovalMeta(
        buyer_names="Rajkumar Methuku and Rajeshwari Vanamala",
        expiration="July 30, 2025",
        loan_amount="$2,600,000",
    )
    flags = evaluate_preapproval_flags(
        meta, "Rajkumar Methuku, Rajeshwari Vanamala", "$1,100,000.00 (61% of price)", date(2025, 5, 12)
    )
    assert flags == []


def test_insufficient_loan_is_critical():
    flags = evaluate_preapproval_flags(PreapprovalMeta(loan_amount="$900,000"), None, "$1,100,000", None)
    assert "preapproval_insufficient" in _cases(flags)
    assert any(f["severity"] == "critical" for f in flags)


def test_borrower_name_mismatch_flags():
    flags = evaluate_preapproval_flags(PreapprovalMeta(buyer_names="John Smith"), "Rajkumar Methuku", None, None)
    assert "preapproval_name_mismatch" in _cases(flags)


def test_a_subset_borrower_is_not_a_mismatch():
    # One co-borrower's letter still overlaps the contract's two buyers.
    flags = evaluate_preapproval_flags(
        PreapprovalMeta(buyer_names="Rajkumar Methuku"), "Rajkumar Methuku, Rajeshwari Vanamala", None, None
    )
    assert "preapproval_name_mismatch" not in _cases(flags)


def test_expiration_before_close_flags():
    flags = evaluate_preapproval_flags(PreapprovalMeta(expiration="04/30/2025"), None, None, date(2025, 8, 4))
    assert "preapproval_expired" in _cases(flags)


def test_expiration_after_close_is_fine():
    flags = evaluate_preapproval_flags(PreapprovalMeta(expiration="09/30/2025"), None, None, date(2025, 8, 4))
    assert "preapproval_expired" not in _cases(flags)
