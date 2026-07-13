"""Heuristic document detection for the ingestion agent (part a).

Phase 3 detects doc TYPE from filename + subject keywords and basic
READABILITY from attachment metadata. Content-level checks (page count,
signature presence, scan quality via pypdf) arrive with Phase 4's pre-check —
until then anything that can't even be read as a PDF routes to the
manual-upload fallback, and unknown types ASK the TC (never guess)."""

from __future__ import annotations

import re

from app.contracts.documents import UNKNOWN_DOC_TYPE, DocType

__all__ = ["UNKNOWN_DOC_TYPE", "check_readability", "detect_doc_type"]

# Ordered: first match wins. Purchase agreement outranks everything because a
# signed PA is the deal-creating document (§11 step 1).
_DOC_TYPE_PATTERNS: list[tuple[DocType, re.Pattern[str]]] = [
    (
        "purchase_agreement",
        re.compile(r"purchase\s+agreement|residential\s+purchase|\brpa\b", re.IGNORECASE),
    ),
    ("proof_of_funds", re.compile(r"proof\s+of\s+funds|\bpof\b", re.IGNORECASE)),
    ("disclosure", re.compile(r"disclosure", re.IGNORECASE)),
    (
        "inspection_report",
        re.compile(r"inspection\s+report|termite|pest\s+report|roof\s+report|sewer", re.IGNORECASE),
    ),
]


def detect_doc_type(filename: str | None, subject: str | None) -> DocType:
    """Best-effort type from filename + subject; 'unknown' means ASK the TC."""
    haystack = f"{filename or ''} {subject or ''}"
    for doc_type, pattern in _DOC_TYPE_PATTERNS:
        if pattern.search(haystack):
            return doc_type
    return UNKNOWN_DOC_TYPE


def check_readability(
    *,
    attachment_name: str | None,
    content_type: str | None,
    size: int | None,
    has_content: bool,
) -> str | None:
    """None when the attachment looks processable; otherwise the reason it
    must go to the manual-upload fallback."""
    if not attachment_name or not has_content:
        return "no readable attachment on the email"
    if content_type != "application/pdf" and not attachment_name.lower().endswith(".pdf"):
        return "attachment is not a PDF"
    if not size or size <= 0:
        return "attachment is empty"
    return None
