"""Re-uploading a purchase agreement supersedes the prior one (no piling-up of
duplicate documents/fields), reopens an archived deal, and — because contacts are
informational — parties/agent-contacts populate from extracted fields without
waiting on confirmation."""

from app.contracts.payload import ExtractedField, Payload


def _pa_payload(txn_id: str, *, ref: str, fields: list[ExtractedField]) -> Payload:
    return Payload(
        document_id=ref,
        transaction_id=txn_id,
        document_type="purchase_agreement",
        document_storage_ref=f"bucket/{ref}.pdf",
        extracted_fields=fields,
    )


def test_reupload_pa_supersedes_the_prior_one(repo):
    txn = repo.create_transaction(property_address="1 A St", actor="tc")["id"]
    repo.write_payload(
        transaction_id=txn,
        payload=_pa_payload(txn, ref="v1", fields=[ExtractedField(name="apn", value="OLD", confidence=0.9)]),
        actor="tc",
    )
    repo.write_payload(
        transaction_id=txn,
        payload=_pa_payload(txn, ref="v2", fields=[ExtractedField(name="apn", value="NEW", confidence=0.9)]),
        actor="tc",
    )
    state = repo.get_full_state(txn)
    assert len(state["documents"]) == 1  # only the latest PA remains
    apns = [f for f in state["extracted_fields"] if f["name"] == "apn"]
    assert len(apns) == 1 and apns[0]["value"] == "NEW"


def test_reupload_reopens_an_archived_deal(repo):
    txn = repo.create_transaction(property_address="1 A St", actor="tc")["id"]
    repo.archive_transaction(transaction_id=txn, actor="tc")
    assert repo.transactions[txn]["status"] == "archived"
    repo.write_payload(
        transaction_id=txn,
        payload=_pa_payload(txn, ref="v1", fields=[]),
        actor="tc",
    )
    assert repo.transactions[txn]["status"] == "open"


def test_agent_contacts_populate_without_confirmation(repo):
    """Extraction lands unconfirmed; the agent's email/phone still reach the
    Party record (informational, not deadline-driving)."""
    txn = repo.create_transaction(property_address="1 A St", actor="tc")["id"]
    repo.write_payload(
        transaction_id=txn,
        payload=_pa_payload(
            txn,
            ref="v1",
            fields=[
                ExtractedField(name="buyer_agent", value="Jane Doe, XYZ Realty", confidence=0.9),
                ExtractedField(name="buyer_agent_email", value="jane@xyz.test", confidence=0.9),
                ExtractedField(name="buyer_agent_phone", value="408-555-0101", confidence=0.9),
            ],
        ),
        actor="tc",
    )
    # No fields confirmed — derive anyway (informational contacts).
    repo.derive_parties_from_fields(transaction_id=txn, actor="tc")
    agent = next(p for p in repo.parties.values() if p["role"] == "buyer_agent")
    assert agent["email"] == "jane@xyz.test" and agent["phone"] == "408-555-0101"
