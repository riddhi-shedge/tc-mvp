"""Repository for the master / SOR (part b).

The only code that touches the database. Every mutating method writes its own
audit_log entry — the audit log records every state change (Prompt 1). Uses the
Supabase service-role key: backend only, never exposed to a frontend.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from app.common.db import ThreadLocalSupabase
from app.contracts.compliance import ComplianceResult
from app.contracts.documents import COUNTER_OFFER_TYPES
from app.contracts.fields import DEADLINE_DRIVING
from app.contracts.payload import CounterMeta, Payload, PreapprovalMeta
from app.master.deal_tasks import derive_tasks
from app.master.inconsistency import CRITICAL_FIELDS, MATERIAL_FIELDS, find_field_conflicts
from app.master.parties import derive_parties, party_key, tier_for


class TimelineAlreadyExists(Exception):
    """A (stub) timeline was already generated for this transaction."""


class DeadlineFieldsUnconfirmed(Exception):
    """The timeline may not build while any deadline-driving field is
    unconfirmed — or MISSING entirely (an omitted field is not a confirmed
    field; §11 step 4 / Prompt 4). Carries field NAMES only — never values
    (logging discipline)."""

    def __init__(self, field_names: list[str]) -> None:
        self.field_names = field_names
        super().__init__(", ".join(field_names))


def _deadline_gate_state(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The timeline-readiness breakdown for the UI (and the "Build timeline"
    pre-check): which deadline-driving §5 fields are MISSING (no row at all —
    the TC must hand-enter them) vs present-but-UNCONFIRMED (a one-tap confirm).
    The timeline builds only when both are empty.

    Mirrors the gate's own rule: a deal with no extraction yet (e.g. created
    manually, no PA uploaded) is not gated on §5 coverage, so it reports ready
    with nothing outstanding — the frontend surfaces the prompt only when a
    deal actually has fields but isn't ready."""
    if not rows:
        return {"ready": True, "missing_fields": [], "unconfirmed_fields": []}
    confirmed = {r["name"] for r in rows if r["confirmed"]}
    present = {r["name"] for r in rows}
    missing = sorted(DEADLINE_DRIVING - present)
    unconfirmed = sorted((DEADLINE_DRIVING & present) - confirmed)
    return {
        "ready": not missing and not unconfirmed,
        "missing_fields": missing,
        "unconfirmed_fields": unconfirmed,
    }


def _deadline_gate_violations(rows: list[dict[str, Any]]) -> list[str]:
    """The flat list of deadline-driving names that block the timeline (missing
    OR unconfirmed) — the §11 gate raised by the stub/compliance write paths."""
    gate = _deadline_gate_state(rows)
    return sorted(set(gate["missing_fields"]) | set(gate["unconfirmed_fields"]))


# Valid pipeline stages for the Deals board (order = left-to-right flow).
DEAL_STAGES: tuple[str, ...] = ("new", "cont", "closing", "closed")
# Older deals may still carry retired stages; fold them into the current four.
_LEGACY_STAGE = {"funds": "new", "removed": "closing"}


def _normalize_stage(stage: str | None) -> str:
    stage = stage or "new"
    return _LEGACY_STAGE.get(stage, stage if stage in DEAL_STAGES else "new")


