"""Heuristic detection (Phase 3): doc type from filename/subject, readability
from metadata. Unknown types ASK the TC; unreadable goes to manual fallback."""

import pytest

from app.ingestion.detector import UNKNOWN_DOC_TYPE, check_readability, detect_doc_type


@pytest.mark.parametrize(
    ("filename", "subject", "expected"),
    [
        ("signed-rpa.pdf", "Signed RPA — 12 Elm St", "purchase_agreement"),
        ("contract.pdf", "Residential Purchase Agreement attached", "purchase_agreement"),
        ("pof.pdf", "Proof of funds for buyers", "proof_of_funds"),
        ("statement.pdf", "POF attached", "proof_of_funds"),
        ("tds.pdf", "Seller disclosure package", "disclosure"),
        ("report.pdf", "General inspection report", "property_inspection"),
        ("termite.pdf", "Termite findings", "termite_inspection"),
        ("roof.pdf", "Roof report", "inspection_report"),
        ("scan001.pdf", "Documents", UNKNOWN_DOC_TYPE),
        (None, None, UNKNOWN_DOC_TYPE),
    ],
)
def test_detect_doc_type(filename, subject, expected):
    assert detect_doc_type(filename, subject) == expected


def test_purchase_agreement_outranks_other_keywords():
    # A PA email that also mentions disclosures is still the deal-creating doc.
    assert detect_doc_type("rpa-with-disclosures.pdf", "RPA + disclosure") == "purchase_agreement"


def test_readable_pdf_passes():
    assert (
        check_readability(
            attachment_name="doc.pdf",
            content_type="application/pdf",
            size=100,
            has_content=True,
        )
        is None
    )


@pytest.mark.parametrize(
    ("kwargs", "reason_fragment"),
    [
        (
            {"attachment_name": None, "content_type": None, "size": None, "has_content": False},
            "no readable attachment",
        ),
        (
            {
                "attachment_name": "photo.jpg",
                "content_type": "image/jpeg",
                "size": 100,
                "has_content": True,
            },
            "not a PDF",
        ),
        (
            {
                "attachment_name": "doc.pdf",
                "content_type": "application/pdf",
                "size": 0,
                "has_content": True,
            },
            "empty",
        ),
        (
            {
                "attachment_name": "doc.pdf",
                "content_type": "application/pdf",
                "size": 100,
                "has_content": False,
            },
            "no readable attachment",
        ),
    ],
)
def test_unreadable_routes_to_manual(kwargs, reason_fragment):
    reason = check_readability(**kwargs)
    assert reason is not None and reason_fragment in reason
