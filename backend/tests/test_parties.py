"""Parties as first-class records: the confirmed purchase-agreement names become
real Party rows (one per person, agents split from brokerage), the TC can fill in
contact details, and re-confirming never duplicates a contact."""

from app.contracts.payload import ExtractedField
from app.master.parties import derive_parties, party_key, tier_for
from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

WEBHOOK_URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"

PARTY_FIELDS = [
    ExtractedField(name="buyer_names", value="Amarendra Kumar Verma, Sushmita Verma", confidence=0.95),
    ExtractedField(name="seller_names", value="Christina Luk", confidence=0.95),
    ExtractedField(name="buyer_agent", value="Jane Doe, XYZ Realty", confidence=0.9),
    ExtractedField(name="listing_agent", value="John Roe, ABC Realty", confidence=0.9),
    ExtractedField(name="escrow_holder", value="Placer Title Escrow", confidence=0.9),
    ExtractedField(name="title_company", value="First American", confidence=0.9),
]


def _deal_with_party_fields(client, tc_headers, extractor) -> str:
    extractor.fields = extractor.fields + PARTY_FIELDS
    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    return client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]


def _bare_deal(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "1 Alpha St (synthetic)"}, headers=tc_headers
    ).json()["id"]


# ---- pure derivation --------------------------------------------------------

def test_derive_splits_multiple_buyers():
    d = derive_parties({"buyer_names": "Amarendra Kumar Verma, Sushmita Verma"})
    assert [p.name for p in d if p.role == "buyer"] == [
        "Amarendra Kumar Verma",
        "Sushmita Verma",
    ]


def test_derive_split_handles_and_ampersand():
    d = derive_parties({"seller_names": "Ann Lee & Bob Ng and Cara Ho"})
    assert [p.name for p in d if p.role == "seller"] == ["Ann Lee", "Bob Ng", "Cara Ho"]


def test_derive_agent_splits_name_and_brokerage():
    d = derive_parties({"buyer_agent": "Jane Doe, XYZ Realty"})
    agent = next(p for p in d if p.role == "buyer_agent")
    assert agent.name == "Jane Doe" and agent.company == "XYZ Realty"


def test_derive_agent_captures_email_and_phone():
    d = derive_parties(
        {
            "buyer_agent": "Jane Doe, XYZ Realty",
            "buyer_agent_email": "jane@xyz.test",
            "buyer_agent_phone": "408-555-0101",
        }
    )
    agent = next(p for p in d if p.role == "buyer_agent")
    assert agent.email == "jane@xyz.test" and agent.phone == "408-555-0101"


def test_derive_escrow_and_title_are_companies():
    d = derive_parties({"escrow_holder": "Placer Title Escrow", "title_company": "First American"})
    by_role = {p.role: p for p in d}
    assert by_role["escrow"].name == "Placer Title Escrow"
    assert by_role["escrow"].company == "Placer Title Escrow"
    assert by_role["title"].name == "First American"


def test_derive_ignores_blanks():
    assert derive_parties({"buyer_names": "", "buyer_agent": "   "}) == []


def test_party_key_normalizes_case_and_space():
    assert party_key("buyer", "  Jane   Doe ") == party_key("buyer", "jane doe")


def test_tier_defaults():
    assert tier_for("buyer_agent") == "email_participant"
    assert tier_for("inspector_termite") == "receiving_end"
    assert tier_for("unknown_role") == "email_participant"


# ---- extraction -> parties on confirm ---------------------------------------

def test_no_parties_until_fields_confirmed(client, tc_headers, extractor):
    txn = _deal_with_party_fields(client, tc_headers, extractor)
    assert client.get(f"/transactions/{txn}", headers=tc_headers).json()["parties"] == []


def test_confirming_fields_creates_party_records(client, tc_headers, extractor):
    txn = _deal_with_party_fields(client, tc_headers, extractor)
    state = client.get(f"/transactions/{txn}", headers=tc_headers).json()
    ids = [f["id"] for f in state["extracted_fields"]]

    r = client.post(f"/transactions/{txn}/fields/confirm", json={"field_ids": ids}, headers=tc_headers)
    assert r.json()["parties_created"] >= 6

    parties = client.get(f"/transactions/{txn}", headers=tc_headers).json()["parties"]
    assert sorted(p["name"] for p in parties if p["role"] == "buyer") == [
        "Amarendra Kumar Verma",
        "Sushmita Verma",
    ]
    agent = next(p for p in parties if p["role"] == "buyer_agent")
    assert agent["company"] == "XYZ Realty"
    assert {"escrow", "title", "listing_agent"} <= {p["role"] for p in parties}


