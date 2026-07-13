"""The Payload write path — the only way deal data enters the SOR (Prompt 1).

Synthetic payloads only. A NEW payload must not commit anything: transaction
creation is HITL and its ingestion flow arrives in Phase 3.
"""

from app.contracts.payload import NEW_TRANSACTION


def _payload(transaction_id: str, **overrides) -> dict:
    body = {
        "document_id": "synthetic-doc-1",
        "transaction_id": transaction_id,
        "party_id": None,
        "extracted_fields": [
            {"name": "close_of_escrow", "value": "2026-08-15", "confidence": 0.92},
            {"name": "purchase_price", "value": "850000", "confidence": 0.99},
        ],
    }
    body.update(overrides)
    return body


def _create_txn(client, tc_headers) -> str:
    r = client.post(
        "/transactions", json={"property_address": "742 Synthetic Ave"}, headers=tc_headers
    )
    return r.json()["id"]


def test_valid_payload_persists_document_and_fields(client, tc_headers, repo):
    txn_id = _create_txn(client, tc_headers)
    r = client.post(f"/transactions/{txn_id}/payloads", json=_payload(txn_id), headers=tc_headers)
    assert r.status_code == 201

    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert len(state["payloads"]) == 1
    assert len(state["documents"]) == 1
    assert state["documents"][0]["external_ref"] == "synthetic-doc-1"
    assert state["documents"][0]["status"] == "pending"
    names = {f["name"] for f in state["extracted_fields"]}
    assert names == {"close_of_escrow", "purchase_price"}
    assert all(f["confirmed"] is False for f in state["extracted_fields"])


def test_payload_write_appends_audit_row(client, tc_headers, repo):
    txn_id = _create_txn(client, tc_headers)
    client.post(f"/transactions/{txn_id}/payloads", json=_payload(txn_id), headers=tc_headers)
    actions = [a["action"] for a in repo.audit_log]
    assert actions.count("payload.written") == 1
    row = next(a for a in repo.audit_log if a["action"] == "payload.written")
    assert row["actor"] == "tc@example.test"
    assert row["details"]["field_count"] == 2


def test_invalid_payload_is_422_and_commits_nothing(client, tc_headers, repo):
    txn_id = _create_txn(client, tc_headers)
    bad = _payload(txn_id)
    bad["extracted_fields"][0]["confidence"] = 1.5
    r = client.post(f"/transactions/{txn_id}/payloads", json=bad, headers=tc_headers)
    assert r.status_code == 422
    assert repo.payloads == {}
    assert repo.documents == {}


def test_payload_for_unknown_transaction_is_404(client, tc_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    r = client.post(f"/transactions/{missing}/payloads", json=_payload(missing), headers=tc_headers)
    assert r.status_code == 404


def test_new_payload_is_rejected_with_hitl_explanation(client, tc_headers, repo):
    """Nothing commits from a NEW payload without TC confirmation (HITL, Phase 3)."""
    txn_id = _create_txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/payloads",
        json=_payload(NEW_TRANSACTION),
        headers=tc_headers,
    )
    assert r.status_code == 409
    assert "confirm" in r.json()["detail"].lower()
    assert repo.payloads == {}


def test_money_wiring_field_names_are_rejected(client, tc_headers, repo):
    """Rule 2 defense in depth: the master never stores money-movement fields."""
    txn_id = _create_txn(client, tc_headers)
    bad = _payload(txn_id)
    bad["extracted_fields"].append(
        {"name": "wire_routing_number", "value": "synthetic", "confidence": 0.9}
    )
    r = client.post(f"/transactions/{txn_id}/payloads", json=bad, headers=tc_headers)
    assert r.status_code == 422
    assert "rule 2" in r.json()["detail"].lower()
    assert repo.payloads == {}
    assert repo.documents == {}


def test_party_from_another_transaction_is_409(client, tc_headers, repo):
    txn_a = _create_txn(client, tc_headers)
    txn_b = _create_txn(client, tc_headers)
    stranger = repo.add_party(transaction_id=txn_b, name="Synthetic Lender", role="lender")
    r = client.post(
        f"/transactions/{txn_a}/payloads",
        json=_payload(txn_a, party_id=stranger["id"]),
        headers=tc_headers,
    )
    assert r.status_code == 409
    assert repo.payloads == {}


def test_party_on_same_transaction_is_accepted(client, tc_headers, repo):
    txn_id = _create_txn(client, tc_headers)
    party = repo.add_party(transaction_id=txn_id, name="Synthetic Lender", role="lender")
    r = client.post(
        f"/transactions/{txn_id}/payloads",
        json=_payload(txn_id, party_id=party["id"]),
        headers=tc_headers,
    )
    assert r.status_code == 201


def test_empty_string_party_id_is_422(client, tc_headers):
    txn_id = _create_txn(client, tc_headers)
    r = client.post(
        f"/transactions/{txn_id}/payloads",
        json=_payload(txn_id, party_id=""),
        headers=tc_headers,
    )
    assert r.status_code == 422


def test_payload_transaction_mismatch_is_409(client, tc_headers, repo):
    txn_a = _create_txn(client, tc_headers)
    txn_b = _create_txn(client, tc_headers)
    r = client.post(f"/transactions/{txn_a}/payloads", json=_payload(txn_b), headers=tc_headers)
    assert r.status_code == 409
    assert repo.payloads == {}
