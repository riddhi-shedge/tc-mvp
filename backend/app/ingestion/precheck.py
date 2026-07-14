"""PDF pre-check (§13, Phase 4): cheap deterministic checks BEFORE any model
call. Failures are §4 "never silently guess" states — the document routes to
manual field entry (or a better upload), it is never guessed at.

Reasons are structural only (page counts, text presence) — never document
content (Rule 5 logging discipline)."""

from __future__ import annotations

import os
from io import BytesIO

# Minimum extractable characters for a doc to count as having a text layer.
_MIN_TEXT_CHARS = 200


def _pa_min_pages() -> int:
    return int(os.environ.get("PA_MIN_PAGES", "2"))


def precheck_pdf(pdf_bytes: bytes, *, expect_purchase_agreement: bool) -> list[str]:
    """Returns a list of human-readable failure reasons; empty means OK."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        if reader.is_encrypted:
            return ["the PDF is encrypted and cannot be read"]
        page_count = len(reader.pages)
        text_chars = sum(len((page.extract_text() or "").strip()) for page in reader.pages)
    except PyPdfError:
        return ["the file is not a readable PDF"]
    except Exception:
        return ["the file could not be parsed as a PDF"]

    if page_count == 0:
        return ["the PDF has no pages"]
    reasons: list[str] = []
    if expect_purchase_agreement and page_count < _pa_min_pages():
        reasons.append(
            f"the document has {page_count} page(s); a purchase agreement is "
            f"expected to have at least {_pa_min_pages()} — possible missing pages"
        )
    if text_chars < _MIN_TEXT_CHARS:
        reasons.append(
            "no usable text layer found (likely an image-only scan) — manual field entry required"
        )
    return reasons
