"""Ingestion agent routes (part a) — Phase 3: the real monitoring agent.

Entry points: the Postmark inbound webhook (dedicated deal address ONLY) and
the TC-authed manual-upload fallback. The ingestion_inbox table is the
lightweight queue between "detected" and "payload written". Detection and
routing SUGGEST; the TC confirms every create and every update (HITL). The SOR
is reached exclusively through validated Payloads sent to the master API with
the TC's own token. Document content lives in ingestion's private bucket —
never in rows, logs, or responses.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.contracts.documents import UNKNOWN_DOC_TYPE, DocType
from app.contracts.payload import NEW_TRANSACTION, Payload
from app.ingestion.detector import check_readability, detect_doc_type
from app.ingestion.inbox_repo import InboxRepo, StorageUnavailable, SupabaseInboxRepo
from app.ingestion.master_client import HttpMasterClient
from app.ingestion.routing import suggest_transaction
from app.ingestion.stub_extractor import stub_extract
from app.common.auth import TCUser, bearer_scheme, require_tc

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


def _tc_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None:  # require_tc already validated the token
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return credentials.credentials


# ---- Postmark inbound webhook (validated boundary, rules/code-style.md) -----
# Only the fields we read are modeled. Attachment Content is decoded straight
# into the private bucket and never stored on the row or logged.


class PostmarkAddress(BaseModel):
    Email: str = ""


class PostmarkAttachment(BaseModel):
    Name: str | None = None
    ContentType: str | None = None
    ContentLength: int | None = None
    Content: str | None = None  # base64; used only for the storage upload


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
    from_email = (body.FromFull.Email if body.FromFull else "") or body.From

    unreadable_reason = check_readability(
        attachment_name=first.Name,
        content_type=first.ContentType,
        size=first.ContentLength,
        has_content=bool(first.Content),
    )
    storage_path: str | None = None
    if unreadable_reason is None:
        try:
            storage_path = inbox.store_attachment(
                source="email",
                filename=first.Name or "attachment.pdf",
                content_base64=first.Content or "",
            )
        except ValueError:
            unreadable_reason = "attachment content could not be decoded"
        except StorageUnavailable:
            # 5xx so Postmark redelivers later — the attachment is not lost.
            raise HTTPException(
                status_code=503, detail="Attachment store unavailable; retry delivery"
            ) from None

    item = inbox.add_item(
        from_email=from_email,
        to_email=deal_address,
        subject=body.Subject,
        attachment_name=first.Name,
        attachment_content_type=first.ContentType,
        attachment_size=first.ContentLength,
        attachment_count=len(body.Attachments),
        detected_doc_type=detect_doc_type(first.Name, body.Subject),
        storage_path=storage_path,
        source="email",
        status="pending" if unreadable_reason is None else "needs_manual",
        needs_manual_reason=unreadable_reason,
    )
    return {"ignored": False, "id": item["id"], "status": item["status"]}


# ---- Manual-upload fallback (the only other ingestion entry) ----------------


class ManualUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    subject: str | None = None
    doc_type: DocType | None = None


@router.post("/manual-upload", status_code=201)
def manual_upload(
    body: ManualUploadRequest,
    tc: TCUser = Depends(require_tc),
    inbox: InboxRepo = Depends(get_inbox_repo),
) -> dict[str, Any]:
    """Fallback for unreadable emails/scans: the TC uploads the file directly.
    It joins the same queue and still requires an explicit confirm (HITL)."""
    if not body.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Manual upload accepts PDF files only")
    try:
        storage_path = inbox.store_attachment(
            source="manual", filename=body.filename, content_base64=body.content_base64
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except StorageUnavailable:
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    item = inbox.add_item(
        from_email=tc.actor,
        to_email="manual-upload",
        subject=body.subject,
        attachment_name=body.filename,
        attachment_content_type="application/pdf",
        attachment_size=None,
        attachment_count=1,
        detected_doc_type=body.doc_type or detect_doc_type(body.filename, body.subject),
        storage_path=storage_path,
        source="manual",
    )
    return item


# ---- The TC's queue view (with routing suggestions) --------------------------


@router.get("/inbox")
def list_inbox(
    tc: TCUser = Depends(require_tc),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    inbox: InboxRepo = Depends(get_inbox_repo),
    master: HttpMasterClient = Depends(get_master_client),
) -> list[dict[str, Any]]:
    items = inbox.list_open()
    if not items:
        return []
    # Suggestions use the TC's own view of the deals (their token, forwarded).
    # If the master is unreachable, items still list — just without suggestions.
    status, transactions = master.list_transactions(token=_tc_token(credentials))
    known = transactions if status < 400 and isinstance(transactions, list) else []
    history = inbox.sender_history()
    return [
        {
            **item,
            "suggestion": (
                suggest_transaction(
                    subject=item.get("subject"),
                    from_email=item.get("from_email", ""),
                    transactions=known,
                    sender_history=history,
                )
                if item["status"] == "pending"
                else None
            ),
        }
        for item in items
    ]


# ---- HITL confirm / dismiss ---------------------------------------------------


class ConfirmRequest(BaseModel):
    # "new" (NEW_TRANSACTION) or an existing transaction id — the TC's HITL call.
    decision: str = Field(min_length=1)
    # TC's correction/confirmation of the detected type (e.g. for 'unknown').
    doc_type: DocType | None = None


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
    if item["status"] == "needs_manual":
        raise HTTPException(
            status_code=409,
            detail=(
                "This item is unreadable and needs the manual-upload fallback: "
                f"{item.get('needs_manual_reason') or 'unreadable'}. Upload the "
                "document via /ingestion/manual-upload, then confirm that item."
            ),
        )
    if item["status"] == "processing":
        raise HTTPException(status_code=409, detail="Inbox item is being processed")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail="Inbox item already handled")

    token = _tc_token(credentials)
    doc_type = body.doc_type or item.get("detected_doc_type") or UNKNOWN_DOC_TYPE
    if doc_type == UNKNOWN_DOC_TYPE:
        # Never guess: an unclassified document can't enter the SOR.
        raise HTTPException(
            status_code=422,
            detail="Document type is unknown — pass doc_type to confirm this item",
        )

    # Claim the item BEFORE any master write so a concurrent confirm can't
    # duplicate side effects; release it if anything below fails.
    if inbox.claim(item_id) is None:
        raise HTTPException(status_code=409, detail="Inbox item already handled")
    try:
        stub_fields, stub_address = stub_extract(item)

        if body.decision == NEW_TRANSACTION:
            # §11 step 2: a new deal is proposed from a purchase agreement; the
            # TC may still create one from another doc type, but only explicitly.
            status, data = master.create_transaction(token=token, property_address=stub_address)
            if status >= 400:
                raise HTTPException(status_code=status, detail=data.get("detail", "master error"))
            transaction_id = data["id"]
        else:
            transaction_id = body.decision

        # §5 fields come from a purchase agreement; real extraction is Phase 4.
        payload = Payload(
            document_id=f"inbox-{item_id}",
            transaction_id=transaction_id,
            extracted_fields=stub_fields if doc_type == "purchase_agreement" else [],
            document_type=doc_type,
            document_storage_ref=item.get("storage_path"),
        )
        status, data = master.write_payload(
            token=token, transaction_id=transaction_id, payload=payload
        )
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
    except Exception:
        inbox.release(item_id)  # back to pending so the TC can retry
        raise

    confirmed = inbox.mark_confirmed(item_id, transaction_id)
    if confirmed is None:  # defensive: we hold the claim, this shouldn't happen
        raise HTTPException(status_code=409, detail="Inbox item already handled")
    return {
        "transaction_id": transaction_id,
        "payload_id": data.get("id"),
        "item": confirmed,
    }


@router.post("/inbox/{item_id}/dismiss")
def dismiss_inbox_item(
    item_id: str,
    tc: TCUser = Depends(require_tc),
    inbox: InboxRepo = Depends(get_inbox_repo),
) -> dict[str, Any]:
    """Close out an item that shouldn't become a payload (e.g. superseded by a
    manual upload, or junk that made it to the deal address)."""
    item = inbox.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    ignored = inbox.mark_ignored(item_id)
    if ignored is None:
        raise HTTPException(status_code=409, detail="Inbox item already handled")
    return ignored
