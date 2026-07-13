"""Repository for the master / SOR (part b).

The only code that touches the database. Every mutating method writes its own
audit_log entry — the audit log records every state change (Prompt 1). Uses the
Supabase service-role key: backend only, never exposed to a frontend.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from app.contracts.payload import Payload


class TimelineAlreadyExists(Exception):
    """A (stub) timeline was already generated for this transaction."""


class MessageNotSendable(Exception):
    """The message is not in 'draft' state — it cannot be approved and sent."""


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

    def transaction_exists(self, transaction_id: str) -> bool: ...

    def party_belongs_to_transaction(self, *, party_id: str, transaction_id: str) -> bool: ...

    def write_payload(
        self, *, transaction_id: str, payload: Payload, actor: str
    ) -> dict[str, Any]: ...

    def get_full_state(self, transaction_id: str) -> dict[str, Any] | None: ...

    def confirm_fields(self, *, transaction_id: str, field_ids: list[str], actor: str) -> int: ...

    def create_stub_timeline(self, *, transaction_id: str, actor: str) -> dict[str, Any]: ...

    def create_stub_draft(self, *, transaction_id: str, actor: str) -> dict[str, Any]: ...

    def approve_and_send_fake(
        self, *, transaction_id: str, message_id: str, actor: str
    ) -> dict[str, Any] | None: ...


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
        from supabase import create_client

        self._db = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )

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

    def write_payload(self, *, transaction_id: str, payload: Payload, actor: str) -> dict[str, Any]:
        # Compensated like create_transaction: deleting the document cascades
        # the payload and extracted fields if any later step fails.
        doc = (
            self._db.table("documents")
            .insert(
                {
                    "transaction_id": transaction_id,
                    "external_ref": payload.document_id,
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
                            **field.model_dump(),
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
                },
            )
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

    def create_stub_timeline(self, *, transaction_id: str, actor: str) -> dict[str, Any]:
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

    def approve_and_send_fake(
        self, *, transaction_id: str, message_id: str, actor: str
    ) -> dict[str, Any] | None:
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
        if rows[0]["status"] != "draft":
            raise MessageNotSendable
        # Rule 3 shape: the human Approval row is recorded FIRST; only then may
        # the message transition draft -> approved -> sent. The send is FAKE —
        # nothing leaves the system in Phase 2 (no Postmark call anywhere).
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
        self._db.table("messages").update({"status": "approved"}).eq("id", message_id).execute()
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="message.approved",
            entity_type="message",
            entity_id=message_id,
            details={"approval_id": approval["id"]},
        )
        sent = (
            self._db.table("messages")
            .update(
                {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
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
            details={"fake": True},
        )
        return {"message": sent, "approval": approval}

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
        return state
