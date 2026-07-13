"""STUB extractor — Phase 2 walking skeleton ONLY.

Returns a fixed set of §5-candidate fields with fake confidence scores so the
extraction-review screen has real data to render. Replaced in Phase 4 by real
Claude extraction (no-retain config, per-field confidence). Never reads the
document (Phase 2 stores attachment metadata only).
"""

from __future__ import annotations

from typing import Any

from app.contracts.payload import ExtractedField

STUB_PROPERTY_ADDRESS = "123 Stub St, Sacramento, CA 95814 (synthetic)"

_STUB_FIELDS: list[tuple[str, str, float]] = [
    ("property_address", STUB_PROPERTY_ADDRESS, 0.97),
    ("purchase_price", "850000", 0.98),
    ("acceptance_date", "2026-07-10", 0.95),
    ("close_of_escrow", "2026-08-11", 0.88),
    ("inspection_contingency_days", "17", 0.62),
    ("loan_contingency_days", "21", 0.55),
]


def stub_extract(item: dict[str, Any]) -> tuple[list[ExtractedField], str]:
    """Fake extraction for an inbox item: (fields, property address)."""
    fields = [
        ExtractedField(name=name, value=value, confidence=confidence)
        for name, value, confidence in _STUB_FIELDS
    ]
    return fields, STUB_PROPERTY_ADDRESS
