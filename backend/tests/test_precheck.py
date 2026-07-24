"""PDF pre-check against the committed synthetic fixtures — the §4 error
states (unreadable / missing pages / no text layer) must be caught cheaply,
before any model call."""

from io import BytesIO
from pathlib import Path

from app.ingestion.precheck import decrypt_pdf, precheck_pdf

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _encrypt(pdf_bytes: bytes, *, user_pw: str, owner_pw: str) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(BytesIO(pdf_bytes)).pages:
        writer.add_page(page)
    writer.encrypt(user_password=user_pw, owner_password=owner_pw)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


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


def test_owner_password_pdf_is_unlocked_and_passes():
    """Owner-only encryption (empty user password) — common in zipForm/DocuSign —
    is readable and must NOT be forced to manual entry."""
    enc = _encrypt(_load("synthetic_pa_signed.pdf"), user_pw="", owner_pw="owner")
    readable = decrypt_pdf(enc)
    assert readable is not None
    assert precheck_pdf(readable, expect_purchase_agreement=True) == []
    # precheck alone also tolerates the still-encrypted (empty-password) bytes
    assert not any("password" in r for r in precheck_pdf(enc, expect_purchase_agreement=True))


def test_user_password_pdf_is_blocked():
    """A real user password can't be opened — that IS a manual-entry case."""
    enc = _encrypt(_load("synthetic_pa_signed.pdf"), user_pw="secret", owner_pw="secret")
    assert decrypt_pdf(enc) is None
    reasons = precheck_pdf(enc, expect_purchase_agreement=True)
    assert any("password-protected" in r for r in reasons)
