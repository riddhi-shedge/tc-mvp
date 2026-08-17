"""HITL confirmation: the TC decides "new deal or which existing?" — nothing
commits to the SOR before this step (rules/security.md)."""

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

WEBHOOK_URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"


def _inbound_item(client) -> str:
    return client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]


def test_inbox_list_requires_auth(client):
    assert client.get("/ingestion/inbox").status_code == 401


def test_inbox_lists_pending_items(client, tc_headers):
    item_id = _inbound_item(client)
    r = client.get("/ingestion/inbox", headers=tc_headers)
    assert r.status_code == 200
    assert [i["id"] for i in r.json()] == [item_id]


def test_duplicate_postmark_delivery_is_idempotent(client, tc_headers):
    """BUG-10: Postmark inbound is at-least-once; a redelivered webhook must return
    the EXISTING queue item, not spawn a second identical one the TC could confirm
    into a duplicate deal."""
    body = postmark_inbound()
    first = client.post(WEBHOOK_URL, json=body).json()
    second = client.post(WEBHOOK_URL, json=body).json()

    assert second["id"] == first["id"]
    assert second.get("duplicate") is True
    open_items = client.get("/ingestion/inbox", headers=tc_headers).json()
    assert [i["id"] for i in open_items] == [first["id"]]


def test_a_distinct_email_is_not_deduped(client, tc_headers):
    """The dedup must be tight: a genuinely different document (different filename)
    from the same sender still gets its own queue item."""
    first = client.post(WEBHOOK_URL, json=postmark_inbound()).json()
    other = client.post(
        WEBHOOK_URL, json=postmark_inbound(attachment_name="second-doc.pdf")
    ).json()
    assert other["id"] != first["id"]
    assert other.get("duplicate") is not True
    open_ids = {i["id"] for i in client.get("/ingestion/inbox", headers=tc_headers).json()}
    assert open_ids == {first["id"], other["id"]}


def test_dedup_key_is_content_addressed_so_distinct_docs_never_collide():
    """The safety invariant behind the dedup: DIFFERENT bytes hash to a DIFFERENT
    path, so a genuinely different document is never absorbed as a duplicate (no
    silent data loss) — while identical bytes are deterministic (a true redelivery
    always matches). This is what makes the storage-path match safe."""
    from app.ingestion.inbox_repo import content_addressed_path

    p_a = content_addressed_path("email", "doc.pdf", b"document-A-bytes")
    p_b = content_addressed_path("email", "doc.pdf", b"document-B-bytes")
    assert p_a != p_b
    assert content_addressed_path("email", "doc.pdf", b"document-A-bytes") == p_a


def test_confirm_requires_auth(client):
    item_id = _inbound_item(client)
    r = client.post(f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"})
    assert r.status_code == 401


def test_confirm_unknown_item_is_404(client, tc_headers):
    r = client.post(
        "/ingestion/inbox/00000000-0000-0000-0000-000000000000/confirm",
        json={"decision": "new"},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_nothing_commits_before_confirm(client, tc_headers, repo):
    _inbound_item(client)
    assert repo.transactions == {}
    assert repo.payloads == {}


def test_confirm_new_creates_transaction_with_stub_payload(client, tc_headers, repo, inbox):
    item_id = _inbound_item(client)
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert r.status_code == 200
    txn_id = r.json()["transaction_id"]

    assert len(repo.transactions) == 1
    state = repo.get_full_state(txn_id)
    assert len(state["payloads"]) == 1
    assert state["documents"][0]["external_ref"] == f"inbox-{item_id}"
    fields = state["extracted_fields"]
    assert len(fields) >= 4  # stub §5-candidate fields
    assert all(0.0 <= f["confidence"] <= 1.0 for f in fields)
    assert all(f["confirmed"] is False for f in fields)

    actions = [a["action"] for a in state["audit_log"]]
    assert "transaction.created" in actions and "payload.written" in actions

    item = inbox.items[item_id]
    assert item["status"] == "confirmed"
    assert item["confirmed_transaction_id"] == txn_id


def test_confirm_existing_attaches_payload_without_new_transaction(client, tc_headers, repo):
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]
    item_id = _inbound_item(client)

    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": txn_id}, headers=tc_headers
    )
    assert r.status_code == 200
    assert r.json()["transaction_id"] == txn_id
    assert len(repo.transactions) == 1
    assert len(repo.get_full_state(txn_id)["payloads"]) == 1


def test_confirm_with_unknown_transaction_is_404_and_item_stays_pending(client, tc_headers, inbox):
    item_id = _inbound_item(client)
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json={"decision": "00000000-0000-0000-0000-000000000000"},
        headers=tc_headers,
    )
    assert r.status_code == 404
    assert inbox.items[item_id]["status"] == "pending"


