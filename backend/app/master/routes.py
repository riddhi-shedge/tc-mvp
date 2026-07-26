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
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.common.auth import TCUser, require_tc
from app.common.zdr import ZdrNotConfirmed
from app.contracts.compliance import ComplianceResult
from app.contracts.fields import EXTRACTABLE_FIELD_NAMES
from app.contracts.payload import Payload
from app.master.dashboard import build_dashboard
from app.master.drafting import (
    ClaudeDrafter,
    DraftContext,
    DraftFailed,
    Drafter,
    MessageContext,
)
from app.master.parties import ROLE_TIERS
from app.master.party_access import (
    AccessIssuanceFailed,
    AccessIssuerNotConfigured,
    PartyAccessIssuer,
    SupabasePartyAccessIssuer,
)
from app.master.mailer import (
    Mailer,
    PostmarkMailer,
    RecipientNotAllowed,
    SendDisabled,
    SendFailed,
)
from app.master.repo import (
    DEAL_STAGES,
    DeadlineFieldsUnconfirmed,
    MasterRepo,
    MessageNotSendable,
    NoPayloadForManualField,
    NoRecipient,
    SupabaseRepo,
    TimelineAlreadyExists,
)

# The compliance part runs as its own process (the daily scheduler); the master
# never imports its internals. The on-demand "Build timeline" action shells out
# to that same entrypoint for one deal — process isolation keeps the parts
# decoupled, exactly like the cron sweep.
_BACKEND_DIR = Path(__file__).resolve().parents[2]

router = APIRouter()


@lru_cache(maxsize=1)
def _default_mailer() -> PostmarkMailer:
    return PostmarkMailer()


def get_mailer() -> Mailer:
    return _default_mailer()


@lru_cache(maxsize=1)
def _default_drafter() -> ClaudeDrafter:
    return ClaudeDrafter()


def get_drafter() -> Drafter:
    return _default_drafter()


@lru_cache(maxsize=1)
def _default_party_access_issuer() -> SupabasePartyAccessIssuer:
    return SupabasePartyAccessIssuer()


def get_party_access_issuer() -> PartyAccessIssuer:
    return _default_party_access_issuer()


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


