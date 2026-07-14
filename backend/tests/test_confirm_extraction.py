"""Phase 4 confirm flow: real extraction seam, §4 never-silently-guess error
states, the manual field-entry fallback, and the deadline-driving stamp."""

import base64
from pathlib import Path

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

WEBHOOK_URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"
FIXTURES = Path(__file__).parent / "fixtures"


def _inbound_item(client, **overrides) -> str:
    return client.post(WEBHOOK_URL, json=postmark_inbound(**overrides)).json()["id"]


def _confirm(client, tc_headers, item_id, body=None):
    return client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json=body or {"decision": "new"},
        headers=tc_headers,
    )


def test_extracted_fields_land_unconfirmed_with_confidence(client, tc_headers, repo, extractor):
    item_id = _inbound_item(client)
    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 200
    assert extractor.calls, "the extractor seam must be exercised"

    state = repo.get_full_state(r.json()["transaction_id"])
    fields = state["extracted_fields"]
    assert len(fields) == 12
    assert all(0.0 <= f["confidence"] <= 1.0 for f in fields)
    assert all(f["confirmed"] is False for f in fields)
    # The deadline-driving stamp comes from the verified §5 list.
    stamped = {f["name"]: f["deadline_driving"] for f in fields}
    assert stamped["close_of_escrow"] is True
    assert stamped["acceptance_date"] is True
    assert stamped["purchase_price"] is False
    assert stamped["property_address"] is False
    # Property address flowed into the created deal.
    assert "Stub St" in state["property"]["address"]


def test_bad_scan_routes_everything_to_manual(client, tc_headers, repo, inbox):
    """Prompt 4 done-when: a bad scan routes to manual — nothing is guessed."""
    scan_b64 = base64.standard_b64encode(
        (FIXTURES / "synthetic_scan_no_text.pdf").read_bytes()
    ).decode()
    body = postmark_inbound()
    body["Attachments"][0]["Content"] = scan_b64
    item_id = client.post(WEBHOOK_URL, json=body).json()["id"]

    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["manual_fields_required"] is True
    assert any("text layer" in reason for reason in detail["reasons"])
    assert repo.transactions == {}  # nothing committed
    assert inbox.items[item_id]["status"] == "pending"  # claim released — retryable


def test_truncated_pa_reports_missing_pages(client, tc_headers, repo):
    truncated_b64 = base64.standard_b64encode(
        (FIXTURES / "synthetic_pa_truncated.pdf").read_bytes()
    ).decode()
    body = postmark_inbound()
    body["Attachments"][0]["Content"] = truncated_b64
    item_id = client.post(WEBHOOK_URL, json=body).json()["id"]

    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 422
    assert any("missing pages" in reason for reason in r.json()["detail"]["reasons"])


def test_wrong_doc_type_is_flagged_not_guessed(client, tc_headers, repo, extractor):
    extractor.doc_looks_like = "proof_of_funds"
    item_id = _inbound_item(client)
    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 422
    assert any("proof_of_funds" in reason for reason in r.json()["detail"]["reasons"])
    assert repo.payloads == {}


def test_unsigned_document_is_flagged(client, tc_headers, repo, extractor):
    extractor.signature_detected = False
    item_id = _inbound_item(client)
    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 422
    assert any("signed" in reason for reason in r.json()["detail"]["reasons"])
    assert repo.payloads == {}


def test_extraction_blocked_is_503_and_releases_claim(client, tc_headers, inbox, extractor):
    extractor.raise_blocked = True
    item_id = _inbound_item(client)
    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 503
    assert inbox.items[item_id]["status"] == "pending"


def test_extraction_failure_is_502_and_releases_claim(client, tc_headers, inbox, extractor):
    extractor.raise_failed = True
    item_id = _inbound_item(client)
    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 502
    assert inbox.items[item_id]["status"] == "pending"


def test_manual_fields_enter_confirmed_at_full_confidence(client, tc_headers, repo, extractor):
    """The TC typing the values IS the confirmation (manual fallback)."""
    item_id = _inbound_item(client)
    r = _confirm(
        client,
        tc_headers,
        item_id,
        {
            "decision": "new",
            "manual_fields": [
                {"name": "property_address", "value": "9 Manual Ct, Sacramento CA (synthetic)"},
                {"name": "close_of_escrow", "value": "2026-09-01"},
                {"name": "purchase_price", "value": "700000"},
            ],
        },
    )
    assert r.status_code == 200
    assert extractor.calls == []  # extraction skipped entirely

    state = repo.get_full_state(r.json()["transaction_id"])
    assert state["property"]["address"].startswith("9 Manual Ct")
    fields = {f["name"]: f for f in state["extracted_fields"]}
    assert all(f["confirmed"] is True and f["confidence"] == 1.0 for f in fields.values())
    assert fields["close_of_escrow"]["deadline_driving"] is True
    payload_audit = next(a for a in repo.audit_log if a["action"] == "payload.written")
    assert payload_audit["details"]["fields_confirmed_on_write"] == 3


def test_storage_outage_at_confirm_is_503_and_releases_claim(client, tc_headers, inbox, extractor):
    item_id = _inbound_item(client)
    inbox.fail_storage = True  # download fails, mirroring the webhook semantics
    r = _confirm(client, tc_headers, item_id)
    assert r.status_code == 503
    assert extractor.calls == []
    assert inbox.items[item_id]["status"] == "pending"


def test_manual_fields_rejected_for_non_pa_doc_types(client, tc_headers, repo):
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]
    item_id = _inbound_item(
        client, subject="Proof of funds (synthetic)", attachment_name="pof-synthetic.pdf"
    )
    r = _confirm(
        client,
        tc_headers,
        item_id,
        {
            "decision": txn_id,
            "manual_fields": [{"name": "purchase_price", "value": "700000"}],
        },
    )
    assert r.status_code == 422
    assert "purchase agreements" in r.json()["detail"]
    assert repo.payloads == {}


def test_manual_field_outside_s5_list_is_422(client, tc_headers, repo):
    item_id = _inbound_item(client)
    r = _confirm(
        client,
        tc_headers,
        item_id,
        {
            "decision": "new",
            "manual_fields": [{"name": "wire_routing_number", "value": "synthetic"}],
        },
    )
    assert r.status_code == 422
    assert "§5" in r.json()["detail"]
    assert repo.transactions == {}


def test_non_pa_documents_skip_extraction(client, tc_headers, repo, extractor):
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]
    item_id = _inbound_item(
        client, subject="Proof of funds (synthetic)", attachment_name="pof-synthetic.pdf"
    )
    r = _confirm(client, tc_headers, item_id, {"decision": txn_id})
    assert r.status_code == 200
    assert extractor.calls == []
    assert repo.get_full_state(txn_id)["extracted_fields"] == []
