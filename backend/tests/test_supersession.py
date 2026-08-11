"""A counter offer supersedes the purchase agreement's terms (Prompt: new-docs).

The latest confirmed value for a field wins, so a seller counter offer's price
overrides the PA's on the board, in the deal's effective_fields (with provenance),
and in the compliance service's confirmed_value — without destroying the PA's
original figure.
"""

from __future__ import annotations

from app.contracts.payload import CounterMeta, ExtractedField, Payload
from app.master.repo import evaluate_counter_flags
from tests.fake_repo import InMemoryRepo


def _price_field(value: str) -> ExtractedField:
    return ExtractedField(name="purchase_price", value=value, confidence=1.0, confirmed=True)


def _write(repo: InMemoryRepo, tid: str, doc_id: str, doc_type: str, value: str) -> None:
    repo.write_payload(
        transaction_id=tid,
        payload=Payload(
            document_id=doc_id,
            transaction_id=tid,
            extracted_fields=[_price_field(value)],
            document_type=doc_type,
        ),
        actor="tc",
    )


def test_counter_offer_supersedes_pa_price():
    repo = InMemoryRepo()
    tid = repo.create_transaction(property_address="21989 McClellan Rd", actor="tc")["id"]

    _write(repo, tid, "pa", "purchase_agreement", "$1,800,000")
    _write(repo, tid, "sco", "seller_counter_offer", "$1,900,000")

    state = repo.get_full_state(tid)
    eff = state["effective_fields"]["purchase_price"]
    assert eff["value"] == "$1,900,000"
    assert eff["superseded_from"] == "$1,800,000"

    # The PA's original figure is preserved (both rows exist) …
    prices = sorted(f["value"] for f in state["extracted_fields"] if f["name"] == "purchase_price")
    assert prices == ["$1,800,000", "$1,900,000"]

    # … but the board shows the effective (counter) price.
    board = {d["id"]: d for d in repo.list_deal_summaries()}
    assert board[tid]["purchase_price"] == "$1,900,000"


def test_no_counter_leaves_pa_value_effective():
    repo = InMemoryRepo()
    tid = repo.create_transaction(property_address="1 Solo St", actor="tc")["id"]
    _write(repo, tid, "pa", "purchase_agreement", "$1,000,000")

    eff = repo.get_full_state(tid)["effective_fields"]["purchase_price"]
    assert eff["value"] == "$1,000,000"
    assert eff["superseded_from"] is None


# ---- counter-offer chain / expiration flags --------------------------------

def test_counter_signed_in_time_raises_no_flags():
    cm = CounterMeta(recipient_signed=True, signed_date="04/28/2025", expiration="04/30/2025")
    assert evaluate_counter_flags("seller_counter_offer", cm) == []


def test_counter_unsigned_flags_fell_through():
    flags = evaluate_counter_flags("seller_counter_offer", CounterMeta(recipient_signed=False))
    assert [f["case_key"] for f in flags] == ["counter_not_accepted"]
    assert flags[0]["severity"] == "critical" and "buyer" in flags[0]["description"]


def test_counter_signed_after_expiration_flags_fell_through():
    cm = CounterMeta(recipient_signed=True, signed_date="05/02/2025", expiration="04/30/2025")
    assert any(f["case_key"] == "counter_not_accepted" for f in evaluate_counter_flags("seller_counter_offer", cm))


def test_buyer_counter_names_the_seller_as_the_accepting_party():
    flags = evaluate_counter_flags("buyer_counter_offer", CounterMeta(recipient_signed=False))
    assert "seller" in flags[0]["description"]


def test_subject_to_further_counter_flags_the_chain():
    cm = CounterMeta(
        recipient_signed=True, signed_date="04/28/2025", expiration="04/30/2025",
        subject_to_further_counter=True,
    )
    flags = evaluate_counter_flags("seller_counter_offer", cm)
    chain = [f for f in flags if f["case_key"] == "counter_chain"]
    assert chain and "buyer counter offer" in chain[0]["description"]


def test_contingency_removal_supersedes_day_field():
    repo = InMemoryRepo()
    tid = repo.create_transaction(property_address="1 CR St", actor="tc")["id"]

    def _f(value: str) -> ExtractedField:
        return ExtractedField(name="inspection_contingency_days", value=value, confidence=1.0, confirmed=True)

    repo.write_payload(
        transaction_id=tid,
        payload=Payload(document_id="pa", transaction_id=tid, extracted_fields=[_f("17")], document_type="purchase_agreement"),
        actor="tc",
    )
    repo.write_payload(
        transaction_id=tid,
        payload=Payload(document_id="cr", transaction_id=tid, extracted_fields=[_f("removed")], document_type="contingency_removal"),
        actor="tc",
    )
    eff = repo.get_full_state(tid)["effective_fields"]["inspection_contingency_days"]
    assert eff["value"] == "removed"
    assert eff["superseded_from"] == "17"


def test_counter_flags_land_via_write_payload():
    repo = InMemoryRepo()
    tid = repo.create_transaction(property_address="1 Chain St", actor="tc")["id"]
    repo.write_payload(
        transaction_id=tid,
        payload=Payload(
            document_id="sco", transaction_id=tid,
            extracted_fields=[_price_field("$1,900,000")],
            document_type="seller_counter_offer",
            counter_meta=CounterMeta(recipient_signed=False),
        ),
        actor="tc",
    )
    cases = {r["case_key"] for r in repo.get_full_state(tid)["risk_flags"]}
    assert "counter_not_accepted" in cases
