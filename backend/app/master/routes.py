"""Master API routes — Prompt 1: create transaction, write validated Payload,
read full deal state. The only path to the SOR; every route requires TC auth.

Payloads are the only write path for deal data, validated at the boundary
(rules/architecture.md). A NEW payload never commits here: transaction creation
from ingestion is HITL and arrives with Phase 3.
"""

from __future__ import annotations

import os
import re
import secrets
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.common.auth import TCUser, require_tc
from app.contracts.compliance import ComplianceResult
from app.contracts.fields import EXTRACTABLE_FIELD_NAMES
from app.contracts.payload import Payload
from app.master.repo import (
    DeadlineFieldsUnconfirmed,
    MasterRepo,
    MessageNotSendable,
    SupabaseRepo,
    TimelineAlreadyExists,
)

router = APIRouter()


def require_compliance_service(
    x_compliance_token: str | None = Header(default=None),
) -> None:
    """Service-token auth for the compliance runner (a machine can't do MFA).
    Constant-time compare; fails closed when unconfigured — mirrors the
    Postmark inbound webhook token."""
    expected = os.environ.get("COMPLIANCE_SERVICE_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Compliance endpoint not configured")
    if x_compliance_token is None or not secrets.compare_digest(x_compliance_token, expected):
        raise HTTPException(status_code=401, detail="Invalid compliance service token")


# Rule 2 (rules/security.md): money movement and wiring instructions are never
# parsed, stored, displayed, or transmitted. Ingestion must not extract such
# fields; the master rejects them anyway as defense in depth.
_MONEY_FIELD_NAME = re.compile(
    r"wir(?:e|ing)|routing|account[\s_-]?(?:number|no)|iban|swift|\baba\b|bank",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _default_repo() -> SupabaseRepo:
    return SupabaseRepo()


def get_repo() -> MasterRepo:
    return _default_repo()


class CreateTransactionRequest(BaseModel):
    property_address: str = Field(min_length=1)


@router.post("/transactions", status_code=201)
def create_transaction(
    body: CreateTransactionRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    return repo.create_transaction(property_address=body.property_address, actor=tc.actor)


@router.get("/transactions")
def list_transactions(
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> list[dict[str, Any]]:
    return repo.list_transactions()


class ConfirmFieldsRequest(BaseModel):
    field_ids: list[str] = Field(min_length=1)


@router.post("/transactions/{transaction_id}/fields/confirm")
def confirm_fields(
    transaction_id: str,
    body: ConfirmFieldsRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    count = repo.confirm_fields(
        transaction_id=transaction_id, field_ids=body.field_ids, actor=tc.actor
    )
    return {"confirmed": count}


@router.post("/transactions/{transaction_id}/timeline/stub", status_code=201)
def create_stub_timeline(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        return repo.create_stub_timeline(transaction_id=transaction_id, actor=tc.actor)
    except DeadlineFieldsUnconfirmed as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "BLOCKED: the timeline cannot build until every deadline-driving "
                "field is TC-confirmed (§11 step 4). Unconfirmed or not yet "
                f"extracted: {', '.join(exc.field_names)}. Confirm them — or "
                "enter missing ones manually — first."
            ),
        ) from None
    except TimelineAlreadyExists:
        raise HTTPException(
            status_code=409, detail="A timeline already exists for this transaction"
        ) from None


@router.post("/transactions/{transaction_id}/messages/draft-stub", status_code=201)
def create_stub_draft(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return repo.create_stub_draft(transaction_id=transaction_id, actor=tc.actor)


@router.post("/transactions/{transaction_id}/messages/{message_id}/approve-and-send")
def approve_and_send(
    transaction_id: str,
    message_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The human approval (Rule 3). Phase 2's send is FAKE — audit-log only."""
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        result = repo.approve_and_send_fake(
            transaction_id=transaction_id, message_id=message_id, actor=tc.actor
        )
    except MessageNotSendable:
        raise HTTPException(
            status_code=409, detail="Message is not a draft — cannot approve/send again"
        ) from None
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return result


@router.get("/transactions/{transaction_id}/compliance-state")
def read_compliance_state(
    transaction_id: str,
    _: None = Depends(require_compliance_service),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Least-privilege read for the scheduled compliance service: only the slice
    it needs (confirmed fields, parties, doc status, task status) — not the full
    deal state, and NOT a TC session. Service-token auth."""
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {
        "transaction_id": transaction_id,
        "fields": [
            {
                "name": f["name"],
                "value": f["value"],
                "confirmed": f["confirmed"],
                "deadline_driving": f.get("deadline_driving", False),
            }
            for f in state.get("extracted_fields", [])
        ],
        "parties": [
            {"role": p.get("role", ""), "name": p.get("name"), "email": p.get("email")}
            for p in state.get("parties", [])
        ],
        "documents": [
            {"doc_type": d.get("doc_type"), "status": d.get("status", "")}
            for d in state.get("documents", [])
        ],
        "tasks": [
            {"title": t.get("title", ""), "status": t.get("status", "")}
            for t in state.get("tasks", [])
        ],
    }


@router.post("/transactions/{transaction_id}/compliance-result", status_code=201)
def apply_compliance_result(
    transaction_id: str,
    result: ComplianceResult,
    _: None = Depends(require_compliance_service),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Persist a compliance run (part c → the SOR). Service-token auth; §11 gate
    and Rule 3 (drafts only) enforced in the repo. Idempotent per deal."""
    if result.transaction_id != transaction_id:
        raise HTTPException(status_code=409, detail="Result transaction_id does not match the URL")
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        return repo.apply_compliance_result(result=result, actor="compliance-service")
    except DeadlineFieldsUnconfirmed as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "BLOCKED: compliance cannot run until every deadline-driving field "
                f"is TC-confirmed (§11). Unconfirmed or missing: {', '.join(exc.field_names)}."
            ),
        ) from None


@router.get("/transactions/{transaction_id}")
def read_full_state(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return state


@router.post("/transactions/{transaction_id}/payloads", status_code=201)
def write_payload(
    transaction_id: str,
    payload: Payload,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if payload.is_new_transaction:
        raise HTTPException(
            status_code=409,
            detail=(
                "NEW payloads are not accepted here: transaction creation is "
                "human-in-the-loop and nothing commits until the TC confirms "
                "(ingestion flow, Phase 3). Create the transaction first, then "
                "write payloads to it."
            ),
        )
    if payload.transaction_id != transaction_id:
        raise HTTPException(
            status_code=409,
            detail="Payload transaction_id does not match the URL transaction",
        )
    money_fields = [f.name for f in payload.extracted_fields if _MONEY_FIELD_NAME.search(f.name)]
    if money_fields:
        raise HTTPException(
            status_code=422,
            detail=(
                "Rule 2: money-movement/wiring fields are never extracted or "
                f"stored. Rejected field name(s): {', '.join(money_fields)}"
            ),
        )
    # Defense in depth: only names from the human-verified §5 list may enter
    # the SOR, regardless of which client wrote the payload.
    unknown_fields = sorted({f.name for f in payload.extracted_fields} - EXTRACTABLE_FIELD_NAMES)
    if unknown_fields:
        raise HTTPException(
            status_code=422,
            detail=(
                "Field name(s) outside the verified §5 extraction list: "
                f"{', '.join(unknown_fields)}"
            ),
        )
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    if payload.party_id is not None and not repo.party_belongs_to_transaction(
        party_id=payload.party_id, transaction_id=transaction_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Payload party_id does not belong to this transaction",
        )
    return repo.write_payload(transaction_id=transaction_id, payload=payload, actor=tc.actor)
