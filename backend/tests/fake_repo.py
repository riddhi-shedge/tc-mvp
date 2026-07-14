"""In-memory fake of the MasterRepo interface — synthetic state only.

Mirrors the behavior the Supabase-backed repo must have (including audit rows on
every state change) so API tests run in isolation with no network.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.contracts.fields import DEADLINE_DRIVING
from app.contracts.payload import Payload
from app.master.repo import (
    _STUB_DRAFT_BODY,
    _STUB_DRAFT_SUBJECT,
    _STUB_DRAFT_WHY,
    _STUB_TIMELINE,
    DeadlineFieldsUnconfirmed,
    MessageNotSendable,
    TimelineAlreadyExists,
    _deadline_gate_violations,
)


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
        self.deadlines: list[dict[str, Any]] = []
        self.tasks: list[dict[str, Any]] = []
        self.messages: dict[str, dict[str, Any]] = {}
        self.approvals: list[dict[str, Any]] = []
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

    def list_transactions(self) -> list[dict[str, Any]]:
        return [
            {**t, "property_address": (self.properties.get(t["id"]) or {}).get("address")}
            for t in self.transactions.values()
        ]

    def transaction_exists(self, transaction_id: str) -> bool:
        return transaction_id in self.transactions

    def confirm_fields(self, *, transaction_id: str, field_ids: list[str], actor: str) -> int:
        confirmed_ids = []
        for field in self.extracted_fields:
            if field["transaction_id"] == transaction_id and field["id"] in field_ids:
                field["confirmed"] = True
                confirmed_ids.append(field["id"])
        if confirmed_ids:
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="field.confirmed",
                entity_type="extracted_field",
                entity_id=None,
                details={"count": len(confirmed_ids), "field_ids": confirmed_ids},
            )
        return len(confirmed_ids)

    def create_stub_timeline(self, *, transaction_id: str, actor: str) -> dict[str, Any]:
        rows = [
            {"name": f["name"], "confirmed": f["confirmed"]}
            for f in self.extracted_fields
            if f["transaction_id"] == transaction_id
        ]
        violations = _deadline_gate_violations(rows)
        if violations:
            raise DeadlineFieldsUnconfirmed(violations)
        if any(d["transaction_id"] == transaction_id for d in self.deadlines):
            raise TimelineAlreadyExists
        today = date.today()
        deadlines, tasks = [], []
        for deadline_name, task_title, days in _STUB_TIMELINE:
            deadline = {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "name": deadline_name,
                "due_date": (today + timedelta(days=days)).isoformat(),
            }
            task = {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "deadline_id": deadline["id"],
                "title": task_title,
                "status": "pending",
            }
            self.deadlines.append(deadline)
            self.tasks.append(task)
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
        return {"deadlines": deadlines, "tasks": tasks}

    def create_stub_draft(self, *, transaction_id: str, actor: str) -> dict[str, Any]:
        message = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "subject": _STUB_DRAFT_SUBJECT,
            "body": _STUB_DRAFT_BODY,
            "status": "draft",
            "created_at": _now(),
            "sent_at": None,
        }
        self.messages[message["id"]] = message
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="message.drafted",
            entity_type="message",
            entity_id=message["id"],
            details={"stub": True},
        )
        return {"message": message, "why": _STUB_DRAFT_WHY}

    def approve_and_send_fake(
        self, *, transaction_id: str, message_id: str, actor: str
    ) -> dict[str, Any] | None:
        message = self.messages.get(message_id)
        if message is None or message["transaction_id"] != transaction_id:
            return None
        if message["status"] != "draft":
            raise MessageNotSendable
        approval = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "message_id": message_id,
            "approved_by": actor,
            "approved_at": _now(),
        }
        self.approvals.append(approval)
        message["status"] = "approved"
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="message.approved",
            entity_type="message",
            entity_id=message_id,
            details={"approval_id": approval["id"]},
        )
        message["status"] = "sent"
        message["sent_at"] = _now()
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="message.sent",
            entity_type="message",
            entity_id=message_id,
            details={"fake": True},
        )
        return {"message": message, "approval": approval}

    def party_belongs_to_transaction(self, *, party_id: str, transaction_id: str) -> bool:
        party = self.parties.get(party_id)
        return party is not None and party["transaction_id"] == transaction_id

    def write_payload(self, *, transaction_id: str, payload: Payload, actor: str) -> dict[str, Any]:
        doc = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "external_ref": payload.document_id,
            "doc_type": payload.document_type,
            "storage_path": payload.document_storage_ref,
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
                    # Stamped from the human-verified §5 list, never trusted.
                    "deadline_driving": field.name in DEADLINE_DRIVING,
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
                "fields_confirmed_on_write": sum(
                    1 for f in payload.extracted_fields if f.confirmed
                ),
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
            "deadlines": [d for d in self.deadlines if d["transaction_id"] == transaction_id],
            "tasks": [t for t in self.tasks if t["transaction_id"] == transaction_id],
            "messages": [
                m for m in self.messages.values() if m["transaction_id"] == transaction_id
            ],
            "reminders": [],
            "risk_flags": [],
            "approvals": [a for a in self.approvals if a["transaction_id"] == transaction_id],
            "audit_log": [a for a in self.audit_log if a["transaction_id"] == transaction_id],
        }
