"""Missing-deadline-field flow (TC UX): a real deal whose extraction missed a
deadline-driving field can be completed in the app — the timeline gate reports
exactly what's outstanding, the TC hand-enters the missing values (whitelisted
to §5, Rule 2 money-guarded), and once ready the timeline can be built. No script.
"""

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

WEBHOOK_URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"


def _deal(client, tc_headers) -> str:
    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    return client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]


def _deal_missing(client, tc_headers, extractor, drop: str) -> str:
    """A deal whose extraction omitted one deadline-driving field entirely."""
    extractor.fields = [f for f in extractor.fields if f.name != drop]
    return _deal(client, tc_headers)


def test_timeline_gate_names_unconfirmed_then_clears(client, tc_headers):
    """A freshly ingested deal reports every deadline-driving field as unconfirmed
    (nothing missing); confirming them flips the gate to ready."""
    txn_id = _deal(client, tc_headers)
    gate = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()["timeline_gate"]
    assert gate["ready"] is False
    assert gate["missing_fields"] == []
    assert "acceptance_date" in gate["unconfirmed_fields"]

    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    dd_ids = [f["id"] for f in state["extracted_fields"] if f["deadline_driving"]]
    client.post(
        f"/transactions/{txn_id}/fields/confirm", json={"field_ids": dd_ids}, headers=tc_headers
    )
    gate = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()["timeline_gate"]
    assert gate["ready"] is True


def test_gate_reports_a_missing_field(client, tc_headers, extractor):
    txn_id = _deal_missing(client, tc_headers, extractor, drop="acceptance_date")
    gate = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()["timeline_gate"]
    assert gate["missing_fields"] == ["acceptance_date"]
    assert "acceptance_date" not in gate["unconfirmed_fields"]


def test_add_missing_field_lands_confirmed_and_clears_the_gate(client, tc_headers, extractor):
    txn_id = _deal_missing(client, tc_headers, extractor, drop="acceptance_date")

    r = client.post(
        f"/transactions/{txn_id}/fields",
        json={"name": "acceptance_date", "value": "2026-07-10"},
        headers=tc_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["field"]["confirmed"] is True  # hand-entered = confirmed
    assert body["field"]["deadline_driving"] is True
    assert "acceptance_date" not in body["timeline_gate"]["missing_fields"]

    # Confirm the rest → the deal is ready to build.
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    unconfirmed = [f["id"] for f in state["extracted_fields"] if not f["confirmed"]]
    client.post(
        f"/transactions/{txn_id}/fields/confirm", json={"field_ids": unconfirmed}, headers=tc_headers
    )
    gate = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()["timeline_gate"]
    assert gate["ready"] is True


def test_add_field_rejects_non_s5_name(client, tc_headers):
    txn_id = _deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/fields",
        json={"name": "wire_instructions", "value": "whatever"},
        headers=tc_headers,
    )
    assert r.status_code == 422


def test_add_field_money_guard_on_value(client, tc_headers):
    """Rule 2: a value carrying wiring/account language is refused even for a
    legitimate §5 field name."""
    txn_id = _deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/fields",
        json={"name": "escrow_holder", "value": "wire to account 12345678"},
        headers=tc_headers,
    )
    assert r.status_code == 422


def test_add_field_rejects_duplicate(client, tc_headers):
    txn_id = _deal(client, tc_headers)  # acceptance_date already extracted
    r = client.post(
        f"/transactions/{txn_id}/fields",
        json={"name": "acceptance_date", "value": "2026-07-10"},
        headers=tc_headers,
    )
    assert r.status_code == 409


def test_add_field_needs_a_document(client, tc_headers):
    """A bare deal (no ingested payload) has nothing to attach a field to."""
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Empty Ct (synthetic)"}, headers=tc_headers
    ).json()["id"]
    r = client.post(
        f"/transactions/{txn_id}/fields",
        json={"name": "acceptance_date", "value": "2026-07-10"},
        headers=tc_headers,
    )
    assert r.status_code == 409


def test_add_field_requires_tc_auth(client):
    r = client.post(
        "/transactions/whatever/fields", json={"name": "acceptance_date", "value": "x"}
    )
    assert r.status_code in (401, 403)


def test_build_timeline_blocked_until_ready(client, tc_headers, extractor):
    """Build-timeline refuses (409) while deadline fields are outstanding, and the
    error names what's blocking — no compliance subprocess is spawned."""
    txn_id = _deal_missing(client, tc_headers, extractor, drop="acceptance_date")
    r = client.post(f"/transactions/{txn_id}/build-timeline", headers=tc_headers)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["missing_fields"] == ["acceptance_date"]
    assert "acceptance_date" not in detail["unconfirmed_fields"]


def test_build_timeline_unknown_deal_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/build-timeline", headers=tc_headers
    )
    assert r.status_code == 404
