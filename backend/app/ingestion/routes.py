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

import logging
import os
import secrets
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.common.auth import TCUser, bearer_scheme, require_tc
from app.contracts.documents import (
    COUNTER_OFFER_TYPES,
    OTHER_DOC_TYPE,
    UNKNOWN_DOC_TYPE,
    DocType,
)
from app.contracts.fields import EXTRACTABLE_FIELD_NAMES
from app.contracts.payload import (
    NEW_TRANSACTION,
    CounterMeta,
    ExtractedField,
    InspectionMeta,
    Payload,
    PartyRef,
    PreapprovalMeta,
    PreliminaryMeta,
)
from app.ingestion.detector import check_readability, detect_doc_type
from app.ingestion.extractor import (
    ClaudeExtractor,
    ExtractionBlocked,
    ExtractionFailed,
    Extractor,
)
from app.ingestion.inbox_repo import InboxRepo, StorageUnavailable, SupabaseInboxRepo
from app.ingestion.master_client import HttpMasterClient
from app.ingestion.precheck import decrypt_pdf, precheck_pdf
from app.ingestion.routing import suggest_transaction

router = APIRouter(prefix="/ingestion")
_log = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
def _default_extractor() -> ClaudeExtractor:
    return ClaudeExtractor()


def get_extractor() -> Extractor:
    return _default_extractor()


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


def _ingest_email_attachment(
    inbox: InboxRepo,
    att: "PostmarkAttachment",
    *,
    from_email: str,
    to_email: str,
    subject: str | None,
) -> dict[str, Any]:
    """Store + queue ONE inbound attachment as its own inbox item. Content-addressed
    so a Postmark redelivery of the same bytes is absorbed (idempotent) rather than
    duplicated. Raises StorageUnavailable so the caller can 5xx and let Postmark
    redeliver — the attachment is never lost."""
    unreadable_reason = check_readability(
        attachment_name=att.Name,
        content_type=att.ContentType,
        size=att.ContentLength,
        has_content=bool(att.Content),
    )
    storage_path: str | None = None
    if unreadable_reason is None:
        try:
            storage_path = inbox.store_attachment(
                source="email", filename=att.Name or "attachment.pdf", content_base64=att.Content or ""
            )
        except ValueError:
            unreadable_reason = "attachment content could not be decoded"

    if storage_path is not None:
        duplicate = inbox.find_duplicate_by_storage_path(
            storage_path=storage_path, attachment_count=1
        )
        if duplicate is not None:
            _log.info("ingestion.webhook.duplicate_absorbed item=%s", duplicate["id"])
            return {"id": duplicate["id"], "status": duplicate["status"], "duplicate": True}

    item = inbox.add_item(
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        attachment_name=att.Name,
        attachment_content_type=att.ContentType,
        attachment_size=att.ContentLength,
        attachment_count=1,
        detected_doc_type=detect_doc_type(att.Name, subject),
        storage_path=storage_path,
        source="email",
        status="pending" if unreadable_reason is None else "needs_manual",
        needs_manual_reason=unreadable_reason,
    )
    return {"id": item["id"], "status": item["status"]}


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

    from_email = (body.FromFull.Email if body.FromFull else "") or body.From
    # One inbox item PER attachment — an email with a PA + counter + disclosure must
    # not silently lose all but the first (BUG-19). A no-attachment email still
    # queues one (needs_manual) item so it's visible.
    attachments = body.Attachments or [PostmarkAttachment()]
    try:
        items = [
            _ingest_email_attachment(
                inbox, att, from_email=from_email, to_email=deal_address, subject=body.Subject
            )
            for att in attachments
        ]
    except StorageUnavailable:
        # 5xx so Postmark redelivers later — content-addressed dedup makes the
        # re-processing of already-stored attachments idempotent, so nothing is lost.
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; retry delivery"
        ) from None
    first = items[0]
    return {
        "ignored": False,
        "id": first["id"],
        "status": first["status"],
        "items": items,
        **({"duplicate": True} if first.get("duplicate") else {}),
    }


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


class ManualFieldEntry(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)


class ConfirmRequest(BaseModel):
    # "new" (NEW_TRANSACTION) or an existing transaction id — the TC's HITL call.
    decision: str = Field(min_length=1)
    # TC's correction/confirmation of the detected type (e.g. for 'unknown').
    doc_type: DocType | None = None
    # Manual field-entry fallback (bad scans / failed extraction): the TC types
    # the §5 values. Typing them IS the confirmation — they land confirmed.
    manual_fields: list[ManualFieldEntry] | None = None


