"""Master API routes — Prompt 1: create transaction, write validated Payload,
read full deal state. The only path to the SOR; every route requires TC auth.

Payloads are the only write path for deal data, validated at the boundary
(rules/architecture.md). A NEW payload never commits here: transaction creation
from ingestion is HITL and arrives with Phase 3.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.contracts.payload import Payload
from app.master.auth import TCUser, require_tc
from app.master.repo import (
    MasterRepo,
    MessageNotSendable,
    SupabaseRepo,
    TimelineAlreadyExists,
)

router = APIRouter()

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
