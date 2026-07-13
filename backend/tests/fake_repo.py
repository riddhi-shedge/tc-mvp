"""In-memory fake of the MasterRepo interface — synthetic state only.

Mirrors the behavior the Supabase-backed repo must have (including audit rows on
every state change) so API tests run in isolation with no network.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.contracts.payload import Payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryRepo:
    def __init__(self) -> None:
        self.transactions: dict[str, dict[str, Any]] = {}
        self.properties: dict[str, dict[str, Any]] = {}
        self.parties: dict[str, dict[str, Any]] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.extracted_fields: list[dict[str, Any]] = []
        self.audit_log: list[dict[str, Any]] = []

    def add_party(self, *, transaction_id: str, name: str, role: str) -> dict[str, Any]:
        """Test helper — party CRUD arrives in a later phase."""
        party = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "name": name,
            "role": role,
        }
        self.parties[party["id"]] = party
        return party

    # -- audit ---------------------------------------------------------------
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
        self.audit_log.append(
            {
                "transaction_id": transaction_id,
                "actor": actor,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": details or {},
                "created_at": _now(),
            }
        )

    # -- MasterRepo interface --------------------------------------------------
    def create_transaction(self, *, property_address: str, actor: str) -> dict[str, Any]:
        txn_id = str(uuid.uuid4())
        txn = {"id": txn_id, "status": "open", "created_at": _now()}
        prop = {
            "id": str(uuid.uuid4()),
            "transaction_id": txn_id,
            "address": property_address,
            "state": "CA",
        }
        self.transactions[txn_id] = txn
        self.properties[txn_id] = prop
        self._audit(
            transaction_id=txn_id,
            actor=actor,
            action="transaction.created",
            entity_type="transaction",
            entity_id=txn_id,
            details={"property_address": property_address},
        )
        return {**txn, "property": prop}

    def transaction_exists(self, transaction_id: str) -> bool:
        return transaction_id in self.transactions

    def party_belongs_to_transaction(self, *, party_id: str, transaction_id: str) -> bool:
        party = self.parties.get(party_id)
        return party is not None and party["transaction_id"] == transaction_id

    def write_payload(self, *, transaction_id: str, payload: Payload, actor: str) -> dict[str, Any]:
        doc = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "external_ref": payload.document_id,
            "status": "pending",
        }
        self.documents[doc["id"]] = doc
        row = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "document_id": doc["id"],
            "party_id": payload.party_id,
            "raw": payload.model_dump(),
        }
        self.payloads[row["id"]] = row
        for field in payload.extracted_fields:
            self.extracted_fields.append(
                {
                    "id": str(uuid.uuid4()),
                    "payload_id": row["id"],
                    "transaction_id": transaction_id,
                    **field.model_dump(),
                }
            )
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
        return row

    def get_full_state(self, transaction_id: str) -> dict[str, Any] | None:
        txn = self.transactions.get(transaction_id)
        if txn is None:
            return None
        return {
            "transaction": txn,
            "property": self.properties.get(transaction_id),
            "parties": [p for p in self.parties.values() if p["transaction_id"] == transaction_id],
            "documents": [
                d for d in self.documents.values() if d["transaction_id"] == transaction_id
            ],
            "payloads": [
                p for p in self.payloads.values() if p["transaction_id"] == transaction_id
            ],
            "extracted_fields": [
                f for f in self.extracted_fields if f["transaction_id"] == transaction_id
            ],
            "deadlines": [],
            "tasks": [],
            "messages": [],
            "reminders": [],
            "risk_flags": [],
            "approvals": [],
            "audit_log": [a for a in self.audit_log if a["transaction_id"] == transaction_id],
        }