@router.post("/transactions/{transaction_id}/archive")
def archive_transaction(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Soft-remove: hide from the active list, keep the full audit trail."""
    txn = repo.archive_transaction(transaction_id=transaction_id, actor=tc.actor)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.post("/transactions/{transaction_id}/unarchive")
def unarchive_transaction(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    txn = repo.unarchive_transaction(transaction_id=transaction_id, actor=tc.actor)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.delete("/transactions/{transaction_id}", status_code=204)
def delete_transaction(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> None:
    """Hard delete — cascades every child row incl. the audit log. Irreversible;
    for synthetic/test cleanup. Archive is the compliance-safe alternative."""
    if not repo.delete_transaction(transaction_id=transaction_id, actor=tc.actor):
        raise HTTPException(status_code=404, detail="Transaction not found")


# NOTE: these static paths are registered BEFORE GET /transactions/{id} so
# "board"/"calendar" are not captured as a transaction id.
@router.get("/transactions/board")
def deals_board(
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> list[dict[str, Any]]:
    """Enriched per-deal rollups for the pipeline board (COE, price, tasks, risks, stage)."""
    return repo.list_deal_summaries()


@router.get("/transactions/calendar")
def deals_calendar(
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> list[dict[str, Any]]:
    """Every deadline across non-archived deals, for the cross-deal calendar."""
    return repo.list_active_deadlines()


class StageRequest(BaseModel):
    stage: str = Field(min_length=1)


@router.post("/transactions/{transaction_id}/stage")
def set_stage(
    transaction_id: str,
    body: StageRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Move a deal to a pipeline stage (drag on the board)."""
    if body.stage not in DEAL_STAGES:
        raise HTTPException(status_code=422, detail=f"stage must be one of {list(DEAL_STAGES)}")
    txn = repo.set_transaction_stage(
        transaction_id=transaction_id, stage=body.stage, actor=tc.actor
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


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
    # Confirmed names/agents/escrow/title become real Party records (idempotent),
    # then allocation-rule tasks (assigned to those agents where present).
    parties_created = repo.derive_parties_from_fields(transaction_id=transaction_id, actor=tc.actor)
    tasks_created = repo.derive_tasks_from_fields(transaction_id=transaction_id, actor=tc.actor)
    return {"confirmed": count, "parties_created": parties_created, "tasks_created": tasks_created}


class AddFieldRequest(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)


@router.post("/transactions/{transaction_id}/fields", status_code=201)
def add_field(
    transaction_id: str,
    body: AddFieldRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Hand-enter a §5 field the extraction missed (e.g. an acceptance date the
    model couldn't find) so a real deal's timeline can be built without a script.
    Whitelisted to the human-verified §5 names; Rule 2 money/wiring guard on both
    name and value; a name already on the deal is a confirm, not an add."""
    name = body.name.strip()
    value = body.value.strip()
    if name not in EXTRACTABLE_FIELD_NAMES:
        raise HTTPException(status_code=422, detail=f"'{name}' is not a §5 extractable field")
    if _MONEY_FIELD_NAME.search(name) or _MONEY_FIELD_NAME.search(value):
        raise HTTPException(
            status_code=422,
            detail="Payment/wiring data is never stored (Rule 2).",
        )
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if any(f["name"] == name for f in state["extracted_fields"]):
        raise HTTPException(
            status_code=409,
            detail=f"'{name}' is already on this deal — confirm it instead of re-adding.",
        )
    try:
        field = repo.add_manual_field(
            transaction_id=transaction_id, name=name, value=value, actor=tc.actor
        )
    except NoPayloadForManualField:
        raise HTTPException(
            status_code=409,
            detail="Upload the purchase agreement first — then missing fields can be added.",
        )
    fresh = repo.get_full_state(transaction_id) or {}
    return {"field": field, "timeline_gate": fresh.get("timeline_gate")}


@router.post("/transactions/{transaction_id}/build-timeline")
def build_timeline(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Run compliance on demand for one deal (the TC's "Build timeline" tap), once
    every deadline-driving field is present and confirmed. Spawns the compliance
    scheduler for this deal — same seam as the daily cron — so the master stays
    decoupled from compliance internals."""
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    gate = state.get("timeline_gate") or {}
    if not gate.get("ready", False):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Timeline needs every deadline-driving field present and confirmed first.",
                "missing_fields": gate.get("missing_fields", []),
                "unconfirmed_fields": gate.get("unconfirmed_fields", []),
            },
        )
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.compliance.scheduler", transaction_id],
            cwd=str(_BACKEND_DIR),
            env={**os.environ},
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeline build timed out — try again")
    if proc.returncode != 0:
        # Never echo subprocess output to the client — it can carry ids (Rule 5).
        raise HTTPException(status_code=502, detail="Timeline build failed — see server logs")
    fresh = repo.get_full_state(transaction_id) or {}
    return {
        "deadlines": len(fresh.get("deadlines", [])),
        "tasks": len(fresh.get("tasks", [])),
        "risk_flags": len(fresh.get("risk_flags", [])),
    }


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


_EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class CreatePartyRequest(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    # Light shape check (avoids the email-validator dep) — caught at entry so
    # the TC fixes a typo now, not at send time.
    email: str | None = Field(default=None, pattern=_EMAIL_RE)
    phone: str | None = None
    company: str | None = None
    permission_tier: str | None = None


class UpdatePartyRequest(BaseModel):
    """Partial update — only the provided fields change (fill a placeholder's
    phone/email/brokerage, correct a name). exclude_unset drives the patch."""

    name: str | None = Field(default=None, min_length=1)
    role: str | None = Field(default=None, min_length=1)
    email: str | None = Field(default=None, pattern=_EMAIL_RE)
    phone: str | None = None
    company: str | None = None


@router.post("/transactions/{transaction_id}/parties", status_code=201)
def create_party(
    transaction_id: str,
    body: CreatePartyRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    tier = body.permission_tier or ROLE_TIERS.get(body.role, "email_participant")
    return repo.create_party(
        transaction_id=transaction_id,
        name=body.name,
        role=body.role,
        email=body.email,
        phone=body.phone,
        company=body.company,
        permission_tier=tier,
        actor=tc.actor,
    )


@router.patch("/transactions/{transaction_id}/parties/{party_id}")
def update_party(
    transaction_id: str,
    party_id: str,
    body: UpdatePartyRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Fill in or correct a party's details (a derived contact or an empty
    roster slot the TC is completing)."""
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422, detail="No fields to update")
    updated = repo.update_party(
        transaction_id=transaction_id, party_id=party_id, fields=fields, actor=tc.actor
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Party not found on this transaction")
    return updated


@router.post("/transactions/{transaction_id}/parties/{party_id}/access-token", status_code=201)
def create_party_access_token(
    transaction_id: str,
    party_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    issuer: PartyAccessIssuer = Depends(get_party_access_issuer),
) -> dict[str, Any]:
    """Issue a scoped receiving-end access token (§8) — the magic-link credential.
    A Supabase-issued session whose admin-set app_metadata.party_id RLS keys off;
    the token grants nothing but that party's own task (enforced in the DB)."""
    party = repo.get_party(party_id=party_id, transaction_id=transaction_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found on this transaction")
    # §8: only receiving-end parties get a live DB credential. Other tiers
    # (email participants: buyer/seller/lender/title/escrow) are out of scope.
    if party.get("permission_tier") != "receiving_end":
        raise HTTPException(
            status_code=409, detail="Access tokens are only for receiving-end parties"
        )
    try:
        result = issuer.issue(party_id=party_id, transaction_id=transaction_id, email=None)
    except AccessIssuerNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except AccessIssuanceFailed:
        # Generic detail — never surface the raw provider exception (Rule 5).
        raise HTTPException(status_code=502, detail="Could not issue access token") from None
    repo.record_access_token_issued(
        transaction_id=transaction_id, party_id=party_id, actor=tc.actor
    )
    return result


class AssignTaskRequest(BaseModel):
    party_id: str = Field(min_length=1)


_TASK_STATUSES = frozenset({"pending", "in_progress", "done", "blocked"})


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1)
    deadline_id: str | None = None
    assigned_party_id: str | None = None


class UpdateTaskRequest(BaseModel):
    status: str = Field(min_length=1)


@router.post("/transactions/{transaction_id}/tasks", status_code=201)
def create_task(
    transaction_id: str,
    body: CreateTaskRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """A TC's own ad-hoc task, alongside the compliance-generated ones."""
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    if body.assigned_party_id is not None and not repo.party_belongs_to_transaction(
        party_id=body.assigned_party_id, transaction_id=transaction_id
    ):
        raise HTTPException(status_code=404, detail="Party not found on this transaction")
    return repo.create_task(
        transaction_id=transaction_id,
        title=body.title.strip(),
        deadline_id=body.deadline_id,
        assigned_party_id=body.assigned_party_id,
        actor=tc.actor,
    )


@router.patch("/transactions/{transaction_id}/tasks/{task_id}")
def update_task(
    transaction_id: str,
    task_id: str,
    body: UpdateTaskRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if body.status not in _TASK_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"status must be one of {sorted(_TASK_STATUSES)}"
        )
    task = repo.set_task_status(
        transaction_id=transaction_id, task_id=task_id, status=body.status, actor=tc.actor
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/transactions/{transaction_id}/tasks/{task_id}/assign")
def assign_task(
    transaction_id: str,
    task_id: str,
    body: AssignTaskRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if not repo.party_belongs_to_transaction(party_id=body.party_id, transaction_id=transaction_id):
        raise HTTPException(status_code=404, detail="Party not found on this transaction")
    task = repo.assign_task(
        transaction_id=transaction_id, task_id=task_id, party_id=body.party_id, actor=tc.actor
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/transactions/{transaction_id}/dashboard")
def read_dashboard(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return build_dashboard(state)


@router.post("/transactions/{transaction_id}/messages/draft-lender", status_code=201)
def draft_lender(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    drafter: Drafter = Depends(get_drafter),
) -> dict[str, Any]:
    """Real Claude draft of a lender status request (Prompt 6). If no lender
    contact, ask for one (Rule 6: never guess a recipient)."""
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    lender = repo.lender_party(transaction_id)
    if lender is None:
        raise HTTPException(
            status_code=409,
            detail="No lender contact on this deal — add one (POST /parties) before drafting.",
        )
    state = repo.get_full_state(transaction_id)
    assert state is not None
    prop = state.get("property") or {}
    ctx = DraftContext(
        property_address=prop.get("address"),
        lender_name=lender.get("name"),
        loan_deadline=repo.loan_deadline_iso(transaction_id),
        loan_status_note=None,
    )
    try:
        draft = drafter.draft_lender_status(ctx)
    except ZdrNotConfirmed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except DraftFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    money_hit = _MONEY_FIELD_NAME.search(f"{draft.subject}\n{draft.body}")
    if money_hit:
        # Rule 2 defense in depth: never persist/send a draft that slipped in
        # wiring/payment language, even though the prompt forbids it.
        raise HTTPException(
            status_code=422,
            detail="Draft contained payment/wiring language and was rejected (Rule 2).",
        )
    message = repo.create_message(
        transaction_id=transaction_id,
        subject=draft.subject,
        body=draft.body,
        party_id=lender["id"],
        actor=tc.actor,
        details={"kind": "lender_status"},
    )
    return {"message": message, "why": draft.why}


def _message_context(
    state: dict[str, Any], party: dict[str, Any], purpose: str, tc: TCUser
) -> MessageContext:
    parties = state.get("parties", [])

    def _names(role: str) -> str | None:
        vals = [p["name"] for p in parties if p.get("role") == role and p.get("name")]
        return ", ".join(vals) or None

    prop = state.get("property") or {}
    key_dates = tuple(
        (d["name"], d["due_date"]) for d in state.get("deadlines", []) if d.get("due_date")
    )
    return MessageContext(
        purpose=purpose,
        recipient_name=party.get("name"),
        recipient_role=party.get("role"),
        property_address=prop.get("address"),
        buyer_names=_names("buyer"),
        seller_names=_names("seller"),
        # Optional TC identity for the signature/intro (set TC_NAME to personalize).
        tc_name=os.environ.get("TC_NAME") or None,
        key_dates=key_dates,
    )


class DraftMessageRequest(BaseModel):
    party_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


@router.post("/transactions/{transaction_id}/messages/draft", status_code=201)
def draft_message(
    transaction_id: str,
    body: DraftMessageRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    drafter: Drafter = Depends(get_drafter),
) -> dict[str, Any]:
    """Personalized draft to any party on the deal, for a chosen purpose. Rule 6:
    the recipient must be a real party with an email (never guessed)."""
    party = repo.get_party(party_id=body.party_id, transaction_id=transaction_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found on this transaction")
    if not party.get("email"):
        raise HTTPException(
            status_code=409,
            detail="This recipient has no email yet — add one on the Parties tab first.",
        )
    state = repo.get_full_state(transaction_id)
    assert state is not None
    ctx = _message_context(state, party, body.purpose, tc)
    try:
        draft = drafter.draft_message(ctx)
    except ZdrNotConfirmed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except DraftFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    if _MONEY_FIELD_NAME.search(f"{draft.subject}\n{draft.body}"):
        raise HTTPException(
            status_code=422,
            detail="Draft contained payment/wiring language and was rejected (Rule 2).",
        )
    message = repo.create_message(
        transaction_id=transaction_id,
        subject=draft.subject,
        body=draft.body,
        party_id=party["id"],
        actor=tc.actor,
        details={"kind": body.purpose},
    )
    return {"message": message, "why": draft.why}


class ApproveSendRequest(BaseModel):
    # The TC's edits ARE the approved content (optional; defaults to the draft).
    subject: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)


@router.post("/transactions/{transaction_id}/messages/{message_id}/approve-and-send")
def approve_and_send(
    transaction_id: str,
    message_id: str,
    body: ApproveSendRequest | None = None,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    mailer: Any = Depends(get_mailer),
) -> dict[str, Any]:
    """The human approval + real (guarded) send (Rule 3). The ONLY path that can
    transition a message to 'sent'. The TC's optional edits are the approved
    content. On a guarded/failed send the message stays 'approved' (retryable)."""
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    edits = body or ApproveSendRequest()
    try:
        result = repo.approve_and_send(
            transaction_id=transaction_id,
            message_id=message_id,
            actor=tc.actor,
            subject=edits.subject,
            body=edits.body,
            mailer=mailer,
            followup_days=int(os.environ.get("FOLLOWUP_DAYS", "3")),
        )
    except MessageNotSendable:
        raise HTTPException(
            status_code=409, detail="Message has already been sent — cannot send again"
        ) from None
    except NoRecipient:
        raise HTTPException(
            status_code=409, detail="Message has no recipient — add a contact with an email first"
        ) from None
    except SendDisabled as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except RecipientNotAllowed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except SendFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
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


@router.get("/transactions/compliance-active")
def list_compliance_active(
    _: None = Depends(require_compliance_service),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Open transaction IDs for the scheduled compliance runner to sweep.
    Service-token auth (a machine can't do MFA); IDs only, no deal content.
    Declared before GET /transactions/{id} so the static path isn't shadowed."""
    return {"transaction_ids": repo.list_active_transaction_ids()}


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
    written = repo.write_payload(transaction_id=transaction_id, payload=payload, actor=tc.actor)
    # Manual-entry fields arrive confirmed — derive parties then rule tasks.
    repo.derive_parties_from_fields(transaction_id=transaction_id, actor=tc.actor)
    repo.derive_tasks_from_fields(transaction_id=transaction_id, actor=tc.actor)
    return written
