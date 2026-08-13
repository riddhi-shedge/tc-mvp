"""Property & termite inspection reports (new-docs pipeline).

Each creates the inspector party (general inspector / pest company) and is
validated against the deal: the inspected address matches the property, and the
inspection is recent.
"""

from __future__ import annotations

from datetime import date

from app.contracts.payload import ExtractedField, InspectionMeta, PartyRef, Payload
from app.master.repo import evaluate_inspection_flags
from tests.fake_repo import InMemoryRepo


def _cases(flags) -> set[str]:
    return {f["case_key"] for f in flags}


def test_address_match_ignores_suffix_and_city():
    meta = InspectionMeta(property_address="21989 McClellan Rd", inspection_date="April 20, 2025")
    assert evaluate_inspection_flags(meta, "21989 McClellan Road, Cupertino, CA", date(2025, 4, 28)) == []


def test_address_mismatch_flags():
    flags = evaluate_inspection_flags(InspectionMeta(property_address="1 Other St"), "21989 McClellan Road", None)
    assert "inspection_address_mismatch" in _cases(flags)


def test_stale_inspection_flags():
    flags = evaluate_inspection_flags(InspectionMeta(inspection_date="01/01/2025"), None, date(2025, 4, 28))
    assert "inspection_stale" in _cases(flags)


def test_recent_inspection_is_not_stale():
    flags = evaluate_inspection_flags(InspectionMeta(inspection_date="04/20/2025"), None, date(2025, 4, 28))
    assert "inspection_stale" not in _cases(flags)


def _pa(repo: InMemoryRepo, tid: str, address: str) -> None:
    repo.write_payload(
        transaction_id=tid,
        payload=Payload(
            document_id="pa", transaction_id=tid, document_type="purchase_agreement",
            extracted_fields=[
                ExtractedField(name="property_address", value=address, confidence=1.0, confirmed=True),
                ExtractedField(name="acceptance_date", value="April 28, 2025", confidence=1.0, confirmed=True),
            ],
        ),
        actor="tc",
    )


def test_inspection_creates_inspector_party_and_no_flag_when_matching():
    repo = InMemoryRepo()
    tid = repo.create_transaction(property_address="21989 McClellan Rd", actor="tc")["id"]
    _pa(repo, tid, "21989 McClellan Road")
    repo.write_payload(
        transaction_id=tid,
        payload=Payload(
            document_id="ti", transaction_id=tid, document_type="termite_inspection",
            inspection_meta=InspectionMeta(property_address="21989 McClellan Rd", inspection_date="April 20, 2025"),
            parties=[PartyRef(role="inspector_termite", name="BayArea Pest Control", company="BayArea Pest Control")],
        ),
        actor="tc",
    )
    state = repo.get_full_state(tid)
    assert "inspector_termite" in {p["role"] for p in state["parties"]}
    assert not any(r["case_key"].startswith("inspection_") for r in state["risk_flags"])


def test_inspection_wrong_address_flags_via_write_payload():
    repo = InMemoryRepo()
    tid = repo.create_transaction(property_address="21989 McClellan Rd", actor="tc")["id"]
    _pa(repo, tid, "21989 McClellan Road")
    repo.write_payload(
        transaction_id=tid,
        payload=Payload(
            document_id="pi", transaction_id=tid, document_type="property_inspection",
            inspection_meta=InspectionMeta(property_address="500 Elsewhere Ave"),
            parties=[PartyRef(role="inspector_general", name="Home Inspect Co")],
        ),
        actor="tc",
    )
    state = repo.get_full_state(tid)
    assert "inspector_general" in {p["role"] for p in state["parties"]}
    assert any(r["case_key"] == "inspection_address_mismatch" for r in state["risk_flags"])
