"""Cross-document inconsistency detection (proposal §2.8): a re-uploaded purchase
agreement whose material values differ from what the TC already confirmed raises a
risk flag rather than silently overwriting."""

import uuid

from app.contracts.payload import ExtractedField, Payload
from app.master.inconsistency import find_field_conflicts
from tests.fake_repo import InMemoryRepo


# ---- pure comparison -------------------------------------------------------

def test_no_conflict_when_values_match_after_normalization():
    existing = {"purchase_price": "$450,000", "close_of_escrow": "2026-08-11"}
    incoming = {"purchase_price": "450000.00", "close_of_escrow": "2026-08-11T00:00:00"}
    assert find_field_conflicts(existing, incoming) == []


def test_flags_changed_close_date_and_price():
    existing = {"close_of_escrow": "2026-08-11", "purchase_price": "$450,000"}
    incoming = {"close_of_escrow": "2026-08-20", "purchase_price": "$460,000"}
    assert {c[0] for c in find_field_conflicts(existing, incoming)} == {"close_of_escrow", "purchase_price"}


def test_ignores_nonmaterial_and_missing_fields():
    existing = {"buyer_names": "Alice", "close_of_escrow": "2026-08-11"}
    incoming = {"buyer_names": "Bob"}  # not material; and close_of_escrow absent from incoming
    assert find_field_conflicts(existing, incoming) == []


# ---- through the repo ------------------------------------------------------

def _pa(txn_id: str, close: str, confirmed: bool) -> Payload:
    return Payload(
        document_id=str(uuid.uuid4()),
        transaction_id=txn_id,
        document_type="purchase_agreement",
        document_storage_ref="ref/pa.pdf",
        extracted_fields=[
            ExtractedField(name="close_of_escrow", value=close, confidence=0.95, confirmed=confirmed),
        ],
    )


def test_reupload_with_changed_date_raises_inconsistency_flag():
    repo = InMemoryRepo()
    txn = repo.create_transaction(property_address="1 A St", actor="tc")["id"]
    # First PA, confirmed.
    repo.write_payload(transaction_id=txn, payload=_pa(txn, "2026-08-11", confirmed=True), actor="tc")
    # Amended PA with a different close date.
    repo.write_payload(transaction_id=txn, payload=_pa(txn, "2026-08-20", confirmed=False), actor="tc")

    flags = [f for f in repo.risk_flags if f["case_key"] == "document_inconsistency"]
    assert len(flags) == 1
    assert flags[0]["severity"] == "critical"
    assert "2026-08-20" in flags[0]["description"] and "2026-08-11" in flags[0]["description"]


def test_reupload_same_date_no_flag():
    repo = InMemoryRepo()
    txn = repo.create_transaction(property_address="1 A St", actor="tc")["id"]
    repo.write_payload(transaction_id=txn, payload=_pa(txn, "2026-08-11", confirmed=True), actor="tc")
    repo.write_payload(transaction_id=txn, payload=_pa(txn, "2026-08-11", confirmed=False), actor="tc")
    assert not any(f["case_key"] == "document_inconsistency" for f in repo.risk_flags)
