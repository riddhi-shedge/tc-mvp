"""Ingestion agent routes (part a) — Prompt 2 walking skeleton.

Entry points: the Postmark inbound webhook (dedicated deal address ONLY) and
the TC's HITL confirm. Ingestion writes only its own queue; the SOR is reached
exclusively through validated Payloads sent to the master API with the TC's own
token. Nothing commits to the SOR before the TC confirms (rules/security.md).
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.contracts.payload import NEW_TRANSACTION, Payload
from app.ingestion.inbox_repo import InboxRepo, SupabaseInboxRepo
from app.ingestion.master_client import HttpMasterClient
from app.ingestion.stub_extractor import stub_extract
from app.master.auth import TCUser, bearer_scheme, require_tc

router = APIRouter(prefix="/ingestion")


@lru_cache(maxsize=1)
def _default_inbox() -> SupabaseInboxRepo:
    return SupabaseInboxRepo()


def get_inbox_repo() -> InboxRepo:
    return _default_inbox()


@lru_cache(maxsize=1)
def _default_master_client() -> HttpMasterClient:
    return HttpMasterClient()


def get_master_client() -> HttpMasterClient:
    return _default_master_client()


# ---- Postmark inbound webhook (validated boundary, rules/code-style.md) -----
# Only the fields we read are modeled; everything else — including attachment
# Content — is dropped by validation and never touches storage.


class PostmarkAddress(BaseModel):
    Email: str = ""


class PostmarkAttachment(BaseModel):
    Name: str | None = None
    ContentType: str | None = None
    ContentLength: int | None = None


class PostmarkInbound(BaseModel):
    From: str = ""
    FromFull: PostmarkAddress | None = None
    To: str = ""
    ToFull: list[PostmarkAddress] = Field(default_factory=list)
    OriginalRecipient: str = ""
    Subject: str | None = None
    Attachments: list[PostmarkAttachment] = Field(default_factory=list)


@router.post("/webhooks/postmark")
def postmark_inbound_webhook(
    body: PostmarkInbound,
    token: str | None = Query(default=None),
    x_webhook_token: str | None = Header(default=None),
    inbox: InboxRepo = Depends(get_inbox_repo),
) -> dict[str, Any]:
    expected = os.environ.get("POSTMARK_WEBHOOK_TOKEN")
    deal_address = os.environ.get("POSTMARK_INBOUND_ADDRESS")
    if not expected or not deal_address:
        # Fail closed: an unconfigured webhook accepts nothing.
        raise HTTPException(status_code=503, detail="Inbound webhook not configured")
    # Header preferred (query strings can end up in proxy access logs).
    provided = x_webhook_token or token
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    # Dedicated inbox only (rules/security.md): mail addressed elsewhere is
    # dropped, never stored. 200 so Postmark does not retry.
    recipients = {r.Email.lower() for r in body.ToFull}
    recipients.add(body.To.lower())
    recipients.add(body.OriginalRecipient.lower())
    if deal_address.lower() not in recipients:
        return {"ignored": True}

    first = body.Attachments[0] if body.Attachments else PostmarkAttachment()
    # Metadata only — attachment content is deliberately NOT stored in Phase 2.
    item = inbox.add_item(
        from_email=(body.FromFull.Email if body.FromFull else "") or body.From,
        to_email=deal_address,
        subject=body.Subject,
        attachment_name=first.Name,
        attachment_content_type=first.ContentType,
        attachment_size=first.ContentLength,
        attachment_count=len(body.Attachments),
    )
    return {"ignored": False, "id": item["id"]}


@router.get("/inbox")
def list_inbox(
    tc: TCUser = Depends(require_tc),
    inbox: InboxRepo = Depends(get_inbox_repo),
) -> list[dict[str, Any]]:
    return inbox.list_pending()


class ConfirmRequest(BaseModel):
    # "new" (NEW_TRANSACTION) or an existing transaction id — the TC's HITL call.
    decision: str = Field(min_length=1)


@router.post("/inbox/{item_id}/confirm")
def confirm_inbox_item(
    item_id: str,
    body: ConfirmRequest,
    tc: TCUser = Depends(require_tc),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    inbox: InboxRepo = Depends(get_inbox_repo),
    master: HttpMasterClient = Depends(get_master_client),
) -> dict[str, Any]:
    item = inbox.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="Inbox item already handled")

    if credentials is None:  # require_tc already validated the token
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = credentials.credentials
    fields, property_address = stub_extract(item)

    if body.decision == NEW_TRANSACTION:
        status, data = master.create_transaction(token=token, property_address=property_address)
        if status >= 400:
            raise HTTPException(status_code=status, detail=data.get("detail", "master error"))
        transaction_id = data["id"]
    else:
        transaction_id = body.decision

    payload = Payload(
        document_id=f"inbox-{item_id}",
        transaction_id=transaction_id,
        extracted_fields=fields,
    )
    status, data = master.write_payload(token=token, transaction_id=transaction_id, payload=payload)
    if status >= 400:
        detail = data.get("detail", "master error")
        if body.decision == NEW_TRANSACTION:
            # The transaction exists but carries no payload yet. Point the TC
            # at it so a retry attaches instead of creating a duplicate deal.
            detail = (
                f"Transaction {transaction_id} was created but the payload write "
                f"failed: {detail}. Retry this inbox item with "
                f"decision='{transaction_id}' to attach to it."
            )
        raise HTTPException(status_code=status, detail=detail)

    confirmed = inbox.mark_confirmed(item_id, transaction_id)
    if confirmed is None:
        # Another request confirmed it between our check and now.
        raise HTTPException(status_code=409, detail="Inbox item already handled")
    return {
        "transaction_id": transaction_id,
        "payload_id": data.get("id"),
        "item": confirmed,
    }
