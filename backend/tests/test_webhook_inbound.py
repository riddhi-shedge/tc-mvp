"""Postmark inbound webhook (part a entry point). Synthetic emails only.

The webhook is gated by a shared token (Postmark can't hold a TC session) and
only ever writes ingestion's own queue — never the SOR. Dedicated-inbox rule:
mail not addressed to the deal address is ignored, not stored.
"""

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"


def test_missing_token_is_401(client):
    r = client.post("/ingestion/webhooks/postmark", json=postmark_inbound())
    assert r.status_code == 401


def test_wrong_token_is_401(client, inbox):
    r = client.post(
        "/ingestion/webhooks/postmark?token=wrong-synthetic-token",
        json=postmark_inbound(),
    )
    assert r.status_code == 401
    assert inbox.items == {}


def test_mail_to_other_address_is_ignored_not_stored(client, inbox):
    """Dedicated inbox only: anything else is dropped (200 so Postmark won't retry)."""
    r = client.post(URL, json=postmark_inbound(to="someone-else@example.test"))
    assert r.status_code == 200
    assert r.json()["ignored"] is True
    assert inbox.items == {}


def test_valid_inbound_stores_pending_item(client, inbox):
    r = client.post(URL, json=postmark_inbound())
    assert r.status_code == 200
    body = r.json()
    assert body["ignored"] is False
    item = inbox.items[body["id"]]
    assert item["status"] == "pending"
    assert item["from_email"] == "listing-agent@example.test"
    assert item["subject"] == "Signed RPA — 123 Stub St (synthetic)"
    assert item["attachment_name"] == "synthetic-signed-rpa.pdf"
    assert item["attachment_content_type"] == "application/pdf"
    assert item["attachment_size"] == 4321


def test_attachment_content_is_never_stored(client, inbox):
    """Phase 2 stores attachment METADATA only — no document content anywhere."""
    r = client.post(URL, json=postmark_inbound())
    item = inbox.items[r.json()["id"]]
    for value in item.values():
        assert value != "JVBERi1zeW50aGV0aWM="
    assert "content" not in {k.lower() for k in item} - {"attachment_content_type"}


def test_token_accepted_via_header(client, inbox):
    """Header is the preferred channel (query strings can land in proxy logs)."""
    r = client.post(
        "/ingestion/webhooks/postmark",
        json=postmark_inbound(),
        headers={"X-Webhook-Token": WEBHOOK_TOKEN},
    )
    assert r.status_code == 200
    assert r.json()["ignored"] is False


def test_attachment_count_recorded(client, inbox):
    body = postmark_inbound()
    body["Attachments"].append(
        {"Name": "second-synthetic.pdf", "ContentType": "application/pdf", "ContentLength": 10}
    )
    r = client.post(URL, json=body)
    item = inbox.items[r.json()["id"]]
    # Only the first attachment's metadata is captured in Phase 2; the count
    # marks that more existed rather than dropping them silently.
    assert item["attachment_count"] == 2
    assert item["attachment_name"] == "synthetic-signed-rpa.pdf"


def test_webhook_never_touches_the_master(client, inbox, repo):
    """Nothing commits to the SOR from mail arrival alone (HITL comes later)."""
    client.post(URL, json=postmark_inbound())
    assert repo.transactions == {}
    assert repo.audit_log == []
