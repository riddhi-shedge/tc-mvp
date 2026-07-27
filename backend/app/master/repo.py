"""Repository for the master / SOR (part b).

The only code that touches the database. Every mutating method writes its own
audit_log entry — the audit log records every state change (Prompt 1). Uses the
Supabase service-role key: backend only, never exposed to a frontend.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from app.common.db import ThreadLocalSupabase
from app.contracts.compliance import ComplianceResult
from app.contracts.fields import DEADLINE_DRIVING
from app.contracts.payload import Payload
from app.master.deal_tasks import derive_tasks
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
DEAL_STAGES: tuple[str, ...] = ("new", "funds", "cont", "removed", "closing", "closed")


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
        "stage": txn.get("stage") or "new",
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

    def delete_transaction(self, *, transaction_id: str, actor: str) -> bool: ...

    def set_transaction_stage(
        self, *, transaction_id: str, stage: str, actor: str
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
        self, *, transaction_id: str, status: str, actor: str, action: str
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
            details={"status": status},
        )
        return rows[0]

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
        fields: dict[str, dict[str, str]] = {}
        for f in (
            self._db.table("extracted_fields").select("transaction_id, name, value")
            .in_("transaction_id", ids).in_("name", ["purchase_price", "all_cash"])
            .execute().data
        ):
            fields.setdefault(f["transaction_id"], {})[f["name"]] = f["value"]
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
            # A re-uploaded purchase agreement SUPERSEDES the prior one — there is
            # exactly one PA per deal, so older PA documents (and their cascaded
            # payloads + fields) are removed rather than piling up as duplicates.
            # Other doc types (disclosures, addenda) may legitimately repeat and
            # are never superseded.
            if payload.document_type == "purchase_agreement":
                self._db.table("documents").delete().eq(
                    "transaction_id", transaction_id
                ).eq("doc_type", "purchase_agreement").neq("id", doc["id"]).execute()
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
    ) -> dict[str, Any]:
        """A TC's own ad-hoc task. Tagged generated_by='tc' so a compliance
        re-run (which only clears its own prior-run rows) never removes it."""
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
            details={"source": "tc"},
        )
        return task

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
                "note": "No reply from lender — consider following up.",
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
        return state
