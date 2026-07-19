"""MVP done-when (§18): the full §11 slice on synthetic data through the REAL
API, end to end — inbound email → HITL confirm → extract → confirm fields →
compliance (VERIFIED 6/26 rules) → risk flags → lender draft → approve/send →
task assign + receiving-end access token → dashboard, every step audited.

Exercises all three decoupled parts (ingestion / master / compliance) wired only
through their real endpoints and payloads. Synthetic data only; sending goes
through the (fake) mailer seam.
"""

from __future__ import annotations

from datetime import date

from tests.conftest import WEBHOOK_TOKEN, postmark_inbound

WEBHOOK = f"/ingestion/webhooks/postmark?token={WEBHOOK_TOKEN}"
COMPLIANCE_TOKEN = "e2e-compliance-token"


def _run_compliance(client, txn_id: str, *, as_of: date):
    """Drive the real compliance round-trip through the master's service-token
    endpoints (read the deal slice → compute with verified rules → write back)."""
    from app.compliance.master_client import _state_from_slice
    from app.compliance.service import run_for_transaction

    hdr = {"X-Compliance-Token": COMPLIANCE_TOKEN}

    class _MasterOverHttp:
        def read_deal_state(self, transaction_id: str):
            r = client.get(f"/transactions/{transaction_id}/compliance-state", headers=hdr)
            assert r.status_code == 200, r.text
            return _state_from_slice(r.json())

        def write_compliance_result(self, result) -> None:
            r = client.post(
                f"/transactions/{result.transaction_id}/compliance-result",
                json=result.model_dump(mode="json"),
                headers=hdr,
            )
            assert r.status_code == 201, r.text

    # rules=None → the production loader → the VERIFIED 6/26 ruleset.
    return run_for_transaction(txn_id, _MasterOverHttp(), as_of=as_of, rules=None)


def test_full_slice_synthetic_deal(client, tc_headers, repo, monkeypatch):
    monkeypatch.setenv("CA_RULES_VERIFIED", "true")  # use the verified 6/26 rules
    monkeypatch.setenv("COMPLIANCE_SERVICE_TOKEN", COMPLIANCE_TOKEN)

    # 1. A signed PA arrives; HITL: nothing commits until the TC confirms.
    pa = client.post(WEBHOOK, json=postmark_inbound()).json()
    assert repo.transactions == {}
    txn_id = client.post(
        f"/ingestion/inbox/{pa['id']}/confirm", json={"decision": "new"}, headers=tc_headers
    ).json()["transaction_id"]

    # 2. Extraction ran on confirm → the §5 fields are present but unconfirmed.
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert len(state["extracted_fields"]) == 12
    unconfirmed = [f["id"] for f in state["extracted_fields"] if not f["confirmed"]]
    assert unconfirmed  # nothing auto-confirmed

    # 3. The TC confirms the fields (the §11 gate for the compliance run).
    client.post(
        f"/transactions/{txn_id}/fields/confirm",
        json={"field_ids": unconfirmed},
        headers=tc_headers,
    )

    # 4. The compliance service computes the timeline on the VERIFIED CA rules.
    #    as_of is late in the window so several §6 risk flags fire.
    result = _run_compliance(client, txn_id, as_of=date(2026, 7, 29))
    assert result.transaction_id == txn_id

    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    # Real 6/26 date math: acceptance 2026-07-10; loan uses the deal's value (21).
    loan = next(d for d in state["deadlines"] if "Loan" in d["name"])
    assert loan["due_date"] == "2026-07-31"
    # COE "30 days after acceptance" → 8/9 Sun → rolls to Mon 8/10.
    coe = next(d for d in state["deadlines"] if "escrow" in d["name"].lower())
    assert coe["due_date"] == "2026-08-10"
    assert state["tasks"], "compliance created tasks"
    assert len(state["risk_flags"]) >= 3  # unscheduled inspection, missing escrow, …

    # 5. Add the lender contact and draft a follow-up (Claude seam → fake drafter).
    client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Synthetic Lender", "role": "lender", "email": "lender@example.test"},
        headers=tc_headers,
    )
    # Compliance may have created draft reminders; diff ids to grab the LENDER draft.
    before = {m["id"] for m in state["messages"]}
    draft_resp = client.post(
        f"/transactions/{txn_id}/messages/draft-lender", headers=tc_headers
    ).json()
    assert "why" in draft_resp  # every AI action shows WHY
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    draft = next(m for m in state["messages"] if m["id"] not in before and m["status"] == "draft")

    # 6. Human approves → the (fake) mailer sends. Rule 3: no send without this tap.
    client.post(
        f"/transactions/{txn_id}/messages/{draft['id']}/approve-and-send",
        json={"subject": draft["subject"], "body": draft["body"]},
        headers=tc_headers,
    )
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert any(m["id"] == draft["id"] and m["status"] == "sent" for m in state["messages"])

    # 7. Assign a task to a receiving-end party and mint their scoped access token.
    inspector_id = client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Synthetic Inspector", "role": "inspector_general"},
        headers=tc_headers,
    ).json()["id"]
    a_task = state["tasks"][0]["id"]
    assert client.post(
        f"/transactions/{txn_id}/tasks/{a_task}/assign",
        json={"party_id": inspector_id},
        headers=tc_headers,
    ).status_code == 200
    token_resp = client.post(
        f"/transactions/{txn_id}/parties/{inspector_id}/access-token", headers=tc_headers
    )
    assert token_resp.status_code == 201
    assert token_resp.json()["access_token"]  # a scoped credential was issued

    # 8. The dashboard drills down; the inspector shows their assigned task.
    dash = client.get(f"/transactions/{txn_id}/dashboard", headers=tc_headers).json()
    insp_view = next(v for v in dash["parties"] if v["party"]["id"] == inspector_id)
    assert any(t["id"] == a_task for t in insp_view["open_tasks"])
    assert dash["risk_alerts"]  # prioritized alerts surfaced

    # 9. Every state change is audited across the whole slice.
    actions = {a["action"] for a in state["audit_log"]}
    assert {"transaction.created", "payload.written", "party.added"} <= actions
    assert any(a.startswith("message.") for a in actions)  # drafted + sent
    assert "task.assigned" in {a["action"] for a in
                               client.get(f"/transactions/{txn_id}", headers=tc_headers).json()["audit_log"]}
