"""Extraction-review confirm: the TC marks extracted fields confirmed.
(The hard deadline-driving gate arrives in Phase 4; Phase 2 needs the action.)"""


def _txn_with_fields(client, tc_headers) -> tuple[str, list[str]]:
    txn_id = client.post(
        "/transactions", json={"property_address": "742 Synthetic Ave"}, headers=tc_headers
    ).json()["id"]
    client.post(
        f"/transactions/{txn_id}/payloads",
        json={
            "document_id": "synthetic-doc-1",
            "transaction_id": txn_id,
            "extracted_fields": [
                {"name": "close_of_escrow", "value": "2026-08-15", "confidence": 0.92},
                {"name": "purchase_price", "value": "850000", "confidence": 0.99},
            ],
        },
        headers=tc_headers,
    )
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    return txn_id, [f["id"] for f in state["extracted_fields"]]


def test_confirm_fields_sets_confirmed(client, tc_headers):
    txn_id, field_ids = _txn_with_fields(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/fields/confirm",
        json={"field_ids": field_ids},
        headers=tc_headers,
    )
    assert r.status_code == 200
    assert r.json()["confirmed"] == 2
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert all(f["confirmed"] is True for f in state["extracted_fields"])


def test_confirm_fields_writes_audit_row(client, tc_headers, repo):
    txn_id, field_ids = _txn_with_fields(client, tc_headers)
    client.post(
        f"/transactions/{txn_id}/fields/confirm",
        json={"field_ids": field_ids},
        headers=tc_headers,
    )
    row = next(a for a in repo.audit_log if a["action"] == "field.confirmed")
    assert row["actor"] == "tc@example.test"
    assert row["details"]["count"] == 2


def test_confirm_fields_unknown_transaction_is_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/fields/confirm",
        json={"field_ids": ["any"]},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_confirm_unknown_field_ids_confirms_nothing(client, tc_headers):
    txn_id, _ = _txn_with_fields(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/fields/confirm",
        json={"field_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=tc_headers,
    )
    assert r.status_code == 200
    assert r.json()["confirmed"] == 0
