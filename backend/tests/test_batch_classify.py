"""Content-level labeling for the batch-upload flow: the TC drops many files,
each becomes an inbox item, and /classify asks the model what each one actually
is. Honest when unsure — unrecognized stays 'unknown' so the TC is asked."""

import base64

SYNTHETIC_B64 = base64.b64encode(b"PDF-synthetic-batch").decode()


def _upload_unlabeled(client, tc_headers, filename="scan001.pdf"):
    """A file whose name/subject give the heuristic nothing → detected unknown.
    Bytes are derived from the filename so two 'versions' never collide with the
    exact-duplicate (same-digest) check."""
    r = client.post(
        "/ingestion/manual-upload",
        json={
            "filename": filename,
            "content_base64": base64.b64encode(f"PDF-synthetic-{filename}".encode()).decode(),
        },
        headers=tc_headers,
    )
    assert r.status_code == 201
    item = r.json()
    assert item["detected_doc_type"] == "unknown"
    return item


def test_classify_requires_auth(client):
    assert client.post("/ingestion/inbox/nope/classify").status_code == 401


def test_classify_unknown_item_is_404(client, tc_headers):
    r = client.post("/ingestion/inbox/nope/classify", headers=tc_headers)
    assert r.status_code == 404


def test_classify_labels_from_content(client, tc_headers, extractor):
    extractor.doc_looks_like = "disclosure"
    item = _upload_unlabeled(client, tc_headers)
    r = client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    assert r.status_code == 200
    assert r.json() == {
        "item_id": item["id"],
        "doc_type": "disclosure",
        "identified": True,
        "guess": "",
        "signals": {"signed": True, "subject_to_counter_offer": False},
    }
    # The label persists — a page refresh still shows it in the queue.
    listed = client.get("/ingestion/inbox", headers=tc_headers).json()
    match = next(i for i in listed if i["id"] == item["id"])
    assert match["detected_doc_type"] == "disclosure"
    assert match["status"] == "pending"


def test_classify_accepts_full_type_vocabulary(client, tc_headers, extractor):
    """The model may answer with ANY known type — a termite report is labeled
    termite_inspection, not collapsed to 'other' (regression: old 5-type list)."""
    extractor.doc_looks_like = "termite_inspection"
    item = _upload_unlabeled(client, tc_headers)
    r = client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    assert r.status_code == 200
    assert r.json()["doc_type"] == "termite_inspection"
    assert r.json()["identified"] is True
    assert r.json()["guess"] == ""


def test_classify_other_carries_best_guess(client, tc_headers, extractor):
    """Outside the known set, Terra still says what it thinks the document is —
    the type stays 'unknown' (the TC decides) but the guess is surfaced+stored."""
    extractor.doc_looks_like = "other"
    extractor.doc_guess = "AVID — Agent Visual Inspection Disclosure"
    item = _upload_unlabeled(client, tc_headers)
    r = client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["identified"] is False
    assert body["doc_type"] == "unknown"
    assert body["guess"] == "AVID — Agent Visual Inspection Disclosure"
    listed = client.get("/ingestion/inbox", headers=tc_headers).json()
    match = next(i for i in listed if i["id"] == item["id"])
    assert match["doc_guess"] == "AVID — Agent Visual Inspection Disclosure"


def test_classify_signals_tell_pa_versions_apart(client, tc_headers, extractor):
    """Two files both reading as purchase agreements: the ratified one shows
    executed signatures, the earlier one doesn't — the signals expose that so
    the batch UI can suggest which is the operative PA."""
    extractor.doc_looks_like = "purchase_agreement"
    extractor.signature_detected = False
    extractor.subject_to_counter_offer = True
    old = _upload_unlabeled(client, tc_headers, filename="scan-old.pdf")
    r_old = client.post(f"/ingestion/inbox/{old['id']}/classify", headers=tc_headers)
    extractor.signature_detected = True
    extractor.subject_to_counter_offer = False
    new = _upload_unlabeled(client, tc_headers, filename="scan-new.pdf")
    r_new = client.post(f"/ingestion/inbox/{new['id']}/classify", headers=tc_headers)
    assert r_old.json()["signals"] == {"signed": False, "subject_to_counter_offer": True}
    assert r_new.json()["signals"] == {"signed": True, "subject_to_counter_offer": False}
    assert r_old.json()["doc_type"] == r_new.json()["doc_type"] == "purchase_agreement"


def test_classify_failure_returns_empty_signals(client, tc_headers, extractor):
    extractor.raise_failed = True
    item = _upload_unlabeled(client, tc_headers)
    r = client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    assert r.status_code == 200
    assert r.json()["signals"] == {}


def test_classify_unrecognized_stays_unknown(client, tc_headers, extractor):
    """The model couldn't tell (or extraction failed) → never guess; the TC is
    asked instead (doc_type stays 'unknown', confirm still 422s without one)."""
    extractor.raise_failed = True
    item = _upload_unlabeled(client, tc_headers)
    r = client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    assert r.status_code == 200
    assert r.json()["identified"] is False
    assert r.json()["doc_type"] == "unknown"
    confirm = client.post(
        f"/ingestion/inbox/{item['id']}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert confirm.status_code == 422  # still asks the human


def test_classify_handled_item_is_409(client, tc_headers, extractor, repo):
    extractor.doc_looks_like = "proof_of_funds"
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Batch Ct"}, headers=tc_headers
    ).json()["id"]
    item = _upload_unlabeled(client, tc_headers)
    client.post(
        f"/ingestion/inbox/{item['id']}/confirm",
        json={"decision": txn_id, "doc_type": "proof_of_funds"},
        headers=tc_headers,
    )
    r = client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    assert r.status_code == 409


def test_confirm_uses_classified_label(client, tc_headers, extractor, repo):
    """After classify, confirm without an explicit doc_type files under the
    model's label — the confirm click is still the TC's HITL decision."""
    extractor.doc_looks_like = "proof_of_funds"
    txn_id = client.post(
        "/transactions", json={"property_address": "11 Batch Ct"}, headers=tc_headers
    ).json()["id"]
    item = _upload_unlabeled(client, tc_headers)
    client.post(f"/ingestion/inbox/{item['id']}/classify", headers=tc_headers)
    r = client.post(
        f"/ingestion/inbox/{item['id']}/confirm", json={"decision": txn_id}, headers=tc_headers
    )
    assert r.status_code == 200
    state = repo.get_full_state(txn_id)
    assert state["documents"][0]["doc_type"] == "proof_of_funds"
