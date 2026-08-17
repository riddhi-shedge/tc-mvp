"""The master persist endpoint: service-token auth, §11 gate, Rule 3 (drafts
only), idempotent replacement, audit."""

import os

from app.contracts.compliance import (
    ComplianceResult,
    ComputedDeadline,
    ComputedTask,
    DraftReminder,
    RiskFlag,
)

SERVICE_TOKEN = "synthetic-compliance-token"
os.environ.setdefault("COMPLIANCE_SERVICE_TOKEN", SERVICE_TOKEN)


def _headers() -> dict[str, str]:
    return {"X-Compliance-Token": SERVICE_TOKEN}


def _result(txn_id: str, *, extra_deadline: bool = False) -> dict:
    deadlines = [
        ComputedDeadline(
            key="inspection_contingency",
            name="Inspection contingency ends",
            due_date="2026-07-27",
            source_field="inspection_contingency_days",
        )
    ]
    if extra_deadline:
        deadlines.append(
            ComputedDeadline(
                key="coe",
                name="Close of escrow",
                due_date="2026-08-10",
                source_field="close_of_escrow",
            )
        )
    return ComplianceResult(
        transaction_id=txn_id,
        deadlines=deadlines,
        tasks=[
            ComputedTask(
                key="task_inspection",
                title="Complete inspections",
                deadline_key="inspection_contingency",
            )
        ],
        risk_flags=[RiskFlag(case="missing_escrow_contact", description="No escrow contact")],
        draft_reminders=[
            DraftReminder(
                flag_case="missing_escrow_contact",
                to_role=None,
                subject="Escrow contact needed",
                body="Please add the escrow company.",
            )
        ],
    ).model_dump(mode="json")


# Every deadline-driving field must be present + confirmed to clear the §11
# coverage gate (as the real extraction flow produces them).
_ALL_DD_FIELDS = [
    {"name": "acceptance_date", "value": "2026-07-10", "confidence": 0.9},
    {"name": "close_of_escrow", "value": "2026-08-14", "confidence": 0.9},
    {"name": "possession_date", "value": "at close of escrow", "confidence": 0.9},
    {"name": "emd_due_days", "value": "3", "confidence": 0.9},
    {"name": "inspection_contingency_days", "value": "17", "confidence": 0.9},
    {"name": "loan_contingency_days", "value": "21", "confidence": 0.9},
    {"name": "appraisal_contingency_days", "value": "17", "confidence": 0.9},
    {"name": "insurance_contingency_days", "value": "17", "confidence": 0.9},
    {"name": "disclosure_delivery_days", "value": "7", "confidence": 0.9},
    {"name": "verification_of_funds_days", "value": "3", "confidence": 0.9},
]


def _confirmed_deal(client, tc_headers, repo, *, address="1 Compliance Way") -> str:
    """A deal with every deadline-driving field confirmed (gate satisfied)."""
    txn_id = client.post(
        "/transactions", json={"property_address": address}, headers=tc_headers
    ).json()["id"]
    client.post(
        f"/transactions/{txn_id}/payloads",
        json={
            "document_id": "doc-1",
            "transaction_id": txn_id,
            "document_type": "purchase_agreement",
            "extracted_fields": _ALL_DD_FIELDS,
        },
        headers=tc_headers,
    )
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    fids = [f["id"] for f in state["extracted_fields"]]
    client.post(
        f"/transactions/{txn_id}/fields/confirm", json={"field_ids": fids}, headers=tc_headers
    )
    return txn_id


def test_missing_token_is_401(client, tc_headers, repo):
    txn_id = _confirmed_deal(client, tc_headers, repo)
    r = client.post(f"/transactions/{txn_id}/compliance-result", json=_result(txn_id))
    assert r.status_code == 401


def test_persists_result_and_drafts_land_draft(client, tc_headers, repo):
    txn_id = _confirmed_deal(client, tc_headers, repo)
    r = client.post(
        f"/transactions/{txn_id}/compliance-result", json=_result(txn_id), headers=_headers()
    )
    assert r.status_code == 201
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert len(state["deadlines"]) == 1
    assert len(state["tasks"]) == 1
    assert len(state["risk_flags"]) == 1
    # Rule 3: the reminder is a DRAFT message, not sent.
    assert [m["status"] for m in state["messages"]] == ["draft"]
    assert any(a["action"] == "compliance.run" for a in repo.audit_log)


def test_gate_blocks_when_deadline_field_unconfirmed(client, tc_headers, repo):
    txn_id = client.post(
        "/transactions", json={"property_address": "2 Gate Way"}, headers=tc_headers
    ).json()["id"]
    client.post(
        f"/transactions/{txn_id}/payloads",
        json={
            "document_id": "doc-2",
            "transaction_id": txn_id,
            "document_type": "purchase_agreement",
            "extracted_fields": [
                {"name": "inspection_contingency_days", "value": "17", "confidence": 0.9}
            ],
        },
        headers=tc_headers,
    )  # NOT confirmed
    r = client.post(
        f"/transactions/{txn_id}/compliance-result", json=_result(txn_id), headers=_headers()
    )
    assert r.status_code == 409
    assert "BLOCKED" in r.json()["detail"]


def test_rerun_replaces_not_duplicates(client, tc_headers, repo):
    txn_id = _confirmed_deal(client, tc_headers, repo)
    client.post(
        f"/transactions/{txn_id}/compliance-result", json=_result(txn_id), headers=_headers()
    )
    # Second run with an extra deadline replaces the first (no accumulation).
    client.post(
        f"/transactions/{txn_id}/compliance-result",
        json=_result(txn_id, extra_deadline=True),
        headers=_headers(),
    )
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert len(state["deadlines"]) == 2  # replaced (1 -> 2), not 3
    assert len(state["risk_flags"]) == 1  # replaced, not doubled
    assert len([m for m in state["messages"] if m["status"] == "draft"]) == 1


