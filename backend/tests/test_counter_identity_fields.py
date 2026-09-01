"""A counter offer changes TERMS, never identities (live bug, deal 39ec2f4c):
the SCO form lists the countering seller first, which flipped the model's
buyer/seller name reads — and counter fields land auto-confirmed, so the swap
superseded the PA's correct names and spawned inverted buyer/seller parties.
Identity fields extracted from a counter are now dropped at ingestion."""

import base64
from pathlib import Path

from app.contracts.payload import ExtractedField

# A real (synthetic) PDF with a text layer so the §4 precheck passes.
COUNTER_B64 = base64.b64encode(
    (Path(__file__).parent / "fixtures" / "synthetic_pof.pdf").read_bytes()
).decode()


def _confirm_counter(client, tc_headers, txn_id):
    item = client.post(
        "/ingestion/manual-upload",
        json={
            "filename": "sco-synthetic.pdf",
            "content_base64": COUNTER_B64,
            "doc_type": "seller_counter_offer",
        },
        headers=tc_headers,
    ).json()
    return client.post(
        f"/ingestion/inbox/{item['id']}/confirm", json={"decision": txn_id}, headers=tc_headers
    )


def test_counter_never_overrides_identity_fields(client, tc_headers, extractor, repo):
    # The model (mis)reads the counter as swapping who buys and who sells.
    extractor.fields = [
        ExtractedField(name="buyer_names", value="Sally Seller", confidence=0.9),
        ExtractedField(name="seller_names", value="Barry Buyer", confidence=0.9),
        ExtractedField(name="property_address", value="999 Wrong Rd", confidence=0.9),
        ExtractedField(name="purchase_price", value="$905,000", confidence=0.95),
    ]
    txn_id = client.post(
        "/transactions", json={"property_address": "12 Counter Ct"}, headers=tc_headers
    ).json()["id"]
    r = _confirm_counter(client, tc_headers, txn_id)
    assert r.status_code == 200

    state = repo.get_full_state(txn_id)
    names = {f["name"] for f in state["extracted_fields"]}
    assert "purchase_price" in names  # the changed term DID land (and supersedes)
    assert "buyer_names" not in names
    assert "seller_names" not in names
    assert "property_address" not in names
    # …so no inverted buyer/seller parties were derived from the counter.
    roles = {(p["role"], p["name"]) for p in state["parties"]}
    assert ("buyer", "Sally Seller") not in roles
    assert ("seller", "Barry Buyer") not in roles