def _manual_extracted_fields(entries: list[ManualFieldEntry]) -> list[ExtractedField]:
    invalid = sorted({e.name for e in entries} - EXTRACTABLE_FIELD_NAMES)
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"manual_fields contains names outside the verified §5 list: {', '.join(invalid)}"
            ),
        )
    return [
        ExtractedField(name=e.name, value=e.value, confidence=1.0, confirmed=True) for e in entries
    ]


def _extraction_error(message: str, reasons: list[str]) -> HTTPException:
    """§4 never-silently-guess states: structured 422 the UI can act on."""
    return HTTPException(
        status_code=422,
        detail={
            "message": message,
            "reasons": reasons,
            "manual_fields_required": True,
        },
    )


def _classify_document(
    item: dict[str, Any], inbox: InboxRepo, extractor: Extractor
) -> DocType:
    """Content-level classification for the TC's 'Other — let Terra identify it'
    choice: the model reads the document and reports what it actually is. This is
    best-effort — an unreadable, blocked, or unrecognizable document files as
    'other' rather than blocking the confirm."""
    storage_path = item.get("storage_path")
    if not storage_path:
        return OTHER_DOC_TYPE
    try:
        pdf_bytes = inbox.download_attachment(storage_path)
    except StorageUnavailable:
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    readable = decrypt_pdf(pdf_bytes)
    if readable is None:
        return OTHER_DOC_TYPE
    try:
        result = extractor.extract(pdf_bytes=readable, doc_type=OTHER_DOC_TYPE)
    except (ExtractionFailed, ExtractionBlocked):
        return OTHER_DOC_TYPE
    looks = result.doc_looks_like
    return looks if looks in {  # doc_looks_like is already schema-constrained
        "purchase_agreement", "counter_offer", "proof_of_funds",
        "disclosure", "inspection_report",
    } else OTHER_DOC_TYPE


def _extract_counter(
    item: dict[str, Any], inbox: InboxRepo, extractor: Extractor
) -> tuple[list[ExtractedField], CounterMeta]:
    """Extract a counter offer's overriding §5 fields (new price, changed dates)
    AND its chain/expiration facts. Uses the same model extractor as a PA but
    WITHOUT the purchase-agreement gates — a counter is short, reads as a counter,
    and legitimately restates only the changed terms. Fields come back confirmed:
    they are the agreed terms and supersede the PA. The metadata drives the
    fell-through / further-counter risk flags the master raises."""
    storage_path = item.get("storage_path")
    if not storage_path:
        raise _extraction_error(
            "No stored document for this item", ["no attachment file is stored"]
        )
    try:
        pdf_bytes = inbox.download_attachment(storage_path)
    except StorageUnavailable:
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    readable = decrypt_pdf(pdf_bytes)
    if readable is None:
        raise _extraction_error(
            "The document is password-protected",
            ["the PDF requires a password to open — upload an unlocked copy"],
        )
    # §4 "never guess" applies to EVERY doc type, not just the PA (BUG-23): a
    # scanned/no-text or non-PDF counter/CR/preapproval/prelim/inspection must
    # route to manual entry rather than being guessed at by the model.
    reasons = precheck_pdf(readable, expect_purchase_agreement=False)
    if reasons:
        raise _extraction_error(
            "The document failed pre-checks — extraction was not attempted", reasons
        )
    try:
        result = extractor.extract(pdf_bytes=readable, doc_type="seller_counter_offer")
        meta = extractor.extract_counter_meta(pdf_bytes=readable)
    except ExtractionBlocked as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    fields = [
        ExtractedField(name=f.name, value=f.value, confidence=f.confidence, confirmed=True)
        for f in result.fields
    ]
    return fields, meta


