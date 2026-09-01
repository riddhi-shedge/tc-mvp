"""'Other' documents keep a human-readable name (TC audit finding 5): the TC's
words, or Terra's stored content-level guess — never a wall of bare "Other"
cards. Typed documents never carry a label (the type IS the name)."""

import base64
from pathlib import Path

PDF_B64 = base64.b64encode(
    (Path(__file__).parent / "fixtures" / "synthetic_pof.pdf").read_bytes()
).decode()


def _upload(client, tc_headers, filename="mystery-form.pdf"):
    return client.post(
        "/ingestion/manual-upload",
        json={"filename": filename, "content_base64": PDF_B64},
        headers=tc_headers,
    ).json()


def _confirm(client, tc_headers, item_id, txn_id, **extra):
    return client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json={"decision": txn_id, **extra},
        headers=tc_headers,
    )


def test_tc_label_lands_on_other_document(client, tc_headers, repo):
    txn_id = client.post(
        "/transactions", json={"property_address": "1 Label Ln"}, headers=tc_headers
    ).json()["id"]
    item = _upload(client, tc_headers)
    r = _confirm(
        client, tc_headers, item["id"], txn_id, doc_type="other", label="FHA Amendatory Clause"
    )
    assert r.status_code == 200
    docs = repo.get_full_state(txn_id)["documents"]
    assert docs[0]["doc_type"] == "other"
    assert docs[0]["label"] == "FHA Amendatory Clause"


def test_label_defaults_to_terras_stored_guess(client, tc_headers, extractor, repo):
    extractor.doc_looks_like = "other"
    extractor.doc_guess = "HOA CC&Rs package"
    txn_id = client.post(
        "/transactions", json={"property_address": "3 Label Ln"}, headers=tc_headers
    ).json()["id"]
    item = _upload(client, tc_headers, filename="mystery-form-2.pdf")
    client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    r = _confirm(client, tc_headers, item["id"], txn_id, doc_type="other")
    assert r.status_code == 200
    docs = repo.get_full_state(txn_id)["documents"]
    assert docs[0]["label"] == "HOA CC&Rs package"


def test_typed_documents_never_carry_a_label(client, tc_headers, repo):
    txn_id = client.post(
        "/transactions", json={"property_address": "5 Label Ln"}, headers=tc_headers
    ).json()["id"]
    item = _upload(client, tc_headers, filename="mystery-form-3.pdf")
    r = _confirm(
        client, tc_headers, item["id"], txn_id, doc_type="proof_of_funds", label="ignored"
    )
    assert r.status_code == 200
    docs = repo.get_full_state(txn_id)["documents"]
    assert docs[0]["doc_type"] == "proof_of_funds"
    assert docs[0]["label"] is None
