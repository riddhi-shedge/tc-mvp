"""PDF pre-check against the committed synthetic fixtures — the §4 error
states (unreadable / missing pages / no text layer) must be caught cheaply,
before any model call."""

from pathlib import Path

from app.ingestion.precheck import precheck_pdf

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_signed_pa_passes():
    assert precheck_pdf(_load("synthetic_pa_signed.pdf"), expect_purchase_agreement=True) == []


def test_truncated_pa_reports_missing_pages():
    reasons = precheck_pdf(_load("synthetic_pa_truncated.pdf"), expect_purchase_agreement=True)
    assert any("missing pages" in r for r in reasons)


def test_image_only_scan_reports_no_text_layer():
    reasons = precheck_pdf(_load("synthetic_scan_no_text.pdf"), expect_purchase_agreement=True)
    assert any("text layer" in r for r in reasons)


def test_garbage_bytes_not_a_pdf():
    reasons = precheck_pdf(b"this is not a pdf at all", expect_purchase_agreement=True)
    assert reasons and "PDF" in reasons[0]


def test_single_page_ok_when_not_a_pa():
    """Only purchase agreements carry the minimum-page expectation."""
    reasons = precheck_pdf(_load("synthetic_pof.pdf"), expect_purchase_agreement=False)
    assert not any("missing pages" in r for r in reasons)