def _extract_contingency_removal_fields(
    item: dict[str, Any], inbox: InboxRepo, extractor: Extractor
) -> list[ExtractedField]:
    """Turn a Contingency Removal (CR-B) into confirmed field overrides: each
    removed contingency's §5 day-field becomes 'removed' (which the timeline skips
    like a waiver) and its *_present flag becomes 'false'. These supersede the PA
    via the master's latest-confirmed rule, so removed contingencies drop off the
    timeline on the next build — the buyer can no longer back out on that basis."""
    storage_path = item.get("storage_path")
    if not storage_path:
        raise _extraction_error(
            "No stored document for this item", ["no attachment file is stored"]
        )
    try:
        pdf_bytes = inbox.download_attachment(storage_path)
    except StorageUnavailable:
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    readable = decrypt_pdf(pdf_bytes)
    if readable is None:
        raise _extraction_error(
            "The document is password-protected",
            ["the PDF requires a password to open — upload an unlocked copy"],
        )
    # §4 "never guess" applies to EVERY doc type, not just the PA (BUG-23): a
    # scanned/no-text or non-PDF counter/CR/preapproval/prelim/inspection must
    # route to manual entry rather than being guessed at by the model.
    reasons = precheck_pdf(readable, expect_purchase_agreement=False)
    if reasons:
        raise _extraction_error(
            "The document failed pre-checks — extraction was not attempted", reasons
        )
    try:
        cr = extractor.extract_contingency_removal(pdf_bytes=readable)
    except ExtractionBlocked as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None

    removed = {
        "loan": cr.all_contingencies_removed or cr.loan_removed,
        "appraisal": cr.all_contingencies_removed or cr.appraisal_removed,
        "inspection": cr.all_contingencies_removed or cr.inspection_removed,
        "insurance": cr.all_contingencies_removed or cr.insurance_removed,
    }
    fields: list[ExtractedField] = []
    for key, gone in removed.items():
        if not gone:
            continue
        fields.append(
            ExtractedField(name=f"{key}_contingency_days", value="removed", confidence=1.0, confirmed=True)
        )
        fields.append(
            ExtractedField(name=f"{key}_contingency_present", value="false", confidence=1.0, confirmed=True)
        )
    return fields


def _extract_preapproval(
    item: dict[str, Any], inbox: InboxRepo, extractor: Extractor
) -> tuple[list[ExtractedField], PreapprovalMeta]:
    """Read a preapproval / underwriter letter. Produces the loan-officer contact
    as §5 lender fields (so the master derives a lender party — NMLS folded into
    the company), and returns the facts the master validates against the deal
    (approved buyer, expiration, approved amount)."""
    storage_path = item.get("storage_path")
    if not storage_path:
        raise _extraction_error(
            "No stored document for this item", ["no attachment file is stored"]
        )
    try:
        pdf_bytes = inbox.download_attachment(storage_path)
    except StorageUnavailable:
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    readable = decrypt_pdf(pdf_bytes)
    if readable is None:
        raise _extraction_error(
            "The document is password-protected",
            ["the PDF requires a password to open — upload an unlocked copy"],
        )
    # §4 "never guess" applies to EVERY doc type, not just the PA (BUG-23): a
    # scanned/no-text or non-PDF counter/CR/preapproval/prelim/inspection must
    # route to manual entry rather than being guessed at by the model.
    reasons = precheck_pdf(readable, expect_purchase_agreement=False)
    if reasons:
        raise _extraction_error(
            "The document failed pre-checks — extraction was not attempted", reasons
        )
    try:
        pa = extractor.extract_preapproval(pdf_bytes=readable)
    except ExtractionBlocked as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None

    fields: list[ExtractedField] = []
    if pa.officer_name:
        company = pa.officer_company or ""
        if pa.officer_nmls:
            company = f"{company} · NMLS {pa.officer_nmls}".strip(" ·")
        # derive_parties splits "name, company" on the first comma.
        contact = f"{pa.officer_name}, {company}" if company else pa.officer_name
        fields.append(ExtractedField(name="lender_contact", value=contact, confidence=1.0, confirmed=True))
        if pa.officer_email:
            fields.append(ExtractedField(name="lender_contact_email", value=pa.officer_email, confidence=1.0, confirmed=True))
        if pa.officer_phone:
            fields.append(ExtractedField(name="lender_contact_phone", value=pa.officer_phone, confidence=1.0, confirmed=True))
    meta = PreapprovalMeta(
        buyer_names=pa.buyer_names, expiration=pa.expiration, loan_amount=pa.loan_amount
    )
    return fields, meta