def _effective_fields(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resolve extracted-field rows to ONE effective value per field name so a
    later confirmed value supersedes an earlier one — this is how a counter
    offer's price overrides the purchase agreement's. Rule: among rows sharing a
    name, the latest CONFIRMED by created_at wins; if none is confirmed, the
    latest row wins. `superseded_from` carries the prior confirmed value it
    replaced, for provenance in the UI ("$1.9M — was $1.8M")."""
    by_name: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for name, group in by_name.items():
        ordered = sorted(group, key=lambda r: r.get("created_at") or "")
        confirmed = [r for r in ordered if r.get("confirmed")]
        chosen = (confirmed or ordered)[-1]
        prior = next(
            (r["value"] for r in reversed(confirmed) if r is not chosen and r["value"] != chosen["value"]),
            None,
        )
        out[name] = {
            "value": chosen["value"],
            "confirmed": bool(chosen.get("confirmed")),
            "deadline_driving": bool(chosen.get("deadline_driving")),
            "superseded_from": prior,
        }
    return out


_LOOSE_DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y",
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
)


def _parse_loose_date(value: str | None) -> date | None:
    """Parse a date written in any common form (ISO, US slash, month name) out of
    a possibly longer phrase. Returns None when nothing matches."""
    if not value:
        return None
    v = re.sub(r"\s+", " ", value.strip())
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        pass
    m = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Za-z]{3,9} \d{1,2},? \d{4}", v)
    token = m.group(0) if m else v
    for fmt in _LOOSE_DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _signed_after(signed: str | None, expiration: str | None) -> bool:
    s, e = _parse_loose_date(signed), _parse_loose_date(expiration)
    return bool(s and e and s > e)


def evaluate_counter_flags(doc_type: str, cm: CounterMeta) -> list[dict[str, str]]:
    """Turn a counter offer's chain/expiration facts into risk flags. A counter
    that the accepting party never signed (or signed too late) means the deal may
    have FALLEN THROUGH; a 'subject to attached counter' box means the true terms
    live in a FURTHER counter that must be uploaded. Pure — inserted by each repo."""
    accepting = (
        "buyer" if doc_type == "seller_counter_offer"
        else "seller" if doc_type == "buyer_counter_offer"
        else "receiving party"
    )
    label = doc_type.replace("_", " ")
    flags: list[dict[str, str]] = []
    late = _signed_after(cm.signed_date, cm.expiration)
    if not cm.recipient_signed or late:
        by = f" by {cm.expiration}" if cm.expiration else ""
        why = "did not sign it in time" if late else "has not signed it"
        flags.append({
            "severity": "critical",
            "case_key": "counter_not_accepted",
            "description": (
                f"The {accepting} {why}{by} — this {label} may not be accepted and the "
                "deal could have fallen through. Confirm acceptance, or mark the deal canceled."
            ),
        })
    if cm.subject_to_further_counter:
        further = (
            "buyer counter offer" if doc_type == "seller_counter_offer" else "seller counter offer"
        )
        flags.append({
            "severity": "warning",
            "case_key": "counter_chain",
            "description": (
                f"This {label} is marked subject to a further counter — the current terms "
                f"are in the {further}. Upload it to capture the latest price and terms."
            ),
        })
    return flags


def _parse_money(value: str | None) -> float | None:
    m = re.search(r"[\d,]+(?:\.\d+)?", value or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _name_set(value: str | None) -> set[str]:
    if not value:
        return set()
    parts = re.split(r"\s*(?:,| and | & |;|/)\s*", value.strip(), flags=re.IGNORECASE)
    return {re.sub(r"\s+", " ", p).strip().lower() for p in parts if p.strip()}


def evaluate_preapproval_flags(
    meta: "PreapprovalMeta",
    pa_buyer_names: str | None,
    pa_loan_amount: str | None,
    coe_date: date | None,
) -> list[dict[str, str]]:
    """Validate a preapproval against the deal: same borrower, approved for at
    least the contract loan, and valid through closing. Pure — inserted by each repo."""
    flags: list[dict[str, str]] = []
    pre_names, pa_names = _name_set(meta.buyer_names), _name_set(pa_buyer_names)
    if pre_names and pa_names and pre_names.isdisjoint(pa_names):
        flags.append({
            "severity": "warning",
            "case_key": "preapproval_name_mismatch",
            "description": (
                f'The preapproval names "{meta.buyer_names}", but the contract buyer is '
                f'"{pa_buyer_names}". Verify it is the same borrower.'
            ),
        })
    pre_amt, pa_amt = _parse_money(meta.loan_amount), _parse_money(pa_loan_amount)
    if pre_amt is not None and pa_amt is not None and pre_amt < pa_amt:
        flags.append({
            "severity": "critical",
            "case_key": "preapproval_insufficient",
            "description": (
                f"The preapproval is for {meta.loan_amount}, less than the {pa_loan_amount} loan "
                "on the contract — the buyer may not be approved for enough to close."
            ),
        })
    exp = _parse_loose_date(meta.expiration)
    if exp and coe_date and exp < coe_date:
        flags.append({
            "severity": "warning",
            "case_key": "preapproval_expired",
            "description": (
                f"The preapproval expires {meta.expiration}, before the close of escrow "
                f"({coe_date.isoformat()}). Request an updated approval letter."
            ),
        })
    return flags


def _deal_summary(
    txn: dict[str, Any],
    props: dict[str, Any],
    coe: dict[str, Any],
    tasks: dict[str, list[int]],
    risks: dict[str, int],
    fields: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Shape one board card from the pre-aggregated lookups (shared by both repos)."""
    tid = txn["id"]
    total, done = tasks.get(tid, [0, 0])
    fx = fields.get(tid, {})
    return {
        "id": tid,
        "status": txn.get("status", "open"),
        "stage": _normalize_stage(txn.get("stage")),
        "property_address": props.get(tid),
        "coe_date": coe.get(tid),
        "purchase_price": fx.get("purchase_price"),
        "all_cash": fx.get("all_cash") == "true",
        "total_tasks": total,
        "done_tasks": done,
        "open_tasks": total - done,
        "risk_count": risks.get(tid, 0),
    }


class MessageNotSendable(Exception):
    """The message is not in 'draft' state — it cannot be approved and sent."""


class NoRecipient(Exception):
    """The message has no resolvable recipient (its party has no email)."""


class NoPayloadForManualField(Exception):
    """A manual field can't be attached — the deal has no payload yet (nothing
    has been ingested). Upload a document first, then add missing fields."""


# Hardcoded Phase 2 timeline — clearly labeled stub; real CA rules are Phase 5
# and come only from ca-rules-researcher + human verification.
_STUB_TIMELINE = (
    ("Earnest money deposit due (stub)", "Confirm earnest money deposited (stub)", 3),
    ("Inspection contingency ends (stub)", "Schedule general inspection (stub)", 17),
    ("Close of escrow (stub)", "Confirm closing preparations (stub)", 30),
)

_STUB_DRAFT_SUBJECT = "Lender status check-in (stub)"
_STUB_DRAFT_BODY = (
    "Hi (stub lender contact),\n\n"
    "Checking in on loan progress for the deal at the subject property. Could "
    "you share the current status of the application and any items you need "
    "from the buyers?\n\nThanks,\n(stub) — Phase 2 walking skeleton draft; real "
    "drafting arrives in Phase 6"
)
_STUB_DRAFT_WHY = (
    "Stub rationale: a signed purchase agreement was ingested and confirmed, so "
    "the first §11 follow-up is a lender status request. Real drafting with a "
    "deal-state-specific WHY arrives in Phase 6."
)


class MasterRepo(Protocol):
    """Interface the API depends on; tests substitute an in-memory fake."""

    def create_transaction(self, *, property_address: str, actor: str) -> dict[str, Any]: ...

    def list_transactions(self) -> list[dict[str, Any]]: ...

    def archive_transaction(
        self, *, transaction_id: str, actor: str
    ) -> dict[str, Any] | None: ...

    def unarchive_transaction(
        self, *, transaction_id: str, actor: str
    ) -> dict[str, Any] | None: ...

    def cancel_transaction(
        self, *, transaction_id: str, reason: str, actor: str
    ) -> dict[str, Any] | None: ...

    def reactivate_transaction(
        self, *, transaction_id: str, actor: str
    ) -> dict[str, Any] | None: ...

    def delete_transaction(self, *, transaction_id: str, actor: str) -> bool: ...

    def set_transaction_stage(
        self, *, transaction_id: str, stage: str, actor: str
    ) -> dict[str, Any] | None: ...

    def resolve_risk_flag(
        self, *, transaction_id: str, flag_id: str, resolved: bool, actor: str
    ) -> dict[str, Any] | None: ...

    def list_deal_summaries(self) -> list[dict[str, Any]]: ...

    def list_active_deadlines(self) -> list[dict[str, Any]]: ...

    def list_open_tasks(self) -> list[dict[str, Any]]: ...

    def list_active_transaction_ids(self) -> list[str]: ...

    def transaction_exists(self, transaction_id: str) -> bool: ...

    def party_belongs_to_transaction(self, *, party_id: str, transaction_id: str) -> bool: ...

    def get_party(self, *, party_id: str, transaction_id: str) -> dict[str, Any] | None: ...

    def record_access_token_issued(
        self, *, transaction_id: str, party_id: str, actor: str
    ) -> None: ...

    def write_payload(
        self, *, transaction_id: str, payload: Payload, actor: str
    ) -> dict[str, Any]: ...

    def get_full_state(self, transaction_id: str) -> dict[str, Any] | None: ...

    def confirm_fields(self, *, transaction_id: str, field_ids: list[str], actor: str) -> int: ...

    def add_manual_field(
        self, *, transaction_id: str, name: str, value: str, actor: str
    ) -> dict[str, Any]: ...

    def create_stub_timeline(self, *, transaction_id: str, actor: str) -> dict[str, Any]: ...

    def create_stub_draft(self, *, transaction_id: str, actor: str) -> dict[str, Any]: ...

    def create_party(
        self,
        *,
        transaction_id: str,
        name: str,
        role: str,
        email: str | None,
        permission_tier: str,
        actor: str,
        phone: str | None = None,
        company: str | None = None,
    ) -> dict[str, Any]: ...

    def update_party(
        self, *, transaction_id: str, party_id: str, fields: dict[str, Any], actor: str
    ) -> dict[str, Any] | None: ...

    def derive_parties_from_fields(self, *, transaction_id: str, actor: str) -> int: ...

    def derive_tasks_from_fields(self, *, transaction_id: str, actor: str) -> int: ...

    def lender_party(self, transaction_id: str) -> dict[str, Any] | None: ...

    def assign_task(
        self, *, transaction_id: str, task_id: str, party_id: str, actor: str
    ) -> dict[str, Any] | None: ...

    def create_task(
        self,
        *,
        transaction_id: str,
        title: str,
        actor: str,
        deadline_id: str | None = None,
        assigned_party_id: str | None = None,
        description: str | None = None,
        due_date: str | None = None,
        priority: str = "normal",
    ) -> dict[str, Any]: ...

    def set_task_status(
        self, *, transaction_id: str, task_id: str, status: str, actor: str
    ) -> dict[str, Any] | None: ...

    def loan_deadline_iso(self, transaction_id: str) -> str | None: ...

    def create_message(
        self,
        *,
        transaction_id: str,
        subject: str,
        body: str,
        party_id: str | None,
        actor: str,
        action: str = "message.drafted",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def delete_message(self, *, transaction_id: str, message_id: str, actor: str) -> str | None: ...

    def delete_reminder(self, *, transaction_id: str, reminder_id: str, actor: str) -> bool: ...

    def document_signed_url(self, *, transaction_id: str, document_id: str) -> str | None: ...

    def add_party_document(
        self, *, transaction_id: str, party_id: str, filename: str,
        content_base64: str, doc_type: str, actor: str,
    ) -> dict[str, Any]: ...

    def approve_and_send(
        self,
        *,
        transaction_id: str,
        message_id: str,
        actor: str,
        subject: str | None,
        body: str | None,
        mailer: Any,
        followup_days: int,
    ) -> dict[str, Any] | None: ...

    def send_invite(
        self, *, transaction_id: str, party_id: str, to: str, subject: str, body: str,
        mailer: Any, actor: str,
    ) -> None: ...

    def apply_compliance_result(
        self, *, result: ComplianceResult, actor: str
    ) -> dict[str, Any]: ...


# Ingestion's private attachment bucket (documents' storage_path lives here).
# Named locally so the master doesn't import ingestion internals.
ATTACHMENT_BUCKET = "ingestion-attachments"


def _task_meta(
    source: str, description: str | None, due_date: str | None, priority: str
) -> dict[str, Any]:
    """Audit-details payload carrying a TC task's richer metadata (no columns for
    it in this environment). Only non-default values are stored."""
    meta: dict[str, Any] = {"source": source}
    if description:
        meta["description"] = description
    if due_date:
        meta["due_date"] = due_date
    if priority and priority != "normal":
        meta["priority"] = priority
    return meta

_CHILD_TABLES = (
    "parties",
    "documents",
    "payloads",
    "extracted_fields",
    "deadlines",
    "tasks",
    "messages",
    "reminders",
    "risk_flags",
    "approvals",
    "audit_log",
)


class SupabaseRepo:
    """Supabase-backed implementation of MasterRepo."""

    def __init__(self) -> None:
        # Thread-local client: this repo is a process-wide singleton used from
        # FastAPI's threadpool, and the Supabase client isn't thread-safe.
        self._pool = ThreadLocalSupabase(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )

    @property
    def _db(self) -> Any:
        return self._pool.client

    # -- audit -----------------------------------------------------------------
    def _audit(
        self,
        *,
        transaction_id: str | None,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._db.table("audit_log").insert(
            {
                "transaction_id": transaction_id,
                "actor": actor,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": details or {},
            }
        ).execute()

    # -- MasterRepo --------------------------------------------------------------
    def create_transaction(self, *, property_address: str, actor: str) -> dict[str, Any]:
        # PostgREST gives no cross-table transaction, so a failure after the
        # first insert is compensated by deleting the transaction (cascades) —
        # no state change may exist without its audit row.
        txn = self._db.table("transactions").insert({"status": "open"}).execute().data[0]
        try:
            prop = (
                self._db.table("properties")
                .insert({"transaction_id": txn["id"], "address": property_address})
                .execute()
                .data[0]
            )
            self._audit(
                transaction_id=txn["id"],
                actor=actor,
                action="transaction.created",
                entity_type="transaction",
                entity_id=txn["id"],
                details={"property_address": property_address},
            )
        except Exception:
            self._db.table("transactions").delete().eq("id", txn["id"]).execute()
            raise
        return {**txn, "property": prop}

    def list_transactions(self) -> list[dict[str, Any]]:
        txns = (
            self._db.table("transactions").select("*").order("created_at", desc=True).execute().data
        )
        if not txns:
            return []
        props = {
            p["transaction_id"]: p
            for p in self._db.table("properties")
            .select("transaction_id, address")
            .in_("transaction_id", [t["id"] for t in txns])
            .execute()
            .data
        }
        return [{**t, "property_address": (props.get(t["id"]) or {}).get("address")} for t in txns]

    def _set_transaction_status(
        self, *, transaction_id: str, status: str, actor: str, action: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        rows = (
            self._db.table("transactions")
            .update({"status": status})
            .eq("id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action=action,
            entity_type="transaction",
            entity_id=transaction_id,
            details={"status": status, **(details or {})},
        )
        return rows[0]

    def cancel_transaction(
        self, *, transaction_id: str, reason: str, actor: str
    ) -> dict[str, Any] | None:
        """The deal fell through / was canceled (e.g. the buyer backed out during
        contingencies). A terminal state, distinct from archive; reactivatable."""
        return self._set_transaction_status(
            transaction_id=transaction_id, status="canceled", actor=actor,
            action="transaction.canceled", details={"reason": reason},
        )

    def reactivate_transaction(self, *, transaction_id: str, actor: str) -> dict[str, Any] | None:
        return self._set_transaction_status(
            transaction_id=transaction_id, status="open", actor=actor,
            action="transaction.reactivated",
        )

    def archive_transaction(self, *, transaction_id: str, actor: str) -> dict[str, Any] | None:
        return self._set_transaction_status(
            transaction_id=transaction_id, status="archived", actor=actor,
            action="transaction.archived",
        )

    def unarchive_transaction(self, *, transaction_id: str, actor: str) -> dict[str, Any] | None:
        return self._set_transaction_status(
            transaction_id=transaction_id, status="open", actor=actor,
            action="transaction.unarchived",
        )

    def delete_transaction(self, *, transaction_id: str, actor: str) -> bool:
        """Hard delete — the transaction row cascades to every child (property,
        parties, documents, fields, deadlines, tasks, messages, AND the audit
        log). For synthetic/test cleanup; archive keeps the compliance trail. The
        PDF blob lives in ingestion's private bucket and is cleared separately."""
        existed = bool(
            self._db.table("transactions").select("id").eq("id", transaction_id).execute().data
        )
        if not existed:
            return False
        self._db.table("transactions").delete().eq("id", transaction_id).execute()
        return True

    def set_transaction_stage(
        self, *, transaction_id: str, stage: str, actor: str
    ) -> dict[str, Any] | None:
        rows = (
            self._db.table("transactions")
            .update({"stage": stage})
            .eq("id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="transaction.staged",
            entity_type="transaction",
            entity_id=transaction_id,
            details={"stage": stage},
        )
        return rows[0]

    def resolve_risk_flag(
        self, *, transaction_id: str, flag_id: str, resolved: bool, actor: str
    ) -> dict[str, Any] | None:
        rows = (
            self._db.table("risk_flags")
            .update({"resolved": resolved})
            .eq("id", flag_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="risk_flag.resolved" if resolved else "risk_flag.reopened",
            entity_type="risk_flag",
            entity_id=flag_id,
            details={"resolved": resolved},
        )
        return rows[0]

    def list_deal_summaries(self) -> list[dict[str, Any]]:
        """Enriched per-deal rollup for the pipeline board — COE, price, task
        progress, risk count, stage — aggregated in a few bulk reads."""
        txns = (
            self._db.table("transactions")
            .select("id, status, stage, created_at")
            .neq("status", "archived")
            .order("created_at", desc=True)
            .execute()
            .data
        )
        if not txns:
            return []
        ids = [t["id"] for t in txns]
        props = {
            p["transaction_id"]: p["address"]
            for p in self._db.table("properties")
            .select("transaction_id, address")
            .in_("transaction_id", ids)
            .execute()
            .data
        }
        coe = {
            d["transaction_id"]: d["due_date"]
            for d in self._db.table("deadlines")
            .select("transaction_id, due_date")
            .eq("compute_key", "coe")
            .in_("transaction_id", ids)
            .execute()
            .data
        }
        tasks: dict[str, list[int]] = {}
        for t in (
            self._db.table("tasks").select("transaction_id, status").in_("transaction_id", ids)
            .execute().data
        ):
            agg = tasks.setdefault(t["transaction_id"], [0, 0])
            agg[0] += 1
            if t["status"] in ("done", "complete"):
                agg[1] += 1
        risks: dict[str, int] = {}
        for r in (
            self._db.table("risk_flags").select("transaction_id").eq("resolved", False)
            .in_("transaction_id", ids).execute().data
        ):
            risks[r["transaction_id"]] = risks.get(r["transaction_id"], 0) + 1
        raw_fields: dict[str, list[dict[str, Any]]] = {}
        for f in (
            self._db.table("extracted_fields")
            .select("transaction_id, name, value, confirmed, created_at")
            .in_("transaction_id", ids).in_("name", ["purchase_price", "all_cash"])
            .execute().data
        ):
            raw_fields.setdefault(f["transaction_id"], []).append(f)
        # Resolve each field to its effective value so a counter offer's price
        # supersedes the PA's on the board.
        fields: dict[str, dict[str, str]] = {
            tid: {n: v["value"] for n, v in _effective_fields(rows).items()}
            for tid, rows in raw_fields.items()
        }
        return [_deal_summary(t, props, coe, tasks, risks, fields) for t in txns]

    def list_active_deadlines(self) -> list[dict[str, Any]]:
        """Every deadline across non-archived deals, for the cross-deal calendar."""
        txns = (
            self._db.table("transactions").select("id").neq("status", "archived").execute().data
        )
        ids = [t["id"] for t in txns]
        if not ids:
            return []
        props = {
            p["transaction_id"]: p["address"]
            for p in self._db.table("properties")
            .select("transaction_id, address").in_("transaction_id", ids).execute().data
        }
        return [
            {
                "transaction_id": d["transaction_id"],
                "property_address": props.get(d["transaction_id"]),
                "name": d["name"],
                "due_date": d["due_date"],
                "key": d.get("compute_key"),
            }
            for d in self._db.table("deadlines")
            .select("transaction_id, name, due_date, compute_key")
            .in_("transaction_id", ids).execute().data
        ]

    def list_open_tasks(self) -> list[dict[str, Any]]:
        """Open (not-done) tasks across non-archived deals — the TC's work queue,
        each with its deal address and linked deadline date."""
        txns = (
            self._db.table("transactions").select("id").neq("status", "archived").execute().data
        )
        ids = [t["id"] for t in txns]
        if not ids:
            return []
        props = {
            p["transaction_id"]: p["address"]
            for p in self._db.table("properties")
            .select("transaction_id, address").in_("transaction_id", ids).execute().data
        }
        due = {
            d["id"]: d["due_date"]
            for d in self._db.table("deadlines")
            .select("id, due_date").in_("transaction_id", ids).execute().data
        }
        return [
            {
                "id": t["id"],
                "transaction_id": t["transaction_id"],
                "property_address": props.get(t["transaction_id"]),
                "title": t["title"],
                "status": t["status"],
                "due_date": due.get(t.get("deadline_id")),
                "assigned_party_id": t.get("assigned_party_id"),
            }
            for t in self._db.table("tasks")
            .select("id, transaction_id, title, status, deadline_id, assigned_party_id")
            .in_("transaction_id", ids).execute().data
            if t["status"] not in ("done", "complete")
        ]

    def list_active_transaction_ids(self) -> list[str]:
        rows = (
            self._db.table("transactions").select("id").eq("status", "open").execute().data
        )
        return [r["id"] for r in rows]

    def transaction_exists(self, transaction_id: str) -> bool:
        rows = (
            self._db.table("transactions")
            .select("id")
            .eq("id", transaction_id)
            .limit(1)
            .execute()
            .data
        )
        return bool(rows)

    def party_belongs_to_transaction(self, *, party_id: str, transaction_id: str) -> bool:
        rows = (
            self._db.table("parties")
            .select("id")
            .eq("id", party_id)
            .eq("transaction_id", transaction_id)
            .limit(1)
            .execute()
            .data
        )
        return bool(rows)

    def get_party(self, *, party_id: str, transaction_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("parties")
            .select("*")
            .eq("id", party_id)
            .eq("transaction_id", transaction_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def record_access_token_issued(
        self, *, transaction_id: str, party_id: str, actor: str
    ) -> None:
        # Rule 5: minting a live receiving-end credential is audited. The token
        # itself is never recorded — only who issued one, to whom, and when.
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="party.access_token_issued",
            entity_type="party",
            entity_id=party_id,
        )

    def write_payload(self, *, transaction_id: str, payload: Payload, actor: str) -> dict[str, Any]:
        # Compensated like create_transaction: deleting the document cascades
        # the payload and extracted fields if any later step fails.
        doc = (
            self._db.table("documents")
            .insert(
                {
                    "transaction_id": transaction_id,
                    "external_ref": payload.document_id,
                    "doc_type": payload.document_type,
                    "storage_path": payload.document_storage_ref,
                    "status": "pending",
                }
            )
            .execute()
            .data[0]
        )
        try:
            row = (
                self._db.table("payloads")
                .insert(
                    {
                        "transaction_id": transaction_id,
                        "document_id": doc["id"],
                        "party_id": payload.party_id,
                        "raw": payload.model_dump(),
                    }
                )
                .execute()
                .data[0]
            )
            if payload.extracted_fields:
                self._db.table("extracted_fields").insert(
                    [
                        {
                            "payload_id": row["id"],
                            "transaction_id": transaction_id,
                            # Stamped from the human-verified §5 list — the
                            # payload's own flag is never trusted for this.
                            **{
                                **field.model_dump(),
                                "deadline_driving": field.name in DEADLINE_DRIVING,
                            },
                        }
                        for field in payload.extracted_fields
                    ]
                ).execute()
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="payload.written",
                entity_type="payload",
                entity_id=row["id"],
                details={
                    "document_external_ref": payload.document_id,
                    "field_count": len(payload.extracted_fields),
                    # Manual TC-entered fields arrive already confirmed.
                    "fields_confirmed_on_write": sum(
                        1 for f in payload.extracted_fields if f.confirmed
                    ),
                },
            )
            # Cross-document inconsistency (§2.8): before a re-uploaded PA
            # supersedes the prior one, compare its values against what the TC
            # already confirmed and raise a flag for each material conflict so a
            # changed date/price can't slip in silently.
            if payload.document_type == "purchase_agreement" and payload.extracted_fields:
                existing_confirmed = {
                    r["name"]: r["value"]
                    for r in self._db.table("extracted_fields")
                    .select("name, value")
                    .eq("transaction_id", transaction_id)
                    .eq("confirmed", True)
                    .execute()
                    .data
                    if r["name"] in MATERIAL_FIELDS
                }
                incoming = {f.name: f.value for f in payload.extracted_fields}
                for name, old, new in find_field_conflicts(existing_confirmed, incoming):
                    self._db.table("risk_flags").insert(
                        {
                            "transaction_id": transaction_id,
                            "severity": "critical" if name in CRITICAL_FIELDS else "warning",
                            "description": (
                                f'The new contract shows {name.replace("_", " ")} = "{new}", but '
                                f'the confirmed value is "{old}". Reconcile before the timeline relies on it.'
                            ),
                            "generated_by": "master",
                            "case_key": "document_inconsistency",
                            "resolved": False,
                        }
                    ).execute()
                    self._audit(
                        transaction_id=transaction_id,
                        actor=actor,
                        action="risk_flag.inconsistency",
                        entity_type="risk_flag",
                        entity_id=None,
                        details={"field": name, "old": old, "new": new},
                    )

            # A re-uploaded purchase agreement SUPERSEDES the prior one — there is
            # exactly one PA per deal, so older PA documents (and their cascaded
            # payloads + fields) are removed rather than piling up as duplicates.
            # Other doc types (disclosures, addenda) may legitimately repeat and
            # are never superseded.
            if payload.document_type == "purchase_agreement":
                self._db.table("documents").delete().eq(
                    "transaction_id", transaction_id
                ).eq("doc_type", "purchase_agreement").neq("id", doc["id"]).execute()

            # A counter offer's chain/expiration facts → risk flags (fell-through
            # if unaccepted; "upload the further counter" if subject-to-counter).
            if payload.document_type in COUNTER_OFFER_TYPES and payload.counter_meta:
                for flag in evaluate_counter_flags(payload.document_type, payload.counter_meta):
                    self._db.table("risk_flags").insert(
                        {
                            "transaction_id": transaction_id,
                            "severity": flag["severity"],
                            "description": flag["description"],
                            "generated_by": "master",
                            "case_key": flag["case_key"],
                            "resolved": False,
                        }
                    ).execute()
                    self._audit(
                        transaction_id=transaction_id,
                        actor=actor,
                        action="risk_flag.counter",
                        entity_type="risk_flag",
                        entity_id=None,
                        details={"case": flag["case_key"]},
                    )

            # A preapproval is validated against the deal (borrower, amount, expiry).
            if payload.document_type == "preapproval" and payload.preapproval_meta:
                eff = _effective_fields(
                    self._db.table("extracted_fields")
                    .select("name, value, confirmed, created_at")
                    .eq("transaction_id", transaction_id)
                    .execute()
                    .data
                )
                coe_rows = (
                    self._db.table("deadlines")
                    .select("due_date")
                    .eq("transaction_id", transaction_id)
                    .ilike("name", "%escrow%")
                    .execute()
                    .data
                )
                coe_date = date.fromisoformat(coe_rows[0]["due_date"]) if coe_rows else None
                for flag in evaluate_preapproval_flags(
                    payload.preapproval_meta,
                    (eff.get("buyer_names") or {}).get("value"),
                    (eff.get("loan_amount") or {}).get("value"),
                    coe_date,
                ):
                    self._db.table("risk_flags").insert(
                        {
                            "transaction_id": transaction_id,
                            "severity": flag["severity"],
                            "description": flag["description"],
                            "generated_by": "master",
                            "case_key": flag["case_key"],
                            "resolved": False,
                        }
                    ).execute()
                    self._audit(
                        transaction_id=transaction_id,
                        actor=actor,
                        action="risk_flag.preapproval",
                        entity_type="risk_flag",
                        entity_id=None,
                        details={"case": flag["case_key"]},
                    )

            # A document arriving reopens an archived deal (work resumed).
            self._db.table("transactions").update({"status": "open"}).eq(
                "id", transaction_id
            ).eq("status", "archived").execute()
        except Exception:
            self._db.table("documents").delete().eq("id", doc["id"]).execute()
            raise
        return row

    def confirm_fields(self, *, transaction_id: str, field_ids: list[str], actor: str) -> int:
        updated = (
            self._db.table("extracted_fields")
            .update({"confirmed": True})
            .eq("transaction_id", transaction_id)
            .in_("id", field_ids)
            .execute()
            .data
        )
        count = len(updated)
        if count:
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="field.confirmed",
                entity_type="extracted_field",
                entity_id=None,
                details={"count": count, "field_ids": [f["id"] for f in updated]},
            )
        return count

    def add_manual_field(
        self, *, transaction_id: str, name: str, value: str, actor: str
    ) -> dict[str, Any]:
        """Attach a TC-entered field value to an existing deal — for §5 fields the
        extraction missed (e.g. an acceptance date the model couldn't find). Hand-
        entered, so it lands already confirmed. The deadline_driving flag is
        stamped from the human-verified §5 list, never from the caller. Requires a
        payload to attach to (extracted_fields.payload_id is NOT NULL) — the most
        recent one for the deal."""
        payloads = (
            self._db.table("payloads")
            .select("id")
            .eq("transaction_id", transaction_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not payloads:
            raise NoPayloadForManualField
        inserted = (
            self._db.table("extracted_fields")
            .insert(
                {
                    "payload_id": payloads[0]["id"],
                    "transaction_id": transaction_id,
                    "name": name,
                    "value": value,
                    "confidence": 1.0,  # hand-entered by the TC
                    "confirmed": True,
                    "deadline_driving": name in DEADLINE_DRIVING,
                }
            )
            .execute()
            .data[0]
        )
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="field.added_manually",
            entity_type="extracted_field",
            entity_id=inserted["id"],
            details={"name": name, "deadline_driving": name in DEADLINE_DRIVING},
        )
        return inserted

    def create_stub_timeline(self, *, transaction_id: str, actor: str) -> dict[str, Any]:
        # The confirmation gate (Prompt 4): no unconfirmed OR missing
        # deadline-driving field may ever create a Deadline/Task.
        rows = (
            self._db.table("extracted_fields")
            .select("name, confirmed")
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        violations = _deadline_gate_violations(rows)
        if violations:
            raise DeadlineFieldsUnconfirmed(violations)
        existing = (
            self._db.table("deadlines")
            .select("id")
            .eq("transaction_id", transaction_id)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            raise TimelineAlreadyExists
        today = date.today()
        deadlines: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        try:
            for deadline_name, task_title, days in _STUB_TIMELINE:
                deadline = (
                    self._db.table("deadlines")
                    .insert(
                        {
                            "transaction_id": transaction_id,
                            "name": deadline_name,
                            "due_date": (today + timedelta(days=days)).isoformat(),
                        }
                    )
                    .execute()
                    .data[0]
                )
                task = (
                    self._db.table("tasks")
                    .insert(
                        {
                            "transaction_id": transaction_id,
                            "deadline_id": deadline["id"],
                            "title": task_title,
                        }
                    )
                    .execute()
                    .data[0]
                )
                deadlines.append(deadline)
                tasks.append(task)
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="timeline.stub_generated",
                entity_type="deadline",
                entity_id=None,
                details={"deadlines": len(deadlines), "tasks": len(tasks), "stub": True},
            )
        except Exception:
            self._db.table("deadlines").delete().eq("transaction_id", transaction_id).execute()
            raise
        return {"deadlines": deadlines, "tasks": tasks}

    def create_stub_draft(self, *, transaction_id: str, actor: str) -> dict[str, Any]:
        message = (
            self._db.table("messages")
            .insert(
                {
                    "transaction_id": transaction_id,
                    "subject": _STUB_DRAFT_SUBJECT,
                    "body": _STUB_DRAFT_BODY,
                    "status": "draft",
                }
            )
            .execute()
            .data[0]
        )
        try:
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="message.drafted",
                entity_type="message",
                entity_id=message["id"],
                details={"stub": True},
            )
        except Exception:
            self._db.table("messages").delete().eq("id", message["id"]).execute()
            raise
        return {"message": message, "why": _STUB_DRAFT_WHY}

    def create_party(
        self,
        *,
        transaction_id: str,
        name: str,
        role: str,
        email: str | None,
        permission_tier: str,
        actor: str,
        phone: str | None = None,
        company: str | None = None,
    ) -> dict[str, Any]:
        party = (
            self._db.table("parties")
            .insert(
                {
                    "transaction_id": transaction_id,
                    "name": name,
                    "role": role,
                    "email": email,
                    "phone": phone,
                    "company": company,
                    "permission_tier": permission_tier,
                }
            )
            .execute()
            .data[0]
        )
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="party.added",
            entity_type="party",
            entity_id=party["id"],
            details={"role": role},
        )
        return party

    def update_party(
        self, *, transaction_id: str, party_id: str, fields: dict[str, Any], actor: str
    ) -> dict[str, Any] | None:
        rows = (
            self._db.table("parties")
            .update(fields)
            .eq("id", party_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="party.updated",
            entity_type="party",
            entity_id=party_id,
            # Field NAMES only — never the contact values (Rule 5 logging).
            details={"fields": sorted(fields.keys())},
        )
        return rows[0]

    def derive_parties_from_fields(self, *, transaction_id: str, actor: str) -> int:
        """Create the Party records implied by the deal's CONFIRMED §5 fields
        (buyers/sellers/agents/escrow/title). Idempotent: skips any (role, name)
        that already exists, so re-confirming never duplicates a contact."""
        # Contacts are informational (not deadline-driving), so parties populate
        # from ALL extracted fields — the TC sees them right after upload, and
        # agent email/phone backfill without waiting on field confirmation.
        rows = (
            self._db.table("extracted_fields")
            .select("name, value")
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        desired = derive_parties({r["name"]: r["value"] for r in rows})
        if not desired:
            return 0
        existing = (
            self._db.table("parties")
            .select("id, role, name, email, phone, company")
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        by_key = {party_key(p["role"], p["name"]): p for p in existing}
        created = 0
        for d in desired:
            match = by_key.get(party_key(d.role, d.name))
            if match is not None:
                # Backfill contact details newly available (e.g. agent email/phone
                # from a later extraction) without overwriting what's there.
                patch = {
                    col: val
                    for col, val in (("email", d.email), ("phone", d.phone), ("company", d.company))
                    if val and not match.get(col)
                }
                if patch:
                    self.update_party(
                        transaction_id=transaction_id, party_id=match["id"], fields=patch, actor=actor
                    )
                continue
            new_party = self.create_party(
                transaction_id=transaction_id,
                name=d.name,
                role=d.role,
                email=d.email,
                phone=d.phone,
                company=d.company,
                permission_tier=tier_for(d.role),
                actor=actor,
            )
            by_key[party_key(d.role, d.name)] = new_party
            created += 1
        return created

    def derive_tasks_from_fields(self, *, transaction_id: str, actor: str) -> int:
        """Create action-item tasks implied by confirmed allocation fields (the
        home-warranty issuer rule). generated_by='rule' + compute_key make it
        idempotent and safe from compliance re-runs; assigned to the relevant
        agent when that party exists."""
        rows = (
            self._db.table("extracted_fields")
            .select("name, value")
            .eq("transaction_id", transaction_id)
            .eq("confirmed", True)
            .execute()
            .data
        )
        desired = derive_tasks({r["name"]: r["value"] for r in rows})
        if not desired:
            return 0
        existing_keys = {
            t["compute_key"]
            for t in (
                self._db.table("tasks")
                .select("compute_key")
                .eq("transaction_id", transaction_id)
                .execute()
                .data
            )
            if t.get("compute_key")
        }
        parties = (
            self._db.table("parties")
            .select("role, id")
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        role_to_party: dict[str, str] = {}
        for p in parties:
            role_to_party.setdefault(p["role"], p["id"])
        created = 0
        for d in desired:
            if d.key in existing_keys:
                continue
            task = (
                self._db.table("tasks")
                .insert(
                    {
                        "transaction_id": transaction_id,
                        "title": d.title,
                        "status": "pending",
                        "assigned_party_id": role_to_party.get(d.assign_role),
                        "generated_by": "rule",
                        "compute_key": d.key,
                    }
                )
                .execute()
                .data[0]
            )
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="task.created",
                entity_type="task",
                entity_id=task["id"],
                details={"source": "rule", "rule": d.key},
            )
            existing_keys.add(d.key)
            created += 1
        return created

    def lender_party(self, transaction_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("parties")
            .select("*")
            .eq("transaction_id", transaction_id)
            .in_("role", ["lender", "loan_officer"])
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def assign_task(
        self, *, transaction_id: str, task_id: str, party_id: str, actor: str
    ) -> dict[str, Any] | None:
        rows = (
            self._db.table("tasks")
            .update({"assigned_party_id": party_id})
            .eq("id", task_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="task.assigned",
            entity_type="task",
            entity_id=task_id,
            details={"party_id": party_id},
        )
        return rows[0]

    def create_task(
        self,
        *,
        transaction_id: str,
        title: str,
        actor: str,
        deadline_id: str | None = None,
        assigned_party_id: str | None = None,
        description: str | None = None,
        due_date: str | None = None,
        priority: str = "normal",
    ) -> dict[str, Any]:
        """A TC's own ad-hoc task. Tagged generated_by='tc' so a compliance
        re-run (which only clears its own prior-run rows) never removes it.
        Extra metadata (description/due_date/priority) rides in the audit details
        — the tasks table has no columns for it here — and the API reads it back."""
        task = (
            self._db.table("tasks")
            .insert(
                {
                    "transaction_id": transaction_id,
                    "title": title,
                    "status": "pending",
                    "deadline_id": deadline_id,
                    "assigned_party_id": assigned_party_id,
                    "generated_by": "tc",
                }
            )
            .execute()
            .data[0]
        )
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="task.created",
            entity_type="task",
            entity_id=task["id"],
            details=_task_meta("tc", description, due_date, priority),
        )
        return {**task, "description": description, "due_date": due_date, "priority": priority}

    def set_task_status(
        self, *, transaction_id: str, task_id: str, status: str, actor: str
    ) -> dict[str, Any] | None:
        rows = (
            self._db.table("tasks")
            .update({"status": status})
            .eq("id", task_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="task.status_changed",
            entity_type="task",
            entity_id=task_id,
            details={"status": status},
        )
        return rows[0]

    def loan_deadline_iso(self, transaction_id: str) -> str | None:
        rows = (
            self._db.table("deadlines")
            .select("due_date")
            .eq("transaction_id", transaction_id)
            .eq("compute_key", "loan_contingency")
            .limit(1)
            .execute()
            .data
        )
        return rows[0]["due_date"] if rows else None

    def create_message(
        self,
        *,
        transaction_id: str,
        subject: str,
        body: str,
        party_id: str | None,
        actor: str,
        action: str = "message.drafted",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message = (
            self._db.table("messages")
            .insert(
                {
                    "transaction_id": transaction_id,
                    "subject": subject,
                    "body": body,
                    "party_id": party_id,
                    "status": "draft",
                }
            )
            .execute()
            .data[0]
        )
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action=action,
            entity_type="message",
            entity_id=message["id"],
            details=details or {},
        )
        return message

    def delete_message(self, *, transaction_id: str, message_id: str, actor: str) -> str | None:
        """Discard a message. Refuses to delete one that's already sent (audit
        trail). Returns 'deleted', 'sent' (refused), or None (not found)."""
        rows = (
            self._db.table("messages")
            .select("status")
            .eq("id", message_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        status = rows[0]["status"]
        if status == "sent":
            return "sent"
        self._db.table("messages").delete().eq("id", message_id).eq(
            "transaction_id", transaction_id
        ).execute()
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="message.discarded",
            entity_type="message",
            entity_id=message_id,
            details={"status": status},
        )
        return "deleted"

    def delete_reminder(self, *, transaction_id: str, reminder_id: str, actor: str) -> bool:
        """Dismiss a follow-up reminder (the TC got a reply or handled it)."""
        rows = (
            self._db.table("reminders")
            .delete()
            .eq("id", reminder_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return False
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="reminder.dismissed",
            entity_type="reminder",
            entity_id=reminder_id,
            details={},
        )
        return True

    def document_signed_url(self, *, transaction_id: str, document_id: str) -> str | None:
        """A short-lived signed URL to view a stored document (opens in a new
        tab). None when the document isn't on this deal or has no stored file."""
        rows = (
            self._db.table("documents")
            .select("storage_path")
            .eq("id", document_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows or not rows[0].get("storage_path"):
            return None
        res = self._db.storage.from_(ATTACHMENT_BUCKET).create_signed_url(rows[0]["storage_path"], 300)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        return None

    def add_party_document(
        self, *, transaction_id: str, party_id: str, filename: str,
        content_base64: str, doc_type: str, actor: str,
    ) -> dict[str, Any]:
        """A party uploads their own document (e.g. an inspector's report, a
        buyer's proof of funds). Stored in the private bucket; the row is tagged
        external_ref='party:{id}' so it's attributable back to who uploaded it."""
        import base64
        import binascii
        import re as _re

        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("document content is not valid base64") from exc
        safe = _re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120] or "upload"
        path = f"{transaction_id}/party/{party_id}/{uuid.uuid4()}_{safe}"
        self._db.storage.from_(ATTACHMENT_BUCKET).upload(
            path, content, {"content-type": "application/octet-stream"}
        )
        doc = (
            self._db.table("documents")
            .insert(
                {
                    "transaction_id": transaction_id,
                    "external_ref": f"party:{party_id}",
                    "doc_type": doc_type,
                    "storage_path": path,
                    "status": "uploaded",
                }
            )
            .execute()
            .data[0]
        )
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="document.party_uploaded",
            entity_type="document",
            entity_id=doc["id"],
            details={"party_id": party_id, "doc_type": doc_type, "filename": filename},
        )
        return doc

    def approve_and_send(
        self,
        *,
        transaction_id: str,
        message_id: str,
        actor: str,
        subject: str | None,
        body: str | None,
        mailer: Any,
        followup_days: int,
    ) -> dict[str, Any] | None:
        """Rule 3 core: record the human Approval FIRST, apply the TC's edits,
        then send via the (guarded) mailer. `sent` is set only on a successful
        send. On send failure (guard off, allowlist miss, transient error) the
        message stays `approved` and this same endpoint RETRIES it (no second
        Approval — the human already approved). The ONLY place a message
        transitions to `sent`."""
        rows = (
            self._db.table("messages")
            .select("*")
            .eq("id", message_id)
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        if not rows:
            return None
        msg = rows[0]
        # 'draft' -> first approval; 'approved' -> retry the send; 'sent' -> no.
        if msg["status"] not in ("draft", "approved"):
            raise MessageNotSendable

        recipient = self._recipient_email(msg.get("party_id"))
        if not recipient:
            raise NoRecipient

        final_subject = subject if subject is not None else msg["subject"]
        final_body = body if body is not None else msg["body"]

        if msg["status"] == "draft":
            approval = (
                self._db.table("approvals")
                .insert(
                    {
                        "transaction_id": transaction_id,
                        "message_id": message_id,
                        "approved_by": actor,
                    }
                )
                .execute()
                .data[0]
            )
            try:
                self._db.table("messages").update(
                    {
                        "status": "approved",
                        "subject": final_subject,
                        "body": final_body,
                        "approved_by": actor,
                        "approved_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", message_id).execute()
            except Exception:
                # Compensate: don't leave an orphaned Approval on a failed flip.
                self._db.table("approvals").delete().eq("id", approval["id"]).execute()
                raise
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="message.approved",
                entity_type="message",
                entity_id=message_id,
                details={"approval_id": approval["id"]},
            )
        else:  # retry of an already-approved-but-unsent message (edits optional)
            if subject is not None or body is not None:
                self._db.table("messages").update(
                    {"subject": final_subject, "body": final_body}
                ).eq("id", message_id).execute()

        # The send — the only outbound path. Failure leaves it approved (retryable).
        sent_result = mailer.send(to=recipient, subject=final_subject, body=final_body)

        sent = (
            self._db.table("messages")
            .update(
                {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "provider_message_id": sent_result.provider_message_id,
                }
            )
            .eq("id", message_id)
            .execute()
            .data[0]
        )
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="message.sent",
            entity_type="message",
            entity_id=message_id,
            details={"provider_message_id": sent_result.provider_message_id},
        )
        # Follow-up reminder — surfaces to the TC; it never sends anything.
        remind_at = datetime.now(timezone.utc) + timedelta(days=followup_days)
        self._db.table("reminders").insert(
            {
                "transaction_id": transaction_id,
                "message_id": message_id,
                "remind_at": remind_at.isoformat(),
                "note": "No reply yet — consider following up.",
            }
        ).execute()
        return {"message": sent, "approval": approval}

    def send_invite(
        self, *, transaction_id: str, party_id: str, to: str, subject: str, body: str,
        mailer: Any, actor: str,
    ) -> None:
        """TC-initiated invite email (a human tap, not auto-send). Sends through
        the guarded mailer and audits; the caller handles the send-disabled case."""
        mailer.send(to=to, subject=subject, body=body)
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="party.invite_sent",
            entity_type="party",
            entity_id=party_id,
            details={},
        )

    def _recipient_email(self, party_id: str | None) -> str | None:
        if not party_id:
            return None
        rows = self._db.table("parties").select("email").eq("id", party_id).execute().data
        return rows[0]["email"] if rows and rows[0].get("email") else None

    def apply_compliance_result(self, *, result: ComplianceResult, actor: str) -> dict[str, Any]:
        transaction_id = result.transaction_id
        # The §11 gate holds here too: no unconfirmed/missing deadline-driving
        # field may drive a Deadline/Task.
        rows = (
            self._db.table("extracted_fields")
            .select("name, confirmed")
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        violations = _deadline_gate_violations(rows)
        if violations:
            raise DeadlineFieldsUnconfirmed(violations)

        # Carry over mutable state a receiving-end party may have set on a
        # prior run's compliance task (e.g. status='done'), keyed by compute_key.
        prior_tasks = (
            self._db.table("tasks")
            .select("compute_key, status, assigned_party_id")
            .eq("transaction_id", transaction_id)
            .eq("generated_by", "compliance")
            .execute()
            .data
        )
        prior_task_state = {t["compute_key"]: t for t in prior_tasks if t.get("compute_key")}

        run_id = str(uuid.uuid4())
        # Insert the NEW run first (tagged run_id); the prior run stays live until
        # this fully lands. A failure mid-insert compensates by deleting only the
        # new run's rows (mirrors write_payload), leaving the old timeline intact
        # and its audit trail untouched.
        try:
            deadline_id_by_key: dict[str, str] = {}
            for d in result.deadlines:
                row = (
                    self._db.table("deadlines")
                    .insert(
                        {
                            "transaction_id": transaction_id,
                            "name": d.name,
                            "due_date": d.due_date.isoformat(),
                            "generated_by": "compliance",
                            "compliance_run_id": run_id,
                            "compute_key": d.key,
                        }
                    )
                    .execute()
                    .data[0]
                )
                deadline_id_by_key[d.key] = row["id"]

            task_id_by_key: dict[str, str] = {}
            for t in result.tasks:
                carried = prior_task_state.get(t.key, {})
                row = (
                    self._db.table("tasks")
                    .insert(
                        {
                            "transaction_id": transaction_id,
                            "title": t.title,
                            "deadline_id": deadline_id_by_key.get(t.deadline_key or ""),
                            # preserve completion + assignee across re-runs
                            "status": carried.get("status", "pending"),
                            "assigned_party_id": carried.get("assigned_party_id"),
                            "generated_by": "compliance",
                            "compliance_run_id": run_id,
                            "compute_key": t.key,
                        }
                    )
                    .execute()
                    .data[0]
                )
                task_id_by_key[t.key] = row["id"]
            for t in result.tasks:
                if t.depends_on_key and t.depends_on_key in task_id_by_key:
                    self._db.table("tasks").update(
                        {"depends_on_task_id": task_id_by_key[t.depends_on_key]}
                    ).eq("id", task_id_by_key[t.key]).execute()

            for f in result.risk_flags:
                self._db.table("risk_flags").insert(
                    {
                        "transaction_id": transaction_id,
                        "severity": f.severity,
                        "description": f.description,
                        "deadline_id": deadline_id_by_key.get(f.deadline_key or ""),
                        "generated_by": "compliance",
                        "compliance_run_id": run_id,
                        "case_key": f.case,
                    }
                ).execute()

            # Rule 3: drafts land as 'draft' messages only — nothing sends here.
            # Resolve to_role -> a party so the draft is later sendable to them.
            # First party per role wins (roles are singular in the MVP data model).
            role_to_party: dict[str, str] = {}
            for p in (
                self._db.table("parties")
                .select("id, role")
                .eq("transaction_id", transaction_id)
                .order("created_at")
                .execute()
                .data
            ):
                role_to_party.setdefault(p["role"], p["id"])
            for r in result.draft_reminders:
                self._db.table("messages").insert(
                    {
                        "transaction_id": transaction_id,
                        "subject": r.subject,
                        "body": r.body,
                        "status": "draft",
                        "party_id": role_to_party.get(r.to_role) if r.to_role else None,
                        "generated_by": "compliance",
                        "compliance_run_id": run_id,
                    }
                ).execute()
        except Exception:
            for table in ("messages", "risk_flags", "tasks", "deadlines"):
                self._db.table(table).delete().eq("compliance_run_id", run_id).execute()
            raise

        # New run landed — now remove the PRIOR run's rows. Deadlines/tasks/flags
        # are regenerated freely; messages only if still 'draft' (an
        # approved/sent compliance message keeps its Approval + audit — the record
        # stays append-only).
        for table in ("risk_flags", "tasks", "deadlines"):
            self._db.table(table).delete().eq("transaction_id", transaction_id).eq(
                "generated_by", "compliance"
            ).neq("compliance_run_id", run_id).execute()
        self._db.table("messages").delete().eq("transaction_id", transaction_id).eq(
            "generated_by", "compliance"
        ).eq("status", "draft").neq("compliance_run_id", run_id).execute()

        summary = {
            "deadlines": len(result.deadlines),
            "tasks": len(result.tasks),
            "risk_flags": len(result.risk_flags),
            "draft_reminders": len(result.draft_reminders),
        }
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="compliance.run",
            entity_type="transaction",
            entity_id=transaction_id,
            details={**summary, "run_id": run_id},
        )
        return summary

    def get_full_state(self, transaction_id: str) -> dict[str, Any] | None:
        txns = self._db.table("transactions").select("*").eq("id", transaction_id).execute().data
        if not txns:
            return None
        props = (
            self._db.table("properties")
            .select("*")
            .eq("transaction_id", transaction_id)
            .execute()
            .data
        )
        state: dict[str, Any] = {
            "transaction": txns[0],
            "property": props[0] if props else None,
        }
        for table in _CHILD_TABLES:
            state[table] = (
                self._db.table(table)
                .select("*")
                .eq("transaction_id", transaction_id)
                .execute()
                .data
            )
        state["timeline_gate"] = _deadline_gate_state(state["extracted_fields"])
        state["effective_fields"] = _effective_fields(state["extracted_fields"])
        return state
