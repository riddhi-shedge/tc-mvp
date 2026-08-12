"""Preliminary ('title') report validation (new-docs pipeline).

The master cross-checks a title report against the deal: the vested owner is the
seller, the APN matches the contract, and the report is recent — each a risk flag.
"""

from __future__ import annotations

from datetime import date

from app.contracts.payload import PreliminaryMeta
from app.master.repo import evaluate_preliminary_flags


def _cases(flags) -> set[str]:
    return {f["case_key"] for f in flags}


def test_valid_report_raises_no_flags():
    meta = PreliminaryMeta(
        effective_date="April 22, 2025",
        vestee="Karthik Anantharaman and Subhashini Meenakshi Sundaram",
        apn="357-13-003",
    )
    flags = evaluate_preliminary_flags(
        meta, "Karthik Anantharaman, Subhashini Meenakshi Sundaram", "357-13-003", date(2025, 4, 28)
    )
    assert flags == []


def test_apn_mismatch_flags():
    flags = evaluate_preliminary_flags(PreliminaryMeta(apn="999-99-999"), None, "357-13-003", None)
    assert "prelim_apn_mismatch" in _cases(flags)


def test_apn_match_ignores_separators():
    flags = evaluate_preliminary_flags(PreliminaryMeta(apn="357 13 003"), None, "357-13-003", None)
    assert "prelim_apn_mismatch" not in _cases(flags)


def test_vestee_mismatch_flags():
    flags = evaluate_preliminary_flags(
        PreliminaryMeta(vestee="Some Other Owner LLC"), "Karthik Anantharaman", None, None
    )
    assert "prelim_vestee_mismatch" in _cases(flags)


def test_stale_report_flags():
    flags = evaluate_preliminary_flags(
        PreliminaryMeta(effective_date="01/01/2025"), None, None, date(2025, 4, 28)
    )
    assert "prelim_stale" in _cases(flags)


def test_recent_report_is_not_stale():
    flags = evaluate_preliminary_flags(
        PreliminaryMeta(effective_date="04/22/2025"), None, None, date(2025, 4, 28)
    )
    assert "prelim_stale" not in _cases(flags)