def test_agent_email_phone_populate_and_backfill(client, tc_headers, extractor):
    """First confirm creates the agent with no contact; adding the agent's email
    field then re-deriving backfills it onto the existing party."""
    extractor.fields = extractor.fields + [
        ExtractedField(name="buyer_agent", value="Jane Doe, XYZ Realty", confidence=0.9),
    ]
    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    txn = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]
    ids = [f["id"] for f in client.get(f"/transactions/{txn}", headers=tc_headers).json()["extracted_fields"]]
    client.post(f"/transactions/{txn}/fields/confirm", json={"field_ids": ids}, headers=tc_headers)

    agent = next(
        p for p in client.get(f"/transactions/{txn}", headers=tc_headers).json()["parties"]
        if p["role"] == "buyer_agent"
    )
    assert agent["email"] is None

    client.post(
        f"/transactions/{txn}/fields",
        json={"name": "buyer_agent_email", "value": "jane@xyz.test"},
        headers=tc_headers,
    )
    client.post(f"/transactions/{txn}/fields/confirm", json={"field_ids": ids}, headers=tc_headers)
    agent2 = next(
        p for p in client.get(f"/transactions/{txn}", headers=tc_headers).json()["parties"]
        if p["role"] == "buyer_agent"
    )
    assert agent2["email"] == "jane@xyz.test"


def test_derivation_is_idempotent(client, tc_headers, extractor):
    txn = _deal_with_party_fields(client, tc_headers, extractor)
    ids = [f["id"] for f in client.get(f"/transactions/{txn}", headers=tc_headers).json()["extracted_fields"]]
    client.post(f"/transactions/{txn}/fields/confirm", json={"field_ids": ids}, headers=tc_headers)
    n1 = len(client.get(f"/transactions/{txn}", headers=tc_headers).json()["parties"])

    again = client.post(
        f"/transactions/{txn}/fields/confirm", json={"field_ids": ids}, headers=tc_headers
    )
    assert again.json()["parties_created"] == 0
    n2 = len(client.get(f"/transactions/{txn}", headers=tc_headers).json()["parties"])
    assert n1 == n2


# ---- create / update contact details ----------------------------------------

def test_create_party_with_phone_and_company(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Acme Escrow", "role": "escrow", "phone": "555-1212", "company": "Acme"},
        headers=tc_headers,
    )
    assert r.status_code == 201
    assert r.json()["phone"] == "555-1212" and r.json()["company"] == "Acme"


def test_update_party_fills_contact(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    pid = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Termite Co", "role": "inspector_termite"},
        headers=tc_headers,
    ).json()["id"]
    r = client.patch(
        f"/transactions/{txn}/parties/{pid}",
        json={"phone": "555-9999", "email": "t@x.test"},
        headers=tc_headers,
    )
    assert r.status_code == 200
    assert r.json()["phone"] == "555-9999" and r.json()["email"] == "t@x.test"


def test_lender_email_with_bank_is_allowed(client, tc_headers):
    """A lender's contact naturally contains 'bank' — contact fields are not
    money/wiring instructions, so they must not trip the Rule 2 guard."""
    txn = _bare_deal(client, tc_headers)
    r = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Sam", "role": "lender", "email": "sam@synthbank.test", "company": "Synth Bank"},
        headers=tc_headers,
    )
    assert r.status_code == 201 and r.json()["email"] == "sam@synthbank.test"


def test_update_party_no_fields_is_422(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    pid = client.post(
        f"/transactions/{txn}/parties", json={"name": "X", "role": "escrow"}, headers=tc_headers
    ).json()["id"]
    r = client.patch(f"/transactions/{txn}/parties/{pid}", json={}, headers=tc_headers)
    assert r.status_code == 422


def test_update_unknown_party_404(client, tc_headers):
    txn = _bare_deal(client, tc_headers)
    r = client.patch(
        f"/transactions/{txn}/parties/00000000-0000-0000-0000-000000000000",
        json={"phone": "5"},
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_update_party_requires_auth(client):
    r = client.patch("/transactions/x/parties/y", json={"phone": "5"})
    assert r.status_code in (401, 403)
