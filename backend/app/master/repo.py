"""Repository for the master / SOR (part b).

The only code that touches the database. Every mutating method writes its own
audit_log entry — the audit log records every state change (Prompt 1). Uses the
Supabase service-role key: backend only, never exposed to a frontend.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from app.contracts.payload import Payload


class MasterRepo(Protocol):
    """Interface the API depends on; tests substitute an in-memory fake."""

    def create_transaction(self, *, property_address: str, actor: str) -> dict[str, Any]: ...

    def transaction_exists(self, transaction_id: str) -> bool: ...

    def party_belongs_to_transaction(self, *, party_id: str, transaction_id: str) -> bool: ...

    def write_payload(
        self, *, transaction_id: str, payload: Payload, actor: str
    ) -> dict[str, Any]: ...

    def get_full_state(self, transaction_id: str) -> dict[str, Any] | None: ...


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
