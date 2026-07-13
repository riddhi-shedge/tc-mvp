"""Manual-upload fallback (Phase 3): the TC uploads unreadable emails/scans
directly. Same queue, same HITL confirm — the only ingestion entry besides the
dedicated deal address (rules/security.md)."""

import base64

SYNTHETIC_B64 = base64.b64encode(b"PDF-synthetic-manual").decode()


def _upload(client, tc_headers, **overrides):
    body = {
        "filename": "scanned-rpa-synthetic.pdf",
        "content_base64": SYNTHETIC_B64,
        "subject": "Manually uploaded purchase agreement (synthetic)",
    }
    body.update(overrides)
    return client.post("/ingestion/manual-upload", json=body, headers=tc_headers)


def test_manual_upload_requires_auth(client):
    r = client.post(
        "/ingestion/manual-upload",
        json={"filename": "x.pdf", "content_base64": SYNTHETIC_B64},
    )
    assert r.status_code == 401


def test_manual_upload_creates_pending_item_with_stored_file(client, tc_headers, inbox):
    r = _upload(client, tc_headers)
    assert r.status_code == 201
    item = r.json()
    assert item["status"] == "pending"
    assert item["source"] == "manual"
    assert item["detected_doc_type"] == "purchase_agreement"  # from filename/subject
    assert inbox.files[item["storage_path"]] == b"PDF-synthetic-manual"


def test_manual_upload_doc_type_override(client, tc_headers):
    r = _upload(client, tc_headers, filename="scan001.pdf", subject=None, doc_type="disclosure")
    assert r.json()["detected_doc_type"] == "disclosure"


def test_manual_upload_invalid_base64_is_422(client, tc_headers):
    r = _upload(client, tc_headers, content_base64="!!not-base64!!")
    assert r.status_code == 422


def test_manual_upload_rejects_non_pdf(client, tc_headers):
    r = _upload(client, tc_headers, filename="photo.jpg")
    assert r.status_code == 422
    assert "PDF" in r.json()["detail"]


def test_manual_upload_storage_outage_is_503(client, tc_headers, inbox):
    inbox.fail_storage = True
    r = _upload(client, tc_headers)
    assert r.status_code == 503


def test_manual_item_confirms_like_any_other(client, tc_headers, repo):
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]
    item = _upload(
        client, tc_headers, filename="pof-synthetic.pdf", subject=None, doc_type="proof_of_funds"
    ).json()
    r = client.post(
        f"/ingestion/inbox/{item['id']}/confirm", json={"decision": txn_id}, headers=tc_headers
    )
    assert r.status_code == 200
    state = repo.get_full_state(txn_id)
    assert state["documents"][0]["doc_type"] == "proof_of_funds"
    assert state["documents"][0]["storage_path"] == item["storage_path"]
