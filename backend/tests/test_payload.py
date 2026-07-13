"""Tests for the Payload contract — written first (TDD). Synthetic data only.

These pin the boundary that ingestion (a) and master (b) both depend on, so each
part can later be tested in isolation against a synthetic Payload.
"""

import pytest
from pydantic import ValidationError

from app.contracts.payload import NEW_TRANSACTION, ExtractedField, Payload


def _field(**overrides) -> dict:
    base = {"name": "close_of_escrow", "value": "2026-08-15", "confidence": 0.92}
    base.update(overrides)
    return base


def test_valid_payload_builds():
    payload = Payload(
        document_id="doc-1",
        transaction_id="txn-1",
        party_id="party-1",
        extracted_fields=[ExtractedField(**_field())],
    )
    assert payload.document_id == "doc-1"
    assert payload.extracted_fields[0].name == "close_of_escrow"


def test_extracted_fields_default_to_empty_list():
    payload = Payload(document_id="doc-1", transaction_id="txn-1")
    assert payload.extracted_fields == []
    assert payload.party_id is None


def test_confirmed_defaults_false():
    field = ExtractedField(**_field())
    assert field.confirmed is False


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.1, 2.0])
def test_confidence_out_of_range_is_rejected(bad_confidence):
    with pytest.raises(ValidationError):
        ExtractedField(**_field(confidence=bad_confidence))


@pytest.mark.parametrize("good_confidence", [0.0, 0.5, 1.0])
def test_confidence_bounds_are_inclusive(good_confidence):
    field = ExtractedField(**_field(confidence=good_confidence))
    assert field.confidence == good_confidence


def test_empty_field_name_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedField(**_field(name=""))


def test_empty_document_id_is_rejected():
    with pytest.raises(ValidationError):
        Payload(document_id="", transaction_id="txn-1")


def test_new_transaction_flag():
    new_payload = Payload(document_id="doc-1", transaction_id=NEW_TRANSACTION)
    existing_payload = Payload(document_id="doc-1", transaction_id="txn-1")
    assert new_payload.is_new_transaction is True
    assert existing_payload.is_new_transaction is False
