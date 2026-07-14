"""Phase 3 "done when": a synthetic PA creates a deal and a synthetic
proof-of-funds attaches to the CORRECT deal — both only after TC confirmation,
with routing tested and no compliance service involved."""

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

URL = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"


def test_pa_creates_deal_and_pof_routes_to_it(client, tc_headers, repo, inbox):
    # --- A signed PA arrives at the dedicated address ---
    pa = client.post(URL, json=postmark_inbound()).json()
    assert repo.transactions == {}  # HITL: nothing commits from arrival

    # TC confirms "new deal" — the agent proposed, the human decided.
    txn_id = client.post(
        f"/ingestion/inbox/{pa['id']}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]
    assert len(repo.transactions) == 1

    # --- A proof of funds arrives from the same sender ---
    pof = client.post(
        URL,
        json=postmark_inbound(
            subject="Proof of funds — buyers (synthetic)",
            attachment_name="pof-synthetic.pdf",
        ),
    ).json()

    # Routing SUGGESTS the right deal (sender history) but commits nothing.
    inbox_view = client.get("/ingestion/inbox", headers=tc_headers).json()
    pof_item = next(i for i in inbox_view if i["id"] == pof["id"])
    assert pof_item["detected_doc_type"] == "proof_of_funds"
    assert pof_item["suggestion"]["transaction_id"] == txn_id
    assert len(repo.get_full_state(txn_id)["documents"]) == 1  # still just the PA

    # TC confirms the suggested routing — the POF attaches to the CORRECT deal.
    r = client.post(
        f"/ingestion/inbox/{pof['id']}/confirm",
        json={"decision": pof_item["suggestion"]["transaction_id"]},
        headers=tc_headers,
    )
    assert r.status_code == 200
    assert len(repo.transactions) == 1  # no second deal

    state = repo.get_full_state(txn_id)
    doc_types = {d["doc_type"] for d in state["documents"]}
    assert doc_types == {"purchase_agreement", "proof_of_funds"}
    pof_doc = next(d for d in state["documents"] if d["doc_type"] == "proof_of_funds")
    assert pof_doc["storage_path"]  # file retained for Phase 4 extraction

    # No compliance service involved: nothing computed any deadline or task.
    assert state["deadlines"] == []
    assert state["tasks"] == []
    # §5 fields came only from the PA; the POF payload carried none.
    payload_fields = {len(p["raw"]["extracted_fields"]) for p in state["payloads"]}
    assert payload_fields == {12, 0}


def test_unreadable_email_falls_back_to_manual_upload(client, tc_headers, repo, inbox):
    txn_id = client.post(
        "/transactions", json={"property_address": "9 Existing Ct"}, headers=tc_headers
    ).json()["id"]

    # Unreadable email (no attachment) -> needs_manual, not confirmable.
    body = postmark_inbound(subject="Faxed disclosure — see attached (synthetic)")
    body["Attachments"] = []
    item_id = client.post(URL, json=body).json()["id"]
    r = client.post(
        f"/ingestion/inbox/{item_id}/confirm", json={"decision": txn_id}, headers=tc_headers
    )
    assert r.status_code == 409
    assert "manual-upload" in r.json()["detail"]

    # TC uploads the document manually, confirms it onto the deal, and
    # dismisses the unreadable email item.
    import base64

    uploaded = client.post(
        "/ingestion/manual-upload",
        json={
            "filename": "disclosure-synthetic.pdf",
            "content_base64": base64.b64encode(b"PDF-synthetic-disclosure").decode(),
            "subject": "Disclosure (synthetic)",
        },
        headers=tc_headers,
    ).json()
    assert (
        client.post(
            f"/ingestion/inbox/{uploaded['id']}/confirm",
            json={"decision": txn_id},
            headers=tc_headers,
        ).status_code
        == 200
    )
    assert repo.get_full_state(txn_id)["documents"][0]["doc_type"] == "disclosure"

    assert client.post(f"/ingestion/inbox/{item_id}/dismiss", headers=tc_headers).status_code == 200
    assert inbox.items[item_id]["status"] == "ignored"
