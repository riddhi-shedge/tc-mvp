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


def test_counter_contact_fields_land_unconfirmed(client, tc_headers, extractor, repo):
    """Terms auto-confirm from a counter; contact info must NOT — a low-
    confidence phone read off a counter would otherwise supersede the PA's
    value via the latest-confirmed rule (TC audit finding 9)."""
    extractor.fields = [
        ExtractedField(name="purchase_price", value="$910,000", confidence=0.95),
        ExtractedField(name="close_of_escrow", value="30 days after acceptance", confidence=0.9),
        ExtractedField(name="buyer_agent_phone", value="5550000000", confidence=0.5),
        ExtractedField(name="listing_agent", value="Lana Lister", confidence=0.6),
    ]
    txn_id = client.post(
        "/transactions", json={"property_address": "14 Counter Ct"}, headers=tc_headers
    ).json()["id"]
    r = _confirm_counter(client, tc_headers, txn_id)
    assert r.status_code == 200
    by_name = {f["name"]: f for f in repo.get_full_state(txn_id)["extracted_fields"]}
    assert by_name["purchase_price"]["confirmed"] is True
    assert by_name["close_of_escrow"]["confirmed"] is True
    assert by_name["buyer_agent_phone"]["confirmed"] is False
    assert by_name["listing_agent"]["confirmed"] is False


def test_pa_supersession_is_audited(repo, client, tc_headers, extractor):
    """Replacing the PA deletes the older document (one PA per deal) — that
    removal must appear in the audit chain (TC audit finding 4: a confirmed
    inbox item pointed at a payload that silently no longer existed)."""
    from app.contracts.payload import Payload

    txn_id = client.post(
        "/transactions", json={"property_address": "16 Supersede St"}, headers=tc_headers
    ).json()["id"]
    for doc_id in ("pa-old", "pa-new"):
        repo.write_payload(
            transaction_id=txn_id,
            payload=Payload(
                document_id=doc_id,
                transaction_id=txn_id,
                extracted_fields=[],
                document_type="purchase_agreement",
            ),
            actor="tc",
        )
    state = repo.get_full_state(txn_id)
    refs = {d["external_ref"] for d in state["documents"]}
    assert refs == {"pa-new"}  # old PA removed
    superseded = [e for e in state["audit_log"] if e["action"] == "document.superseded"]
    assert len(superseded) == 1
    assert superseded[0]["details"]["external_ref"] == "pa-old"
