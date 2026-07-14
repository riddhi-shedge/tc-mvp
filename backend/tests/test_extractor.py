"""Extractor unit tests: the ZDR gate (Rule 5) and the §5 whitelist filter
(Rule 2 by construction). No network — the Claude call itself is covered by
the opt-in test_llm_extraction.py."""

import pytest

from app.ingestion.extractor import (
    ClaudeExtractor,
    ExtractionBlocked,
    check_zdr_gate,
    parse_extraction_output,
)


def test_gate_open_in_synthetic_only_mode(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_ONLY", "true")
    monkeypatch.delenv("ZDR_CONFIRMED", raising=False)
    check_zdr_gate()  # no raise


def test_gate_open_when_zdr_confirmed(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_ONLY", "false")
    monkeypatch.setenv("ZDR_CONFIRMED", "true")
    check_zdr_gate()  # no raise


def test_gate_blocks_real_mode_without_zdr(monkeypatch):
    """Flipping SYNTHETIC_ONLY off without confirmed ZDR hard-stops extraction."""
    monkeypatch.setenv("SYNTHETIC_ONLY", "false")
    monkeypatch.setenv("ZDR_CONFIRMED", "false")
    with pytest.raises(ExtractionBlocked, match="zero-data-retention"):
        check_zdr_gate()


def test_claude_extractor_respects_gate_before_any_call(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_ONLY", "false")
    monkeypatch.setenv("ZDR_CONFIRMED", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-key")
    with pytest.raises(ExtractionBlocked):
        ClaudeExtractor().extract(pdf_bytes=b"%PDF-", doc_type="purchase_agreement")


def _output(fields: list, **overrides) -> dict:
    data = {
        "doc_looks_like": "purchase_agreement",
        "signature_indicators": True,
        "fields": fields,
    }
    data.update(overrides)
    return data


def test_whitelist_drops_non_s5_and_wiring_names():
    result = parse_extraction_output(
        _output(
            [
                {"name": "purchase_price", "value": "850000", "confidence": 0.9},
                {"name": "wire_routing_number", "value": "synthetic", "confidence": 0.9},
                {"name": "made_up_field", "value": "x", "confidence": 0.5},
            ]
        )
    )
    assert [f.name for f in result.fields] == ["purchase_price"]


def test_empty_values_are_skipped_and_duplicates_keep_highest_confidence():
    result = parse_extraction_output(
        _output(
            [
                {"name": "title_company", "value": "  ", "confidence": 0.4},
                {"name": "purchase_price", "value": "999999", "confidence": 0.1},
                {"name": "purchase_price", "value": "850000", "confidence": 0.9},
            ]
        )
    )
    assert [(f.name, f.value, f.confidence) for f in result.fields] == [
        ("purchase_price", "850000", 0.9)
    ]


def test_unknown_doc_looks_like_normalizes_to_other():
    result = parse_extraction_output(_output([], doc_looks_like="w2-form"))
    assert result.doc_looks_like == "other"


def test_confidence_is_clamped_and_coerced():
    result = parse_extraction_output(
        _output(
            [
                {"name": "purchase_price", "value": "850000", "confidence": 1.7},
                {"name": "apn", "value": "000-000-000", "confidence": -0.2},
                {"name": "buyer_names", "value": "Alex Synthetic", "confidence": "nan?"},
            ]
        )
    )
    by_name = {f.name: f.confidence for f in result.fields}
    assert by_name == {"purchase_price": 1.0, "apn": 0.0, "buyer_names": 0.0}


def test_doc_type_and_signature_pass_through():
    result = parse_extraction_output(
        _output([], doc_looks_like="proof_of_funds", signature_indicators=False)
    )
    assert result.doc_looks_like == "proof_of_funds"
    assert result.signature_detected is False
    assert result.fields == []


def test_fields_never_arrive_preconfirmed():
    """Model output can't mark anything confirmed — only the TC (or manual
    entry, which IS the TC) does that."""
    result = parse_extraction_output(
        _output([{"name": "purchase_price", "value": "850000", "confidence": 0.9}])
    )
    assert all(f.confirmed is False for f in result.fields)