def test_payload_failure_after_create_points_tc_at_orphan_transaction(
    client, tc_headers, repo, inbox
):
    """If create succeeds but the payload write fails, the error names the
    created transaction so a retry attaches instead of duplicating the deal."""
    from app.ingestion.routes import get_master_client
    from app.main import app
    from tests.fake_inbox import FakeMasterClient

    class FailingWriteClient(FakeMasterClient):
        def write_payload(self, *, token, transaction_id, payload):
            return 502, {"detail": "synthetic master outage"}

    app.dependency_overrides[get_master_client] = lambda: FailingWriteClient(repo)
    item_id = _inbound_item(client)
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert r.status_code == 502
    created_id = next(iter(repo.transactions))
    assert created_id in r.json()["detail"]
    assert inbox.items[item_id]["status"] == "pending"

    # Retry per the error message: attach to the created transaction.
    app.dependency_overrides[get_master_client] = lambda: FakeMasterClient(repo)
    r2 = client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json={"decision": created_id},
        headers=tc_headers,
    )
    assert r2.status_code == 200
    assert r2.json()["transaction_id"] == created_id
    assert len(repo.transactions) == 1


def test_confirm_with_doc_type_override(client, tc_headers, repo):
    """The TC corrects an 'unknown' detection at confirm time (never guessed)."""
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]
    body = postmark_inbound(subject="Documents (synthetic)", attachment_name="scan001.pdf")
    item_id = client.post(WEBHOOK_URL, json=body).json()["id"]

    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json={"decision": txn_id, "doc_type": "disclosure"},
        headers=tc_headers,
    )
    assert r.status_code == 200
    doc = repo.get_full_state(txn_id)["documents"][0]
    assert doc["doc_type"] == "disclosure"


def test_non_pa_payload_carries_no_stub_fields(client, tc_headers, repo):
    """§5 fields come from a purchase agreement; other docs attach field-less
    until Phase 4's real extraction."""
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]
    item_id = client.post(
        WEBHOOK_URL,
        json=postmark_inbound(
            subject="Proof of funds (synthetic)", attachment_name="pof-synthetic.pdf"
        ),
    ).json()["id"]
    client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": txn_id}, headers=tc_headers
    )
    state = repo.get_full_state(txn_id)
    assert state["extracted_fields"] == []
    assert state["documents"][0]["doc_type"] == "proof_of_funds"


def test_confirm_unknown_without_doc_type_is_422(client, tc_headers, repo):
    """Never guess: an unclassified document can't enter the SOR."""
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]
    body = postmark_inbound(subject="Documents (synthetic)", attachment_name="scan001.pdf")
    item_id = client.post(WEBHOOK_URL, json=body).json()["id"]
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": txn_id}, headers=tc_headers
    )
    assert r.status_code == 422
    assert "doc_type" in r.json()["detail"]
    assert repo.payloads == {}


def test_confirm_with_invalid_doc_type_is_422(client, tc_headers):
    item_id = _inbound_item(client)
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json={"decision": "new", "doc_type": "totally-made-up"},
        headers=tc_headers,
    )
    assert r.status_code == 422


def test_failed_confirm_releases_the_claim(client, tc_headers, repo, inbox):
    """After a master failure mid-confirm the item is back to 'pending' —
    claimed during the attempt, released on failure, retryable by the TC."""
    from app.ingestion.routes import get_master_client
    from app.main import app
    from tests.fake_inbox import FakeMasterClient

    class FailingCreateClient(FakeMasterClient):
        def create_transaction(self, *, token, property_address):
            return 502, {"detail": "synthetic master outage"}

    app.dependency_overrides[get_master_client] = lambda: FailingCreateClient(repo)
    item_id = _inbound_item(client)
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert r.status_code == 502
    assert inbox.items[item_id]["status"] == "pending"

    app.dependency_overrides[get_master_client] = lambda: FakeMasterClient(repo)
    assert (
        client.post(
            f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
        ).status_code
        == 200
    )


def test_processing_item_cannot_be_confirmed_again(client, tc_headers, inbox):
    """A claimed (in-flight) item rejects a concurrent confirm."""
    item_id = _inbound_item(client)
    assert inbox.claim(item_id) is not None
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert r.status_code == 409
    assert "processed" in r.json()["detail"]


def test_dismiss_closes_pending_item(client, tc_headers, inbox):
    item_id = _inbound_item(client)
    assert client.post(f"/ingestion/inbox/{item_id}/dismiss", headers=tc_headers).status_code == 200
    assert inbox.items[item_id]["status"] == "ignored"
    # And it can't be dismissed or confirmed again.
    assert client.post(f"/ingestion/inbox/{item_id}/dismiss", headers=tc_headers).status_code == 409
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert r.status_code == 409


def test_double_confirm_is_409(client, tc_headers):
    item_id = _inbound_item(client)
    first = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert first.status_code == 200
    second = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    )
    assert second.status_code == 409
