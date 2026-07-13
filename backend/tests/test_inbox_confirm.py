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
