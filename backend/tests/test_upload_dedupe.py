"""Exact-duplicate detection on manual/batch upload: identical bytes are caught
via the content-addressed storage digest — the TC is told, never silently given
two queue items for one document. Revised versions hash differently and are
NEVER treated as duplicates (that's the version-compare flow's job)."""

import base64

B64_A = base64.b64encode(b"PDF-synthetic-dedupe-A").decode()
B64_B = base64.b64encode(b"PDF-synthetic-dedupe-B").decode()


def _upload(client, tc_headers, filename="doc.pdf", content=B64_A, **overrides):
    body = {"filename": filename, "content_base64": content, **overrides}
    return client.post("/ingestion/manual-upload", json=body, headers=tc_headers)


def test_identical_reupload_is_reported_not_requeued(client, tc_headers, inbox):
    first = _upload(client, tc_headers).json()
    r = _upload(client, tc_headers)
    assert r.json()["duplicate_of"]["id"] == first["id"]
    assert len([i for i in inbox.items.values() if i["status"] == "pending"]) == 1


def test_renamed_identical_bytes_still_caught(client, tc_headers, inbox):
    first = _upload(client, tc_headers, filename="original.pdf").json()
    r = _upload(client, tc_headers, filename="renamed-copy.pdf")
    assert r.json()["duplicate_of"]["id"] == first["id"]


def test_different_bytes_never_flagged(client, tc_headers):
    _upload(client, tc_headers, content=B64_A)
    r = _upload(client, tc_headers, filename="doc-v2.pdf", content=B64_B)
    assert "duplicate_of" not in r.json()
    assert r.json()["status"] == "pending"


def test_duplicate_of_filed_document_warns_but_queues(client, tc_headers):
    txn_id = client.post(
        "/transactions", json={"property_address": "5 Dup Ct"}, headers=tc_headers
    ).json()["id"]
    first = _upload(client, tc_headers, doc_type="proof_of_funds").json()
    client.post(
        f"/ingestion/inbox/{first['id']}/confirm", json={"decision": txn_id}, headers=tc_headers
    )
    r = _upload(client, tc_headers)
    body = r.json()
    assert body["status"] == "pending"  # still queued — a re-file can be legit
    assert body["already_filed"]["transaction_id"] == txn_id
    assert body["already_filed"]["item_id"] == first["id"]


def test_dismissed_duplicate_requeues_silently(client, tc_headers):
    first = _upload(client, tc_headers).json()
    client.post(f"/ingestion/inbox/{first['id']}/dismiss", headers=tc_headers)
    r = _upload(client, tc_headers)
    body = r.json()
    assert "duplicate_of" not in body and "already_filed" not in body
    assert body["status"] == "pending"