def _extract_preliminary(
    item: dict[str, Any], inbox: InboxRepo, extractor: Extractor
) -> PreliminaryMeta:
    """Read a preliminary ('title') report — validation-only (no field overrides,
    no party). Returns the facts the master cross-checks against the deal: the
    effective date (recency), the vested owner (should be the seller), and the APN."""
    storage_path = item.get("storage_path")
    if not storage_path:
        raise _extraction_error(
            "No stored document for this item", ["no attachment file is stored"]
        )
    try:
        pdf_bytes = inbox.download_attachment(storage_path)
    except StorageUnavailable:
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    readable = decrypt_pdf(pdf_bytes)
    if readable is None:
        raise _extraction_error(
            "The document is password-protected",
            ["the PDF requires a password to open — upload an unlocked copy"],
        )
    # §4 "never guess" applies to EVERY doc type, not just the PA (BUG-23): a
    # scanned/no-text or non-PDF counter/CR/preapproval/prelim/inspection must
    # route to manual entry rather than being guessed at by the model.
    reasons = precheck_pdf(readable, expect_purchase_agreement=False)
    if reasons:
        raise _extraction_error(
            "The document failed pre-checks — extraction was not attempted", reasons
        )
    try:
        pr = extractor.extract_preliminary(pdf_bytes=readable)
    except ExtractionBlocked as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return PreliminaryMeta(effective_date=pr.effective_date, vestee=pr.vestee, apn=pr.apn)


def _extract_inspection(
    item: dict[str, Any], inbox: InboxRepo, extractor: Extractor, role: str
) -> tuple[list[PartyRef], InspectionMeta]:
    """Read a property or termite inspection report: creates the inspector party
    (the individual if named, else the company) and returns the facts the master
    validates (inspected address matches the property; inspection is recent)."""
    storage_path = item.get("storage_path")
    if not storage_path:
        raise _extraction_error(
            "No stored document for this item", ["no attachment file is stored"]
        )
    try:
        pdf_bytes = inbox.download_attachment(storage_path)
    except StorageUnavailable:
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    readable = decrypt_pdf(pdf_bytes)
    if readable is None:
        raise _extraction_error(
            "The document is password-protected",
            ["the PDF requires a password to open — upload an unlocked copy"],
        )
    # §4 "never guess" applies to EVERY doc type, not just the PA (BUG-23): a
    # scanned/no-text or non-PDF counter/CR/preapproval/prelim/inspection must
    # route to manual entry rather than being guessed at by the model.
    reasons = precheck_pdf(readable, expect_purchase_agreement=False)
    if reasons:
        raise _extraction_error(
            "The document failed pre-checks — extraction was not attempted", reasons
        )
    try:
        insp = extractor.extract_inspection(pdf_bytes=readable)
    except ExtractionBlocked as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None

    parties: list[PartyRef] = []
    party_name = insp.inspector_name or insp.inspector_company
    if party_name:
        parties.append(
            PartyRef(
                role=role,
                name=party_name,
                company=insp.inspector_company,
                email=insp.inspector_email,
                phone=insp.inspector_phone,
            )
        )
    meta = InspectionMeta(
        property_address=insp.property_address, inspection_date=insp.inspection_date
    )
    return parties, meta


def _extract_pa_fields(
    item: dict[str, Any], inbox: InboxRepo, extractor: Extractor
) -> tuple[list[ExtractedField], bool]:
    """Run pre-check + real extraction for a purchase agreement. Raises the
    structured 422 for every §4 error state; never guesses. Returns the fields and
    whether the PA is subject to a (not-yet-uploaded) counter offer."""
    storage_path = item.get("storage_path")
    if not storage_path:
        raise _extraction_error(
            "No stored document for this item", ["no attachment file is stored"]
        )
    try:
        pdf_bytes = inbox.download_attachment(storage_path)
    except StorageUnavailable:
        # Same retryable semantics as the webhook path for the same failure.
        raise HTTPException(
            status_code=503, detail="Attachment store unavailable; try again shortly"
        ) from None
    # Unlock owner-password-only PDFs (common with zipForm/DocuSign) so the model
    # gets readable bytes; only a real user password forces manual entry.
    readable = decrypt_pdf(pdf_bytes)
    if readable is None:
        raise _extraction_error(
            "The document is password-protected",
            ["the PDF requires a password to open — upload an unlocked copy, or enter fields manually"],
        )
    pdf_bytes = readable
    reasons = precheck_pdf(pdf_bytes, expect_purchase_agreement=True)
    if reasons:
        raise _extraction_error(
            "The document failed pre-checks — extraction was not attempted", reasons
        )
    try:
        result = extractor.extract(pdf_bytes=pdf_bytes, doc_type="purchase_agreement")
    except ExtractionBlocked as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except ExtractionFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    if result.doc_looks_like != "purchase_agreement":
        raise _extraction_error(
            "Wrong document type",
            [
                f"the document reads as '{result.doc_looks_like}', not a purchase "
                "agreement — correct doc_type, or dismiss this item"
            ],
        )
    if not result.signature_detected:
        raise _extraction_error(
            "No executed-signature indicators found",
            [
                "the document does not appear to be a signed copy — verify it is "
                "executed; to proceed deliberately, enter the fields manually"
            ],
        )
    if not result.fields:
        # Passed pre-checks (has pages + a text layer) yet nothing mapped — don't
        # create a hollow deal with a placeholder address (BUG-22); route to manual.
        raise _extraction_error(
            "No fields could be read from this document",
            [
                "the document passed pre-checks but no §5 fields were extracted — "
                "enter the fields manually, or upload a clearer copy"
            ],
        )
    return result.fields, result.subject_to_counter_offer


