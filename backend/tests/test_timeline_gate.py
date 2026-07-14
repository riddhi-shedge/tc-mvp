"""The confirmation gate (Prompt 4 done-when): proceeding with an unconfirmed
deadline-driving field is BLOCKED with an explanation. No unconfirmed deadline
field may ever create a task."""

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

WEBHOOK_URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"


def _deal_with_extracted_fields(client, tc_headers) -> str:
    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    return client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]


def test_timeline_blocked_while_deadline_fields_unconfirmed(client, tc_headers, repo):
    txn_id = _deal_with_extracted_fields(client, tc_headers)
    r = client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "BLOCKED" in detail
    # The explanation names the offending fields (names only, never values).
    for name in ("acceptance_date", "close_of_escrow"):
        assert name in detail
    # And no task was created.
    state = repo.get_full_state(txn_id)
    assert state["deadlines"] == [] and state["tasks"] == []


def test_confirming_only_non_deadline_fields_keeps_the_block(client, tc_headers, repo):
    txn_id = _deal_with_extracted_fields(client, tc_headers)
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    non_dd = [f["id"] for f in state["extracted_fields"] if not f["deadline_driving"]]
    client.post(
        f"/transactions/{txn_id}/fields/confirm", json={"field_ids": non_dd}, headers=tc_headers
    )
    assert (
        client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers).status_code == 409
    )


def test_confirming_deadline_fields_unlocks_the_timeline(client, tc_headers):
    txn_id = _deal_with_extracted_fields(client, tc_headers)
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    dd_ids = [f["id"] for f in state["extracted_fields"] if f["deadline_driving"]]
    client.post(
        f"/transactions/{txn_id}/fields/confirm", json={"field_ids": dd_ids}, headers=tc_headers
    )
    # Non-deadline fields may stay unconfirmed — they don't gate the timeline.
    r = client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers)
    assert r.status_code == 201


def test_missing_deadline_field_blocks_even_with_no_unconfirmed_rows(client, tc_headers, extractor):
    """An OMITTED deadline-driving field is not a confirmed field: coverage is
    required, not just row-level confirmation."""
    from app.contracts.payload import ExtractedField

    # Extractor returns everything except insurance_contingency_days.
    extractor.fields = [f for f in extractor.fields if f.name != "insurance_contingency_days"] + [
        ExtractedField(name="apn", value="000-000-000", confidence=0.9)
    ]
    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    txn_id = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]

    # Confirm every row that exists — the missing name still blocks.
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    all_ids = [f["id"] for f in state["extracted_fields"]]
    client.post(
        f"/transactions/{txn_id}/fields/confirm", json={"field_ids": all_ids}, headers=tc_headers
    )
    r = client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers)
    assert r.status_code == 409
    assert "insurance_contingency_days" in r.json()["detail"]


def test_full_manual_entry_satisfies_the_gate(client, tc_headers):
    """Manual entries arrive confirmed; covering every deadline-driving field
    manually satisfies the gate (partial coverage does not — see below)."""
    from app.contracts.fields import DEADLINE_DRIVING

    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    manual = [{"name": "property_address", "value": "9 Manual Ct (synthetic)"}] + [
        {"name": name, "value": "synthetic-value"} for name in sorted(DEADLINE_DRIVING)
    ]
    txn_id = client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json={"decision": "new", "manual_fields": manual},
        headers=tc_headers,
    ).json()["transaction_id"]
    assert (
        client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers).status_code == 201
    )


def test_partial_manual_entry_blocks_on_missing_names(client, tc_headers):
    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    txn_id = client.post(
        f"/ingestion/inbox/{item_id}/confirm",
        json={
            "decision": "new",
            "manual_fields": [
                {"name": "property_address", "value": "9 Manual Ct (synthetic)"},
                {"name": "close_of_escrow", "value": "2026-09-01"},
            ],
        },
        headers=tc_headers,
    ).json()["transaction_id"]
    r = client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers)
    assert r.status_code == 409
    assert "not yet extracted" in r.json()["detail"]
    assert "emd_due_days" in r.json()["detail"]
