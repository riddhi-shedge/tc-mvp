"""OPT-IN real-Claude extraction test (one API call, SYNTHETIC fixture only).

Run with:  RUN_LLM_TESTS=1 pytest tests/test_llm_extraction.py
Requires ANTHROPIC_API_KEY in the environment (source ../.env). The ZDR gate
allows this because SYNTHETIC_ONLY=true — the fixture is a synthetic document.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="real-LLM test is opt-in (RUN_LLM_TESTS=1 + ANTHROPIC_API_KEY)",
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_real_extraction_on_synthetic_signed_pa():
    from app.contracts.fields import DEADLINE_DRIVING
    from app.ingestion.extractor import ClaudeExtractor

    pdf = (FIXTURES / "synthetic_pa_signed.pdf").read_bytes()
    result = ClaudeExtractor().extract(pdf_bytes=pdf, doc_type="purchase_agreement")

    assert result.doc_looks_like == "purchase_agreement"
    assert result.signature_detected is True

    by_name = {f.name: f for f in result.fields}
    assert "850" in by_name["purchase_price"].value
    assert "123 Stub St" in by_name["property_address"].value
    assert by_name["inspection_contingency_days"].value.strip().startswith("17")
    assert by_name["loan_contingency_days"].value.strip().startswith("21")
    assert "insurance_contingency_days" in by_name  # the v2 addition
    assert all(0.0 <= f.confidence <= 1.0 for f in result.fields)
    # DD fields present for the gate to bite on.
    assert DEADLINE_DRIVING & set(by_name)
    # Rule 2: nothing wiring-shaped can appear (whitelist guarantees it).
    assert all(f.name in by_name and "wire" not in f.name for f in result.fields)