@router.post("/inbox/{item_id}/confirm")
def confirm_inbox_item(
    item_id: str,
    body: ConfirmRequest,
    tc: TCUser = Depends(require_tc),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    inbox: InboxRepo = Depends(get_inbox_repo),
    master: HttpMasterClient = Depends(get_master_client),
    extractor: Extractor = Depends(get_extractor),
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
    if doc_type == OTHER_DOC_TYPE:
        # The TC asked Terra to identify it — classify from the content itself.
        doc_type = _classify_document(item, inbox, extractor)
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
        # §5 fields come only from a purchase agreement (real extraction,
        # Phase 4). Other doc types attach field-less. Manual entry skips
        # extraction: the TC's typed values are the confirmed truth.
        if doc_type != "purchase_agreement" and body.manual_fields:
            raise HTTPException(
                status_code=422,
                detail=(
                    "manual_fields apply only to purchase agreements — "
                    f"this item is a {doc_type}"
                ),
            )
        counter_meta: CounterMeta | None = None
        preapproval_meta: PreapprovalMeta | None = None
        preliminary_meta: PreliminaryMeta | None = None
        inspection_meta: InspectionMeta | None = None
        new_parties: list[PartyRef] = []
        pa_subject_to_counter = False
        if doc_type == "purchase_agreement":
            if body.manual_fields:
                fields: list[ExtractedField] = _manual_extracted_fields(body.manual_fields)
            else:
                fields, pa_subject_to_counter = _extract_pa_fields(item, inbox, extractor)
        elif doc_type in COUNTER_OFFER_TYPES:
            # A counter offer restates the changed terms (e.g. a new price); its
            # fields supersede the PA's via the master's latest-confirmed rule, and
            # its metadata drives the fell-through / further-counter flags.
            fields, counter_meta = _extract_counter(item, inbox, extractor)
        elif doc_type == "contingency_removal":
            # Removed contingencies override the PA to 'removed' → drop off the timeline.
            fields = _extract_contingency_removal_fields(item, inbox, extractor)
        elif doc_type == "preapproval":
            # Creates the loan-officer party (via §5 lender fields) and carries the
            # facts the master validates against the deal (name/expiry/amount).
            fields, preapproval_meta = _extract_preapproval(item, inbox, extractor)
        elif doc_type == "preliminary_report":
            # Validation-only: APN / vested-owner / recency cross-checks in the master.
            preliminary_meta = _extract_preliminary(item, inbox, extractor)
            fields = []
        elif doc_type in ("property_inspection", "termite_inspection"):
            role = "inspector_general" if doc_type == "property_inspection" else "inspector_termite"
            new_parties, inspection_meta = _extract_inspection(item, inbox, extractor, role)
            fields = []
        else:
            fields = []

        address = next(
            (f.value for f in fields if f.name == "property_address"),
            "(address pending confirmation)",
        )

        if body.decision == NEW_TRANSACTION:
            # §11 step 2: a new deal is proposed from a purchase agreement; the
            # TC may still create one from another doc type, but only explicitly.
            status, data = master.create_transaction(token=token, property_address=address)
            if status >= 400:
                raise HTTPException(status_code=status, detail=data.get("detail", "master error"))
            transaction_id = data["id"]
        else:
            transaction_id = body.decision

        payload = Payload(
            document_id=f"inbox-{item_id}",
            transaction_id=transaction_id,
            extracted_fields=fields,
            document_type=doc_type,
            document_storage_ref=item.get("storage_path"),
            counter_meta=counter_meta,
            preapproval_meta=preapproval_meta,
            preliminary_meta=preliminary_meta,
            inspection_meta=inspection_meta,
            parties=new_parties,
            pa_subject_to_counter=pa_subject_to_counter,
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