def test_rerun_removes_a_deadline_no_longer_computed(client, tc_headers, repo):
    """Hotspot #4: a re-run with FEWER deadlines (e.g. a contingency removed, or
    the deal went all-cash) must DELETE the now-stale deadline/task/flag — not
    leave the TC chasing a deadline that no longer exists."""
    txn_id = _confirmed_deal(client, tc_headers, repo)
    # Run 1: two deadlines (inspection + COE), a task, a flag, a draft.
    client.post(
        f"/transactions/{txn_id}/compliance-result",
        json=_result(txn_id, extra_deadline=True),
        headers=_headers(),
    )
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert {d["name"] for d in state["deadlines"]} == {
        "Inspection contingency ends",
        "Close of escrow",
    }

    # Run 2: only the COE remains (inspection contingency dropped).
    from app.contracts.compliance import ComplianceResult, ComputedDeadline

    shrunk = ComplianceResult(
        transaction_id=txn_id,
        deadlines=[
            ComputedDeadline(
                key="coe", name="Close of escrow", due_date="2026-08-10",
                source_field="close_of_escrow",
            )
        ],
        tasks=[], risk_flags=[], draft_reminders=[],
    ).model_dump(mode="json")
    client.post(f"/transactions/{txn_id}/compliance-result", json=shrunk, headers=_headers())

    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    names = {d["name"] for d in state["deadlines"]}
    assert names == {"Close of escrow"}, f"stale deadline lingered: {names}"
    assert all(t["compute_key"] != "task_inspection" for t in state["tasks"] if t.get("compute_key"))
    assert not [f for f in state["risk_flags"] if f.get("case_key") == "missing_escrow_contact"]


def test_transaction_id_mismatch_is_409(client, tc_headers, repo):
    txn_id = _confirmed_deal(client, tc_headers, repo)
    r = client.post(
        f"/transactions/{txn_id}/compliance-result",
        json=_result("some-other-id"),
        headers=_headers(),
    )
    assert r.status_code == 409


def _lender_result(txn_id: str) -> dict:
    """A compliance result whose draft targets the lender (so it's sendable)."""
    r = ComplianceResult(
        transaction_id=txn_id,
        deadlines=[
            ComputedDeadline(
                key="loan_contingency",
                name="Loan contingency ends",
                due_date="2026-07-31",
                source_field="loan_contingency_days",
            )
        ],
        tasks=[],
        risk_flags=[RiskFlag(case="loan_contingency_approaching", description="approaching")],
        draft_reminders=[
            DraftReminder(
                flag_case="loan_contingency_approaching",
                to_role="lender",
                subject="Loan contingency deadline approaching",
                body="Please confirm loan status.",
            )
        ],
    )
    return r.model_dump(mode="json")


def test_rerun_preserves_an_already_sent_compliance_message(client, tc_headers, repo):
    """A compliance draft the TC approved-and-sent must survive later runs —
    the record is append-only (blocking review fix)."""
    txn_id = _confirmed_deal(client, tc_headers, repo)
    client.post(
        f"/transactions/{txn_id}/parties",
        json={"name": "Syn Lender", "role": "lender", "email": "lender@example.test"},
        headers=tc_headers,
    )
    client.post(
        f"/transactions/{txn_id}/compliance-result",
        json=_lender_result(txn_id),
        headers=_headers(),
    )
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    msg_id = next(m["id"] for m in state["messages"] if m["status"] == "draft")
    assert (
        client.post(
            f"/transactions/{txn_id}/messages/{msg_id}/approve-and-send", headers=tc_headers
        ).status_code
        == 200
    )

    # Re-run compliance — the sent message (and its approval) must remain.
    client.post(
        f"/transactions/{txn_id}/compliance-result",
        json=_lender_result(txn_id),
        headers=_headers(),
    )
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert any(m["id"] == msg_id and m["status"] == "sent" for m in state["messages"])
    assert len(state["approvals"]) == 1


def test_rerun_preserves_task_completion(client, tc_headers, repo):
    """A compliance task a party marked done stays done across re-runs (blocking
    review fix — no delete+recreate reset)."""
    txn_id = _confirmed_deal(client, tc_headers, repo)
    client.post(
        f"/transactions/{txn_id}/compliance-result", json=_result(txn_id), headers=_headers()
    )
    # Mark the compliance task done directly in the repo (party action; the TC
    # task-status API arrives in Phase 7).
    task = next(t for t in repo.tasks if t.get("generated_by") == "compliance")
    task["status"] = "done"

    client.post(
        f"/transactions/{txn_id}/compliance-result", json=_result(txn_id), headers=_headers()
    )
    survived = [t for t in repo.tasks if t.get("compute_key") == task["compute_key"]]
    assert len(survived) == 1 and survived[0]["status"] == "done"


def test_compliance_state_read_uses_service_token(client, tc_headers, repo):
    txn_id = _confirmed_deal(client, tc_headers, repo)
    # No token -> 401 (not a TC session).
    assert client.get(f"/transactions/{txn_id}/compliance-state").status_code == 401
    r = client.get(f"/transactions/{txn_id}/compliance-state", headers=_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["transaction_id"] == txn_id
    assert {f["name"] for f in body["fields"]} >= {"inspection_contingency_days"}
    # The slice carries only the compliance-relevant keys, not full deal state.
    assert set(body) == {"transaction_id", "fields", "parties", "documents", "tasks"}
