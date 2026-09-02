"""Master API routes — Prompt 1: create transaction, write validated Payload,
read full deal state. The only path to the SOR; every route requires TC auth.

Payloads are the only write path for deal data, validated at the boundary
(rules/architecture.md). A NEW payload never commits here: transaction creation
from ingestion is HITL and arrives with Phase 3.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

from app.common.dates import ca_today
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.common.auth import PartyUser, TCUser, require_agent_portfolio, require_party, require_tc
from app.master.agent_portfolio import (
    agent_earnings,
    agent_schedule,
    listing_earnings,
    seller_context,
    build_agent_portfolio,
    build_listing_portfolio,
    build_offer_comparison,
    client_context,
    deal_summary,
    draft_targets,
)
from app.master.attention import build_attention
from app.master.authority import UnauthorizedWrite, require_originate
from app.master.event_catalog import agent_activity
from app.master.party_views import _seller_deal_health
from app.common.zdr import ZdrNotConfirmed
from app.contracts.compliance import ComplianceResult
from app.contracts.fields import EXTRACTABLE_FIELD_NAMES
from app.contracts.payload import Payload
from app.master.dashboard import build_dashboard
from app.master.assistant import AssistantError, ClaudeAssistant, DealAssistant, build_context
from app.master.story import (
    ClaudeStoryteller,
    StoryFailed,
    Storyteller,
    build_story_digest,
)
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
from app.master.party_views import build_party_workspace
from app.master.repo import (
    DEAL_STAGES,
    ComplianceRunInProgress,
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
_log = logging.getLogger(__name__)


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


def get_storyteller() -> Storyteller:
    return ClaudeStoryteller()


@lru_cache(maxsize=1)
def _default_assistant() -> ClaudeAssistant:
    return ClaudeAssistant()


def get_assistant() -> DealAssistant:
    return _default_assistant()


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

# Wiring/PII smuggled into a whitelisted field's VALUE (e.g. a routing/account
# number or SSN pasted into other_terms). Deliberately TARGETED — a bank/account
# LABEL adjacent to digits, or an SSN — so it does NOT reject legitimate values
# like "Wells Fargo Bank", an APN "357-13-003", or a phone "415-555-1234".
_WIRING_VALUE = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b"                                   # SSN
    r"|(?:routing|iban|swift|\baba\b)\D{0,15}\d"               # routing/IBAN/SWIFT/ABA label near digits
    r"|account\s*(?:number|no\.?|#)\D{0,10}\d",                # "account number: 12345"
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


class CancelRequest(BaseModel):
    reason: str = ""


@router.post("/transactions/{transaction_id}/cancel")
def cancel_transaction(
    transaction_id: str,
    body: CancelRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The deal fell through / was canceled — a terminal state distinct from
    archive (reactivatable), e.g. the buyer backed out during contingencies."""
    txn = repo.cancel_transaction(
        transaction_id=transaction_id, reason=(body.reason or "").strip(), actor=tc.actor
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.post("/transactions/{transaction_id}/reactivate")
def reactivate_transaction(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    txn = repo.reactivate_transaction(transaction_id=transaction_id, actor=tc.actor)
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


@router.get("/transactions/tasks")
def open_tasks(
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> list[dict[str, Any]]:
    """Open tasks across non-archived deals — the Home work queue."""
    return repo.list_open_tasks()


# ---- P4: deadline .ics feed — deadlines land in the calendar the TC lives in --

def _calendar_feed_token() -> str | None:
    """The feed's bearer secret. CALENDAR_FEED_TOKEN wins if set; otherwise it is
    derived (HMAC) from the service-role key so production needs zero setup. The
    feed is read-only deadline data; the token gates it like a private ICS URL."""
    explicit = os.environ.get("CALENDAR_FEED_TOKEN")
    if explicit:
        return explicit
    secret = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not secret:
        return None
    return hmac.new(secret.encode(), b"terra-calendar-feed", hashlib.sha256).hexdigest()[:32]


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/calendar.ics")
def calendar_ics(
    key: str | None = None,
    repo: MasterRepo = Depends(get_repo),
) -> Response:
    """Token-authenticated ICS feed of every active deal's deadlines — subscribe
    once from Google/Apple Calendar. Read-only; no PII beyond address + deadline
    names; stable UIDs so a recomputed date UPDATES the event instead of duplicating."""
    token = _calendar_feed_token()
    if token is None:
        raise HTTPException(status_code=503, detail="Calendar feed is not configured")
    if not key or not secrets.compare_digest(key, token):
        raise HTTPException(status_code=401, detail="Invalid feed key")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Terra//TC deadlines//EN",
        "X-WR-CALNAME:Terra — deal deadlines",
        "CALSCALE:GREGORIAN",
    ]
    for d in repo.list_active_deadlines():
        due = (d.get("due_date") or "").replace("-", "")[:8]
        if not due:
            continue
        addr = (d.get("property_address") or "").split(",")[0]
        uid = hashlib.sha1(f"{d['transaction_id']}|{d['name']}".encode()).hexdigest()[:16]
        summary = _ics_escape(f"{d['name']}{f' — {addr}' if addr else ''}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@terra-tc",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{due}",
            f"SUMMARY:{summary}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return Response(
        content="\r\n".join(lines) + "\r\n",
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="terra-deadlines.ics"'},
    )


@router.get("/transactions/calendar/feed-url")
def calendar_feed_url(
    request: Request,
    tc: TCUser = Depends(require_tc),
) -> dict[str, Any]:
    """The subscribe URL (with its token) for the TC to paste into their calendar
    app. TC-auth here; the feed itself is gated by the token alone."""
    token = _calendar_feed_token()
    if token is None:
        return {"available": False, "url": None}
    return {"available": True, "url": f"{str(request.base_url).rstrip('/')}/calendar.ics?key={token}"}


@router.get("/transactions/attention")
def attention_queue(
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The TC's decision queue (P1): every pending decision across the book —
    drafts awaiting approval, due follow-up reminders, timeline-gate blockers,
    unresolved risk flags — plus the CA-business-day deadline horizon. Pending
    inbox items stay on the ingestion side; the frontend adds that count."""
    return build_attention(repo.list_full_states())


# ---- Deal notes (P3): TC-only, SOR-backed — never served to parties ----------

class NoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    color: str = Field(default="y", max_length=2)


@router.get("/transactions/{transaction_id}/notes")
def list_notes(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    notes = repo.list_deal_notes(transaction_id)
    if notes is None:
        # Pre-migration: report unavailable rather than 500 — the UI says so.
        return {"available": False, "notes": []}
    return {"available": True, "notes": notes}


OPS_LANES = {"hoa", "warranty", "nhd", "utilities"}


class OpsAdvanceRequest(BaseModel):
    status: str = Field(pattern="^(ordered|done)$")
    occurred_on: str | None = None
    note: str | None = Field(default=None, max_length=300)


@router.post("/transactions/{transaction_id}/ops/{lane}", status_code=201)
def advance_ops_lane(
    transaction_id: str,
    lane: str,
    body: OpsAdvanceRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Wave 3A ops lanes (HOA docs / home warranty / NHD / utilities): one
    ordered->done mini-chain per lane, TC-advanced only."""
    if lane not in OPS_LANES:
        raise HTTPException(status_code=422, detail=f"Unknown lane; lanes are {sorted(OPS_LANES)}")
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        occurred = date.fromisoformat(body.occurred_on) if body.occurred_on else ca_today()
    except ValueError:
        raise HTTPException(status_code=422, detail="occurred_on must be YYYY-MM-DD") from None
    row = repo.advance_ops_item(
        transaction_id=transaction_id, lane=lane, status=body.status,
        occurred_on=occurred.isoformat(), note=(body.note or None), actor=tc.actor,
    )
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="Invalid transition — 'ordered' starts a lane once; 'done' needs it ordered first",
        )
    return row


# Wave 2: the closing chain, in order. Each step is TC-confirmed exactly once;
# a step may only be recorded when every prior step exists (no stranded states).
CLOSING_CHAIN = ["docs_ordered", "cd_delivered", "signed", "funded", "recorded", "keys_released"]

# Federal holidays for the TRID 3-business-day CD review clock (business day =
# every day EXCEPT Sundays and federal legal public holidays — Saturdays COUNT).
# Deliberately separate from ca_legal_holidays. 2026–2027 fixed/observed dates.
_FEDERAL_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26",
    "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-10-11", "2027-11-11",
    "2027-11-25", "2027-12-24",
}


def trid_earliest_signing(cd_delivered: date) -> date:
    """Earliest signing day: 3 TRID business days AFTER CD delivery."""
    d, counted = cd_delivered, 0
    while counted < 3:
        d += timedelta(days=1)
        if d.weekday() != 6 and d.isoformat() not in _FEDERAL_HOLIDAYS:
            counted += 1
    return d


class ClosingStepRequest(BaseModel):
    occurred_on: str | None = None  # ISO date; defaults to today (CA time)
    note: str | None = Field(default=None, max_length=300)


@router.post("/transactions/{transaction_id}/closing/{step}", status_code=201)
def record_closing_step(
    transaction_id: str,
    step: str,
    body: ClosingStepRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Advance the closing chain — TC-confirmed only (escrow emails may suggest,
    the human records). Enforces order, once-per-step, and the federal TRID
    3-business-day CD review before 'signed'."""
    if step not in CLOSING_CHAIN:
        raise HTTPException(status_code=422, detail=f"Unknown step; chain is {CLOSING_CHAIN}")
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    done = {e["step"]: e for e in state.get("closing_events", [])}
    if step in done:
        raise HTTPException(status_code=409, detail=f"'{step}' is already recorded")
    idx = CLOSING_CHAIN.index(step)
    missing = [s for s in CLOSING_CHAIN[:idx] if s not in done]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"Record {missing[0]} first — the chain is strictly ordered"
        )
    try:
        occurred = date.fromisoformat(body.occurred_on) if body.occurred_on else ca_today()
    except ValueError:
        raise HTTPException(status_code=422, detail="occurred_on must be YYYY-MM-DD") from None
    if step == "signed" and "cd_delivered" in done:
        earliest = trid_earliest_signing(date.fromisoformat(done["cd_delivered"]["occurred_on"]))
        if occurred < earliest:
            raise HTTPException(
                status_code=422,
                detail=f"Too early: TRID requires 3 business days of CD review — "
                f"earliest signing is {earliest.isoformat()} (Saturdays count; "
                "Sundays and federal holidays don't).",
            )
    return repo.record_closing_step(
        transaction_id=transaction_id, step=step, occurred_on=occurred.isoformat(),
        note=(body.note or None), actor=tc.actor,
    )


class ServeNoticeRequest(BaseModel):
    deadline_id: str = Field(min_length=1)
    kind: str = Field(default="nbp", pattern="^(nbp|nsp)$")
    served_date: str | None = None  # ISO date; defaults to today (CA time)


@router.post("/transactions/{transaction_id}/notices", status_code=201)
def serve_notice(
    transaction_id: str,
    body: ServeNoticeRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Record that a Notice to (Buyer/Seller) Perform was SERVED — by the agent,
    outside Terra (Terra tracks, never sends). Verified rules D2/D3
    (docs/ca-rules-verification.md): earliest service = 2 days before the
    deadline; cure = 2 calendar days after service."""
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    deadline = next((d for d in state["deadlines"] if d["id"] == body.deadline_id), None)
    if deadline is None:
        raise HTTPException(status_code=404, detail="Deadline not found on this transaction")
    try:
        served = date.fromisoformat(body.served_date) if body.served_date else ca_today()
    except ValueError:
        raise HTTPException(status_code=422, detail="served_date must be YYYY-MM-DD") from None
    earliest = date.fromisoformat(deadline["due_date"]) - timedelta(days=2)  # D2
    if served < earliest:
        raise HTTPException(
            status_code=422,
            detail=f"Too early: an NBP may be served no sooner than {earliest.isoformat()} "
            "(2 days before the deadline, verified rule D2).",
        )
    cure = (served + timedelta(days=2)).isoformat()  # D3
    return repo.create_notice(
        transaction_id=transaction_id, deadline_id=body.deadline_id, kind=body.kind,
        served_date=served.isoformat(), cure_expires=cure, actor=tc.actor,
    )


@router.post("/transactions/{transaction_id}/notices/{notice_id}/cure")
def cure_notice(
    transaction_id: str,
    notice_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    row = repo.cure_notice(transaction_id=transaction_id, notice_id=notice_id, actor=tc.actor)
    if row is None:
        raise HTTPException(status_code=404, detail="Open notice not found on this transaction")
    return row


class CreateRepairRequest(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    source_document_id: str | None = None


@router.post("/transactions/{transaction_id}/repairs", status_code=201)
def create_repair(
    transaction_id: str,
    body: CreateRepairRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Track a repair item (Wave 1 repair loop). Created only by the TC — the
    click IS the HITL that promotes an advisory read fact into a record."""
    if not repo.transaction_exists(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return repo.create_repair(
        transaction_id=transaction_id,
        description=body.description.strip(),
        source_document_id=body.source_document_id,
        actor=tc.actor,
    )


@router.post("/transactions/{transaction_id}/repairs/{repair_id}/resolve")
def resolve_repair(
    transaction_id: str,
    repair_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Human-only by design: repair.resolve is NEVER_BY_MACHINE (§5 authority)."""
    row = repo.resolve_repair(transaction_id=transaction_id, repair_id=repair_id, actor=tc.actor)
    if row is None:
        raise HTTPException(status_code=404, detail="Open repair not found on this transaction")
    return row


@router.post("/transactions/{transaction_id}/notes", status_code=201)
def add_note(
    transaction_id: str,
    body: NoteRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    try:
        return repo.add_deal_note(
            transaction_id=transaction_id, body=body.body.strip(), color=body.color, actor=tc.actor
        )
    except Exception:
        raise HTTPException(
            status_code=503, detail="Notes need the deal_notes migration applied."
        ) from None


@router.post("/transactions/{transaction_id}/messages/{message_id}/draft-chase", status_code=201)
def draft_chase(
    transaction_id: str,
    message_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    drafter: Drafter = Depends(get_drafter),
) -> dict[str, Any]:
    """P2: a sent message got no reply — draft the courteous nudge. The chase is a
    DRAFT like every outbound (Rule 3): it lands in the decision queue for the TC
    to review and approve; nothing sends here."""
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    msg = next((m for m in state.get("messages", []) if m["id"] == message_id), None)
    if msg is None or msg.get("status") != "sent":
        raise HTTPException(status_code=409, detail="Only a sent message can be chased")
    if msg.get("replied_at"):
        raise HTTPException(status_code=409, detail="They already replied — nothing to chase")
    recipient = next((p for p in state.get("parties", []) if p["id"] == msg.get("party_id")), None)
    fields = {k: v.get("value") for k, v in (state.get("effective_fields") or {}).items()}
    ctx = MessageContext(
        purpose="chase",
        recipient_name=(recipient or {}).get("name"),
        recipient_role=(recipient or {}).get("role"),
        property_address=(state.get("property") or {}).get("address") or fields.get("property_address"),
        buyer_names=fields.get("buyer_names"), seller_names=fields.get("seller_names"),
        tc_name=None, key_dates=(),
        note=f"Earlier message (no reply yet): subject '{msg.get('subject')}', sent {str(msg.get('sent_at') or '')[:10]}.",
    )
    try:
        draft = drafter.draft_message(ctx)
    except ZdrNotConfirmed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except DraftFailed:
        raise HTTPException(status_code=502, detail="Drafting is unavailable right now") from None
    created = repo.create_message(
        transaction_id=transaction_id, subject=draft.subject, body=draft.body,
        party_id=msg.get("party_id"), actor=tc.actor, action="message.drafted",
        details={"why": draft.why, "purpose": "chase", "ai": True,
                 "recipient_name": (recipient or {}).get("name"),
                 "recipient_role": (recipient or {}).get("role"),
                 "chases_message_id": message_id},
    )
    return {"message": {"id": created["id"], "subject": created["subject"], "status": created["status"]}}


@router.delete("/transactions/{transaction_id}/notes/{note_id}")
def delete_note(
    transaction_id: str,
    note_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    if not repo.delete_deal_note(transaction_id=transaction_id, note_id=note_id, actor=tc.actor):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True}


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


class ResolveRiskRequest(BaseModel):
    resolved: bool = True


@router.post("/transactions/{transaction_id}/risk-flags/{flag_id}/resolve")
def resolve_risk_flag(
    transaction_id: str,
    flag_id: str,
    body: ResolveRiskRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Mark an attention item handled (or reopen it) — the TC's checkbox."""
    flag = repo.resolve_risk_flag(
        transaction_id=transaction_id, flag_id=flag_id, resolved=body.resolved, actor=tc.actor
    )
    if flag is None:
        raise HTTPException(status_code=404, detail="Risk flag not found")
    return flag


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


@router.post("/transactions/{transaction_id}/story")
def tell_deal_story(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    storyteller: Storyteller = Depends(get_storyteller),
) -> dict[str, Any]:
    """Cross-document synthesis: one narrative + observations blending what was
    read from every document (universal-read facts, effective terms, deadlines,
    flags). The model sees ONLY structured SOR data — never raw documents — and
    the output is advisory display text: no records created, nothing sent.
    Money-language guarded like every model output (Rule 2)."""
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if not state.get("documents"):
        raise HTTPException(status_code=409, detail="No documents on file yet — nothing to weave")
    digest = build_story_digest(state)
    try:
        story = storyteller.tell(digest)
    except ZdrNotConfirmed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except StoryFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    joined = story.get("narrative", "") + "\n" + "\n".join(
        o.get("text", "") for o in story.get("observations", [])
    )
    if _MONEY_FIELD_NAME.search(joined):
        raise HTTPException(
            status_code=422,
            detail="Synthesis contained payment/wiring language and was rejected (Rule 2).",
        )
    return story


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


# §8: receiving-end vendors (own task only) and collaborators (agents/broker —
# read-only scoped view) get a live DB credential; email-only participants
# (buyer/seller/lender/title/escrow) do not.
_COLLAB_ROLES = {"buyer_agent", "listing_agent", "broker", "agent"}


def _invite_tier(party: dict[str, Any]) -> str | None:
    # Every party gets their own scoped workspace link. Agents/broker keep the
    # broader 'collaborator' DB tier; everyone else gets 'receiving_end' (most
    # locked at the DB) — the workspace scoping itself is enforced by the party
    # API from the signed token, independent of this tier.
    if party.get("permission_tier") == "collaborator" or party.get("role") in _COLLAB_ROLES:
        return "collaborator"
    return "receiving_end"


@router.post("/transactions/{transaction_id}/parties/{party_id}/access-token", status_code=201)
def create_party_access_token(
    transaction_id: str,
    party_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    issuer: PartyAccessIssuer = Depends(get_party_access_issuer),
) -> dict[str, Any]:
    """Issue a scoped party session (§8) — the magic-link credential. A
    Supabase-issued session whose admin-set app_metadata RLS keys off; a
    receiving-end token grants only its own task, a collaborator token a
    read-only deal view (all enforced in the DB)."""
    party = repo.get_party(party_id=party_id, transaction_id=transaction_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found on this transaction")
    token_tier = _invite_tier(party)
    if token_tier is None:
        raise HTTPException(
            status_code=409,
            detail="Invite links are for receiving-end vendors and agents/broker only.",
        )
    token = _mint_party_link_token(
        repo, issuer, transaction_id=transaction_id, party_id=party_id,
        tier=token_tier, actor=tc.actor,
    )
    repo.record_access_token_issued(
        transaction_id=transaction_id, party_id=party_id, actor=tc.actor
    )
    return {"party_id": party_id, "access_token": token}


class InviteEmailRequest(BaseModel):
    # The app origin (e.g. https://app.example.com/) so the emailed link points at
    # wherever the workspace is served — the frontend passes its own location.
    base_url: str = Field(min_length=1)


@router.post("/transactions/{transaction_id}/parties/{party_id}/invite-email")
def email_party_invite(
    transaction_id: str,
    party_id: str,
    body: InviteEmailRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    issuer: PartyAccessIssuer = Depends(get_party_access_issuer),
    mailer: Mailer = Depends(get_mailer),
) -> dict[str, Any]:
    """Email a party their personalized invite link. Send is guarded (Rule 3):
    if outbound email is off / the address isn't allow-listed, we return the link
    so the TC can share it manually instead."""
    party = repo.get_party(party_id=party_id, transaction_id=transaction_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found on this transaction")
    token_tier = _invite_tier(party)
    if token_tier is None:
        raise HTTPException(
            status_code=409, detail="Invite links are for receiving-end vendors and agents/broker only."
        )
    email = party.get("email")
    if not email:
        raise HTTPException(
            status_code=422, detail="This party has no email yet — add one on the Parties tab first."
        )
    token = _mint_party_link_token(
        repo, issuer, transaction_id=transaction_id, party_id=party_id,
        tier=token_tier, actor=tc.actor,
    )
    link = f"{body.base_url.split('#')[0]}#invite={token}"
    state = repo.get_full_state(transaction_id) or {}
    address = (state.get("property") or {}).get("address") or "the transaction"
    tc_name = os.environ.get("TC_NAME") or "your transaction coordinator"
    what = (
        "a read-only view of the deal"
        if token_tier == "collaborator"
        else "the items that need you"
    )
    subject = f"Your view of {address}"
    text = (
        f"Hi {party.get('name') or 'there'},\n\n"
        f"{tc_name} has shared {what} for {address} with you — no login required. "
        f"Open it here:\n\n{link}\n\n"
        "You'll see only what's relevant to you.\n\n"
        f"Thanks,\n{tc_name}"
    )
    if _MONEY_FIELD_NAME.search(f"{subject}\n{text}"):
        raise HTTPException(status_code=422, detail="Draft contained wiring language (Rule 2).")
    repo.record_access_token_issued(
        transaction_id=transaction_id, party_id=party_id, actor=tc.actor
    )
    try:
        repo.send_invite(
            transaction_id=transaction_id, party_id=party_id, to=email,
            subject=subject, body=text, mailer=mailer, actor=tc.actor,
        )
    except SendDisabled as exc:
        return {"sent": False, "reason": "disabled", "detail": str(exc), "link": link}
    except RecipientNotAllowed as exc:
        return {"sent": False, "reason": "not_allowlisted", "detail": str(exc), "link": link}
    except SendFailed:
        raise HTTPException(status_code=502, detail="Email provider failed — try again") from None
    return {"sent": True, "to": email}


class AssignTaskRequest(BaseModel):
    party_id: str = Field(min_length=1)


_TASK_STATUSES = frozenset({"pending", "in_progress", "done", "blocked"})


_TASK_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1)
    deadline_id: str | None = None
    assigned_party_id: str | None = None
    # Richer TC-authored task metadata. The tasks table has no columns for these
    # (schema is fixed in this environment), so they ride in the task.created
    # audit details and the API reads them back from there.
    description: str | None = None
    due_date: str | None = None  # ISO yyyy-mm-dd
    priority: str = "normal"


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
    priority = body.priority if body.priority in _TASK_PRIORITIES else "normal"
    return repo.create_task(
        transaction_id=transaction_id,
        title=body.title.strip(),
        deadline_id=body.deadline_id,
        assigned_party_id=body.assigned_party_id,
        actor=tc.actor,
        description=(body.description or "").strip() or None,
        due_date=(body.due_date or "").strip() or None,
        priority=priority,
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


@router.delete("/transactions/{transaction_id}/messages/{message_id}")
def discard_message(
    transaction_id: str,
    message_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Discard a draft/approved message. A sent message can't be removed (audit)."""
    result = repo.delete_message(transaction_id=transaction_id, message_id=message_id, actor=tc.actor)
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if result == "sent":
        raise HTTPException(status_code=409, detail="A sent message can't be discarded.")
    return {"discarded": True}


@router.delete("/transactions/{transaction_id}/reminders/{reminder_id}")
def dismiss_reminder(
    transaction_id: str,
    reminder_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Dismiss a follow-up reminder (got a reply / handled it)."""
    if not repo.delete_reminder(transaction_id=transaction_id, reminder_id=reminder_id, actor=tc.actor):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"dismissed": True}


@router.get("/transactions/{transaction_id}/documents/{document_id}/signed-url")
def document_signed_url(
    transaction_id: str,
    document_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """A short-lived signed URL to open a stored document in a new tab."""
    url = repo.document_signed_url(transaction_id=transaction_id, document_id=document_id)
    if url is None:
        raise HTTPException(status_code=404, detail="No viewable file for this document")
    return {"url": url}


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
        # Effective (superseded) values so a counter offer's price/dates win.
        "fields": [
            {
                "name": name,
                "value": d["value"],
                "confirmed": d["confirmed"],
                "deadline_driving": d["deadline_driving"],
            }
            for name, d in state.get("effective_fields", {}).items()
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
    except ComplianceRunInProgress:
        # Another apply holds this deal (scheduler vs. manual re-run). Idempotent —
        # back off; the in-flight run produces the same result.
        raise HTTPException(
            status_code=409,
            detail="A compliance run is already in progress for this deal; retry shortly.",
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


def _merge_task_meta(state: dict[str, Any]) -> None:
    """Fold TC task metadata (description/due_date/priority) — which is persisted
    in the task.created audit details, since the tasks table has no columns for
    it — back onto each task. Latest audit event wins."""
    meta: dict[str, dict[str, Any]] = {}
    rows = sorted(state.get("audit_log", []), key=lambda r: r.get("created_at") or "")
    for row in rows:
        if row.get("entity_type") != "task" or row.get("action") not in ("task.created", "task.updated"):
            continue
        det = row.get("details") or {}
        picked = {k: det[k] for k in ("description", "due_date", "priority") if k in det}
        if picked:
            meta[row.get("entity_id")] = {**meta.get(row.get("entity_id"), {}), **picked}
    for t in state.get("tasks", []):
        m = meta.get(t["id"], {})
        t["description"] = m.get("description")
        t["due_date"] = m.get("due_date")
        t["priority"] = m.get("priority", "normal")


@router.get("/transactions/{transaction_id}")
def read_full_state(
    transaction_id: str,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _merge_task_meta(state)
    # P8: a human-readable digest of recent deal events, rendered from the shared
    # event catalog (operator voice) — powers the "since you last looked" strip.
    state["digest"] = agent_activity(state.get("audit_log", []), deal_id=transaction_id, limit=20)
    return state


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@router.post("/transactions/{transaction_id}/ask")
def ask_deal(
    transaction_id: str,
    body: AskRequest,
    tc: TCUser = Depends(require_tc),
    repo: MasterRepo = Depends(get_repo),
    assistant: DealAssistant = Depends(get_assistant),
) -> dict[str, Any]:
    """Grounded Q&A over one deal's own records — the TC asks, the assistant answers
    only from this deal's confirmed fields, deadlines, parties, documents, and tasks."""
    state = repo.get_full_state(transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # The TC's own notes join the grounded context (P3) — TC-authored working
    # text on their own deal, same retention posture as the rest of the state.
    state["deal_notes"] = repo.list_deal_notes(transaction_id) or []
    context = build_context(state)
    try:
        answer = assistant.answer(context=context, question=body.question.strip())
    except ZdrNotConfirmed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except AssistantError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"answer": answer}


# ---- Party workspace: each invited stakeholder's own scoped view ------------
# Everything is pinned to the party's own deal + identity from their (signed)
# token — never a client-supplied id. Everyone sees the ROSTER (who's involved)
# and the process TIMELINE; each sees only THEIR tasks and THEIR documents; and
# no private financials / other parties' contact / messages are exposed.


def _due_for(task: dict[str, Any], deadlines: list[dict[str, Any]]) -> str | None:
    if task.get("due_date"):
        return task["due_date"]
    did = task.get("deadline_id")
    return next((d["due_date"] for d in deadlines if d["id"] == did), None) if did else None


@router.get("/party/workspace")
def party_workspace(
    party: PartyUser = Depends(require_party),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    state = repo.get_full_state(party.transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    _merge_task_meta(state)
    me = next((p for p in state.get("parties", []) if p["id"] == party.party_id), None)
    if me is None:
        raise HTTPException(status_code=403, detail="You are not on this deal")
    # Personalized, role-scoped view: the sections + the deal fields this role may
    # see (a vendor never sees the price) — assembled + privacy-filtered server-side.
    property_view = repo.get_or_enrich_property(party.transaction_id)
    return build_party_workspace(state=state, me=me, tier=party.tier, property_view=property_view)


class PartyTaskStatusRequest(BaseModel):
    status: str = Field(min_length=1)


@router.post("/party/tasks/{task_id}/status")
def party_set_task_status(
    task_id: str,
    body: PartyTaskStatusRequest,
    party: PartyUser = Depends(require_party),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """A party updates the status of ONE OF THEIR OWN tasks."""
    if body.status not in {"pending", "in_progress", "done"}:
        raise HTTPException(status_code=422, detail="status must be pending, in_progress, or done")
    state = repo.get_full_state(party.transaction_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    task = next((t for t in state.get("tasks", []) if t["id"] == task_id), None)
    if task is None or task.get("assigned_party_id") != party.party_id:
        raise HTTPException(status_code=404, detail="That task isn't assigned to you")
    updated = repo.set_task_status(
        transaction_id=party.transaction_id, task_id=task_id, status=body.status, actor=party.actor
    )
    return updated or {}


class PartyUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    doc_type: str = "other"


@router.post("/party/documents", status_code=201)
def party_upload_document(
    body: PartyUploadRequest,
    party: PartyUser = Depends(require_party),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """A party uploads their own document to the deal."""
    try:
        doc = repo.add_party_document(
            transaction_id=party.transaction_id,
            party_id=party.party_id,
            filename=body.filename.strip(),
            content_base64=body.content_base64,
            doc_type=(body.doc_type or "other").strip() or "other",
            actor=party.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"document": {"id": doc["id"], "doc_type": doc.get("doc_type"), "status": doc.get("status")}}


@router.post("/party/deposit/verify", status_code=201)
def party_verify_deposit(
    party: PartyUser = Depends(require_party),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The buyer self-attests they verified wire instructions out of band (by phone)
    and sent their deposit. NO wiring/account data is accepted or stored (Rule 2) —
    only the attestation, recorded to the audit log and shown back in their workspace."""
    _require_party_write(repo, party, "money.verify_deposit")
    repo.record_deposit_verified(
        transaction_id=party.transaction_id, party_id=party.party_id, actor=party.actor
    )
    return {"verified": True}


class DisclosureAttestRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=40)


@router.post("/party/disclosure/attest", status_code=201)
def party_attest_disclosure(
    body: DisclosureAttestRequest,
    party: PartyUser = Depends(require_party),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The seller attests a specific CA disclosure is accurate, complete, and
    delivered (an informed, gated attestation — never auto-completed). Recorded to
    the audit log and read back as that disclosure's delivered state."""
    _require_party_write(repo, party, "disclosure.complete")
    repo.record_disclosure_attested(
        transaction_id=party.transaction_id, party_id=party.party_id,
        kind=body.kind.strip(), actor=party.actor,
    )
    return {"attested": True, "kind": body.kind.strip()}


@router.post("/party/disbursement/verify", status_code=201)
def party_verify_disbursement(
    party: PartyUser = Depends(require_party),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The seller self-attests they verified their proceeds-disbursement account out
    of band (by phone). NO account/routing data is accepted or stored (Rule 1)."""
    _require_party_write(repo, party, "money.verify_disbursement")
    repo.record_disbursement_verified(
        transaction_id=party.transaction_id, party_id=party.party_id, actor=party.actor
    )
    return {"verified": True}


def _mint_party_link_token(
    repo: MasterRepo, issuer: PartyAccessIssuer, *,
    transaction_id: str, party_id: str, tier: str, actor: str,
) -> str:
    """A PERMANENT invite credential (pi_…): random token handed out once, only
    its sha256 stored; re-minting revokes the party's previous links. Falls back
    to the legacy ~1h Supabase session token if party_invites isn't provisioned
    yet (pre-migration), so invites never hard-break."""
    token = "pi_" + secrets.token_urlsafe(32)
    try:
        repo.create_party_invite(
            transaction_id=transaction_id, party_id=party_id, tier=tier,
            token_hash=hashlib.sha256(token.encode()).hexdigest(), actor=actor,
        )
        return token
    except Exception:
        _log.info("party_invites unavailable (migration applied?) — falling back to session token")
    try:
        result = issuer.issue(party_id=party_id, transaction_id=transaction_id, email=None, tier=tier)
    except AccessIssuerNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except AccessIssuanceFailed:
        raise HTTPException(status_code=502, detail="Could not issue access token") from None
    return result["access_token"]


def _require_party_write(repo: MasterRepo, party: PartyUser, write: str) -> None:
    """§5 write-authority, enforced dynamically: the signed token names the party;
    their SOR role must be authorized to originate this write. Defense in depth —
    the UIs never offer the wrong action, but a token could be replayed against
    any /party endpoint without this."""
    row = repo.get_party(party_id=party.party_id, transaction_id=party.transaction_id)
    role = (row or {}).get("role") or ""
    try:
        require_originate(write, role)
    except UnauthorizedWrite:
        raise HTTPException(
            status_code=403, detail=f"Your role isn't authorized for this action ({write})."
        ) from None


# ---- Buyer's-agent command center: cross-deal portfolio (the whole book) ------
# The agent's token authenticates; aggregation runs service-role across every deal.

def _all_deal_states(repo: MasterRepo) -> list[dict[str, Any]]:
    # Batch-loaded: one IN-query per table for the whole book, not 13 per deal.
    return repo.list_full_states()


def _agent_me(states: list[dict[str, Any]], party_id: str) -> dict[str, Any]:
    for st in states:
        for p in st.get("parties") or []:
            if p.get("id") == party_id:
                return {"name": p.get("name"), "role": p.get("role")}
    return {"name": "Agent", "role": "buyer_agent"}


def _draft_meta(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """message_id -> its message.drafted audit details (why / purpose / urgency…)."""
    out: dict[str, dict[str, Any]] = {}
    for row in state.get("audit_log") or []:
        if row.get("action") == "message.drafted" and row.get("entity_id"):
            out[row["entity_id"]] = row.get("details") or {}
    return out


def _pending_drafts(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Draft-status messages across the book, enriched into ApprovalItems (rule #3:
    recipient + full body + the co-pilot's reasoning, always shown before send)."""
    items: list[dict[str, Any]] = []
    for st in states:
        txn = st.get("transaction") or {}
        parties = {p["id"]: p for p in (st.get("parties") or [])}
        fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
        meta = _draft_meta(st)
        for m in st.get("messages") or []:
            if m.get("status") != "draft":
                continue
            d = meta.get(m["id"], {})
            recipient = parties.get(m.get("party_id")) or {}
            items.append({
                "id": m["id"], "dealId": txn.get("id"),
                "clientName": fields.get("buyer_names") or "Buyer",
                "title": m.get("subject") or "Outbound message",
                "recipient": {
                    "name": recipient.get("name") or d.get("recipient_name") or "Recipient",
                    "relationship": recipient.get("role") or d.get("recipient_role") or "other",
                    "channel": "email",
                },
                "draftBody": m.get("body") or "",
                "reasoning": d.get("why") or "Flagged by your co-pilot.",
                "urgency": d.get("urgency") or "normal",
                "riskClass": d.get("risk_class") or "standard",
                "state": "pending",
                "createdAt": m.get("created_at"),
            })
    rank = {"urgent": 0, "normal": 1, "low": 2}
    items.sort(key=lambda x: (rank.get(x["urgency"], 1), x.get("createdAt") or ""))
    return items


def _agent_deal_detail(st: dict[str, Any]) -> dict[str, Any]:
    fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items() if v.get("value") is not None}
    deadlines = sorted(st.get("deadlines") or [], key=lambda x: x.get("due_date") or "")
    meta = _draft_meta(st)
    return {
        "summary": deal_summary(st),
        "fields": fields,
        "deadlines": [{"id": d.get("id"), "name": d.get("name"), "due_date": d.get("due_date")} for d in deadlines],
        "parties": [
            {"id": p.get("id"), "name": p.get("name"), "role": p.get("role"), "phone": p.get("phone")}
            for p in st.get("parties") or []
        ],
        "tasks": [
            {"id": t.get("id"), "title": t.get("title"), "status": t.get("status"), "due_date": t.get("due_date")}
            for t in st.get("tasks") or []
        ],
        "documents": [
            {"id": d.get("id"), "doc_type": d.get("doc_type"), "status": d.get("status")}
            for d in st.get("documents") or []
        ],
        "messages": [
            {
                "id": m.get("id"), "subject": m.get("subject"), "status": m.get("status"),
                "reasoning": (meta.get(m.get("id"), {}) or {}).get("why"),
            }
            for m in st.get("messages") or []
        ],
    }


@router.get("/agent/portfolio")
def agent_portfolio(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    states = _all_deal_states(repo)
    pending = _pending_drafts(states)
    payload = build_agent_portfolio(
        deals=states, me=_agent_me(states, agent.party_id), pending_drafts=len(pending)
    )
    # Ship the queue with the portfolio: the command center needs both on every
    # load/poll, and a separate /agent/approvals call re-loads the whole book.
    payload["approvalItems"] = pending
    return payload


@router.get("/agent/approvals")
def agent_approvals(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    return {"items": _pending_drafts(_all_deal_states(repo))}


@router.get("/agent/clients")
def agent_clients(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Client cards with the pre-call context: contingency snapshot, docs on
    file, next deadline, and plain-English talking points from the event log."""
    out = []
    for st in _all_deal_states(repo):
        txn = st.get("transaction") or {}
        fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
        out.append({
            "dealId": txn.get("id"),
            "clientName": fields.get("buyer_names") or "Buyer",
            "propertyAddress": (st.get("property") or {}).get("address") or fields.get("property_address") or "Property",
            "parties": [
                {"id": p.get("id"), "name": p.get("name"), "role": p.get("role"), "phone": p.get("phone")}
                for p in st.get("parties") or [] if p.get("role") != "buyer"
            ],
            **client_context(st),
        })
    return {"clients": out}


@router.get("/agent/schedule")
def agent_schedule_view(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Where the agent needs to be: dated deadlines + open tasks across the book."""
    return {"items": agent_schedule(_all_deal_states(repo))}


@router.get("/agent/earnings")
def agent_earnings_view(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The commission pipeline — ESTIMATES only (default buyer-side rate, clearly
    labeled); display-only, no money logic touched."""
    return agent_earnings(_all_deal_states(repo))


@router.post("/agent/clients/{transaction_id}/draft-update", status_code=201)
def agent_draft_client_update(
    transaction_id: str,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
    drafter: Drafter = Depends(get_drafter),
) -> dict[str, Any]:
    """The weekly 'where things stand' note to the buyer client — drafted by the
    co-pilot from deal state, landing in the approval queue (Rule 3: the agent
    reviews recipient + full body before anything sends)."""
    st = repo.get_full_state(transaction_id)
    if not st:
        raise HTTPException(status_code=404, detail="Deal not found")
    buyer = next((p for p in st.get("parties") or [] if p.get("role") == "buyer"), None)
    if not buyer:
        raise HTTPException(status_code=409, detail="No buyer client on this deal")
    fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
    dates = tuple(
        (d.get("name"), d.get("due_date"))
        for d in sorted(st.get("deadlines") or [], key=lambda x: x.get("due_date") or "")[:4]
        if d.get("due_date")
    )
    ctx = MessageContext(
        purpose="client_update", recipient_name=buyer.get("name"), recipient_role="buyer",
        property_address=(st.get("property") or {}).get("address") or fields.get("property_address"),
        buyer_names=fields.get("buyer_names"), seller_names=fields.get("seller_names"),
        tc_name=_agent_me([st], agent.party_id).get("name"),
        key_dates=dates, note=None,
    )
    try:
        draft = drafter.draft_message(ctx)
    except ZdrNotConfirmed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except DraftFailed:
        raise HTTPException(status_code=502, detail="Drafting is unavailable right now") from None
    created = repo.create_message(
        transaction_id=transaction_id, subject=draft.subject, body=draft.body,
        party_id=buyer.get("id"), actor=agent.actor, action="message.drafted",
        details={"why": draft.why, "purpose": "client_update", "ai": True,
                 "recipient_name": buyer.get("name"), "recipient_role": "buyer"},
    )
    return {"message": {"id": created["id"], "subject": created["subject"], "status": created["status"]}}


@router.get("/agent/deals/{transaction_id}")
def agent_deal_detail(
    transaction_id: str,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    st = repo.get_full_state(transaction_id)
    if not st:
        raise HTTPException(status_code=404, detail="Deal not found")
    return _agent_deal_detail(st)


class CopilotRefreshRequest(BaseModel):
    limit: int = Field(default=8, ge=1, le=20)


@router.post("/agent/copilot/refresh", status_code=201)
def agent_copilot_refresh(
    body: CopilotRefreshRequest,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
    drafter: Drafter = Depends(get_drafter),
) -> dict[str, Any]:
    """Generate outbound DRAFTS for outreach the book needs (live co-pilot drafting).
    Each becomes a pending approval item — nothing is sent (rule #3)."""
    states = _all_deal_states(repo)
    generated = 0
    errors = 0
    for st in states:
        if generated >= body.limit:
            break
        txn = st.get("transaction") or {}
        tid = txn.get("id")
        fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
        existing = {d.get("purpose") for d in _draft_meta(st).values() if d.get("purpose")}
        prop = (st.get("property") or {}).get("address") or fields.get("property_address")
        for tgt in draft_targets(st, existing_purposes=existing):
            if generated >= body.limit:
                break
            dl = tgt["deadline"]
            rec = tgt["recipient"]
            ctx = MessageContext(
                purpose=tgt["purpose"], recipient_name=rec.get("name"), recipient_role=rec.get("role"),
                property_address=prop, buyer_names=fields.get("buyer_names"),
                seller_names=fields.get("seller_names"), tc_name=_agent_me(states, agent.party_id).get("name"),
                key_dates=((dl.get("name"), dl.get("due_date")),), note=None,
            )
            try:
                draft = drafter.draft_message(ctx)
            except DraftFailed:
                errors += 1
                continue
            repo.create_message(
                transaction_id=tid, subject=draft.subject, body=draft.body,
                party_id=rec.get("id"), actor=agent.actor, action="message.drafted",
                details={
                    "why": draft.why, "purpose": tgt["purpose"], "urgency": tgt["urgency"],
                    "risk_class": tgt["risk_class"], "recipient_role": rec.get("role"),
                    "recipient_name": rec.get("name"), "ai": True,
                },
            )
            generated += 1
    return {"generated": generated, "errors": errors}


class AgentApproveRequest(BaseModel):
    transaction_id: str
    subject: str | None = None
    body: str | None = None


@router.post("/agent/approvals/{message_id}/approve", status_code=201)
def agent_approve(
    message_id: str,
    body: AgentApproveRequest,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Rule #3: the agent's explicit approval of an AI draft — logged to the deal
    (not silently sent; the command center isn't wired to outbound delivery)."""
    try:
        msg = repo.record_message_approved(
            transaction_id=body.transaction_id, message_id=message_id,
            actor=agent.actor, subject=body.subject, body=body.body,
        )
    except MessageNotSendable:
        raise HTTPException(status_code=409, detail="This message was already approved or sent") from None
    if msg is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"approved": True, "id": message_id}


class AgentDismissRequest(BaseModel):
    transaction_id: str


@router.post("/agent/approvals/{message_id}/dismiss")
def agent_dismiss(
    message_id: str,
    body: AgentDismissRequest,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    result = repo.delete_message(transaction_id=body.transaction_id, message_id=message_id, actor=agent.actor)
    if result is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if result == "sent":
        raise HTTPException(status_code=409, detail="Already sent — can't dismiss")
    return {"dismissed": True}


# ---- Listing-agent command center (near-mirror; listing frame) ----------------
# Reuses the same auth, approval queue (/agent/approvals + approve/dismiss), and
# co-pilot refresh; adds the listing portfolio and the offer-comparison workflow.

@router.get("/listing/portfolio")
def listing_portfolio(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    states = _all_deal_states(repo)
    pending = _pending_drafts(states)
    payload = build_listing_portfolio(
        deals=states, me=_agent_me(states, agent.party_id), pending_drafts=len(pending)
    )
    payload["approvalItems"] = pending  # same single-load contract as /agent/portfolio
    return payload


@router.get("/listing/sellers")
def listing_sellers(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Seller cards with the pre-call cram: status + DOM, offers, disclosure
    delivery state, marketing pulse (sample), talking points."""
    out = []
    for st in _all_deal_states(repo):
        txn = st.get("transaction") or {}
        fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
        out.append({
            "listingId": txn.get("id"),
            "sellerName": fields.get("seller_names") or "Seller",
            "propertyAddress": (st.get("property") or {}).get("address") or fields.get("property_address") or "Property",
            "parties": [
                {"id": p.get("id"), "name": p.get("name"), "role": p.get("role"), "phone": p.get("phone")}
                for p in st.get("parties") or [] if p.get("role") != "seller"
            ],
            **seller_context(st),
        })
    return {"sellers": out}


@router.get("/listing/schedule")
def listing_schedule_view(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """The listing agent's day across the book — seller-framed names."""
    return {"items": agent_schedule(_all_deal_states(repo), name_field="seller_names")}


@router.get("/listing/earnings")
def listing_earnings_view(
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    """Listing-side commission pipeline — ESTIMATES only, display only."""
    return listing_earnings(_all_deal_states(repo))


@router.post("/listing/sellers/{transaction_id}/draft-update", status_code=201)
def listing_draft_seller_update(
    transaction_id: str,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
    drafter: Drafter = Depends(get_drafter),
) -> dict[str, Any]:
    """The weekly where-things-stand note to the SELLER — co-pilot drafted,
    approval-queue gated (Rule 3)."""
    st = repo.get_full_state(transaction_id)
    if not st:
        raise HTTPException(status_code=404, detail="Listing not found")
    seller = next((p for p in st.get("parties") or [] if p.get("role") == "seller"), None)
    if not seller:
        raise HTTPException(status_code=409, detail="No seller on this listing")
    fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
    dates = tuple(
        (d.get("name"), d.get("due_date"))
        for d in sorted(st.get("deadlines") or [], key=lambda x: x.get("due_date") or "")[:4]
        if d.get("due_date")
    )
    ctx = MessageContext(
        purpose="seller_update", recipient_name=seller.get("name"), recipient_role="seller",
        property_address=(st.get("property") or {}).get("address") or fields.get("property_address"),
        buyer_names=fields.get("buyer_names"), seller_names=fields.get("seller_names"),
        tc_name=_agent_me([st], agent.party_id).get("name"),
        key_dates=dates, note=None,
    )
    try:
        draft = drafter.draft_message(ctx)
    except ZdrNotConfirmed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except DraftFailed:
        raise HTTPException(status_code=502, detail="Drafting is unavailable right now") from None
    created = repo.create_message(
        transaction_id=transaction_id, subject=draft.subject, body=draft.body,
        party_id=seller.get("id"), actor=agent.actor, action="message.drafted",
        details={"why": draft.why, "purpose": "seller_update", "ai": True,
                 "recipient_name": seller.get("name"), "recipient_role": "seller"},
    )
    return {"message": {"id": created["id"], "subject": created["subject"], "status": created["status"]}}


@router.get("/listing/offers/{transaction_id}")
def listing_offers(
    transaction_id: str,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
) -> dict[str, Any]:
    st = repo.get_full_state(transaction_id)
    if not st:
        raise HTTPException(status_code=404, detail="Listing not found")
    fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
    health = _seller_deal_health(fields, st.get("audit_log", []))
    # re-point the key name for the listing frame (read-only to the agent)
    for m in health["milestones"]:
        m["actionableByAgent"] = m.pop("actionableBySeller", False)
    return {
        "offers": build_offer_comparison(st),
        "buyerHealth": health,
        "sellerName": fields.get("seller_names") or "Seller",
        "propertyAddress": (st.get("property") or {}).get("address") or fields.get("property_address"),
    }


@router.post("/listing/offers/{transaction_id}/draft-comparison", status_code=201)
def listing_draft_comparison(
    transaction_id: str,
    agent: PartyUser = Depends(require_agent_portfolio),
    repo: MasterRepo = Depends(get_repo),
    drafter: Drafter = Depends(get_drafter),
) -> dict[str, Any]:
    """Draft a plain-language, neutral offer summary FOR THE SELLER (rule #3: goes to
    the approval queue; the AI never picks a winner — the seller decides)."""
    st = repo.get_full_state(transaction_id)
    if not st:
        raise HTTPException(status_code=404, detail="Listing not found")
    offers = build_offer_comparison(st)
    if not offers:
        raise HTTPException(status_code=409, detail="No offers to compare on this listing")
    fields = {k: v.get("value") for k, v in (st.get("effective_fields") or {}).items()}
    seller = next((p for p in st.get("parties") or [] if p.get("role") == "seller"), None)
    if not seller:
        raise HTTPException(status_code=409, detail="No seller on file to send to")

    def _usd(c: int | None) -> str:
        return f"${c / 100:,.0f}" if c else "—"
    lines = "; ".join(
        f"{o['buyerAgentName']}: {_usd(o['priceCents'])}, {o['financing']}, {o['contingencies']} contingencies, "
        f"close {o['closeDays']}d ({o['tradeoffTag']})" for o in offers
    )
    ctx = MessageContext(
        purpose="offer_comparison", recipient_name=seller.get("name"), recipient_role="seller",
        property_address=(st.get("property") or {}).get("address") or fields.get("property_address"),
        buyer_names=None, seller_names=fields.get("seller_names"),
        # Resolve the drafter's name from the deal already in hand — the previous
        # _all_deal_states() call re-loaded the entire book for one name.
        tc_name=_agent_me([st], agent.party_id).get("name"),
        key_dates=(), note=f"Offers received: {lines}. Present these neutrally; do not recommend one.",
    )
    try:
        draft = drafter.draft_message(ctx)
    except DraftFailed:
        raise HTTPException(status_code=502, detail="Co-pilot drafting is unavailable") from None
    repo.create_message(
        transaction_id=transaction_id, subject=draft.subject, body=draft.body,
        party_id=seller.get("id"), actor=agent.actor, action="message.drafted",
        details={"why": draft.why, "purpose": "offer_comparison", "urgency": "normal",
                 "risk_class": "standard", "recipient_role": "seller", "recipient_name": seller.get("name"), "ai": True},
    )
    return {"drafted": True}


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
    # Rule 2 also on VALUES: a routing/account number or SSN smuggled into a
    # whitelisted field (e.g. other_terms) via document-content injection must not
    # reach the SOR. Targeted so legitimate values ("…Bank", an APN) are unaffected.
    wiring_values = sorted(
        {f.name for f in payload.extracted_fields if _WIRING_VALUE.search(f.value or "")}
    )
    if wiring_values:
        raise HTTPException(
            status_code=422,
            detail=(
                "Rule 2: wiring/account/SSN data is never stored. Rejected value(s) "
                f"in field(s): {', '.join(wiring_values)}"
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
