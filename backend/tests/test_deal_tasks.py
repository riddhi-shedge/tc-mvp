"""Table-Q allocation rules: the home-warranty issuer drives an action item —
"buyer's choice" is the buyer's agent's task, a warranty with no issuer named is
the listing agent's — and the new informational §5 fields extract cleanly."""

from app.contracts.fields import EXTRACTABLE_FIELD_NAMES, is_deadline_driving
from app.contracts.payload import ExtractedField
from app.master.deal_tasks import derive_tasks
from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

WEBHOOK_URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"


# ---- new §5 fields ----------------------------------------------------------

def test_new_fields_are_extractable_and_informational():
    for name in (
        "items_included",
        "items_excluded",
        "home_warranty_paid_by",
        "home_warranty_issued_by",
        "other_terms",
    ):
        assert name in EXTRACTABLE_FIELD_NAMES
        assert not is_deadline_driving(name)  # must never gate the timeline


# ---- pure allocation rule ---------------------------------------------------

def test_buyers_choice_is_the_buyer_agents_task():
    tasks = derive_tasks({"home_warranty_paid_by": "buyer", "home_warranty_issued_by": "buyer's choice"})
    assert len(tasks) == 1
    assert tasks[0].assign_role == "buyer_agent" and tasks[0].key == "home_warranty_choice"


def test_blank_issuer_with_warranty_is_the_listing_agents_task():
    tasks = derive_tasks({"home_warranty_paid_by": "seller", "home_warranty_issued_by": ""})
    assert len(tasks) == 1
    assert tasks[0].assign_role == "listing_agent" and tasks[0].key == "home_warranty_confirm"


def test_named_issuer_needs_no_task():
    assert derive_tasks({"home_warranty_paid_by": "seller", "home_warranty_issued_by": "First American HW"}) == []


def test_no_warranty_needs_no_task():
    assert derive_tasks({"home_warranty_paid_by": "none", "home_warranty_issued_by": ""}) == []
    assert derive_tasks({}) == []


# ---- end to end: confirm -> rule task, assigned, idempotent -----------------

def _deal_with(client, tc_headers, extractor, extra: list[ExtractedField]) -> str:
    extractor.fields = extractor.fields + extra
    item_id = client.post(WEBHOOK_URL, json=postmark_inbound()).json()["id"]
    return client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]


def test_confirm_creates_and_assigns_the_warranty_task(client, tc_headers, extractor):
    txn = _deal_with(
        client,
        tc_headers,
        extractor,
        [
            ExtractedField(name="buyer_agent", value="Jane Doe, XYZ Realty", confidence=0.9),
            ExtractedField(name="home_warranty_paid_by", value="buyer", confidence=0.9),
            ExtractedField(name="home_warranty_issued_by", value="buyer's choice", confidence=0.9),
        ],
    )
    ids = [f["id"] for f in client.get(f"/transactions/{txn}", headers=tc_headers).json()["extracted_fields"]]
    r = client.post(f"/transactions/{txn}/fields/confirm", json={"field_ids": ids}, headers=tc_headers)
    assert r.json()["tasks_created"] == 1

    state = client.get(f"/transactions/{txn}", headers=tc_headers).json()
    task = next(t for t in state["tasks"] if t.get("compute_key") == "home_warranty_choice")
    agent = next(p for p in state["parties"] if p["role"] == "buyer_agent")
    assert task["assigned_party_id"] == agent["id"]

    # Idempotent — re-confirming creates no duplicate rule task.
    again = client.post(f"/transactions/{txn}/fields/confirm", json={"field_ids": ids}, headers=tc_headers)
    assert again.json()["tasks_created"] == 0
