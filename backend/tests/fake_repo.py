"""In-memory fake of the MasterRepo interface — synthetic state only.

Mirrors the behavior the Supabase-backed repo must have (including audit rows on
every state change) so API tests run in isolation with no network.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.contracts.documents import COUNTER_OFFER_TYPES
from app.contracts.fields import DEADLINE_DRIVING
from app.contracts.payload import Payload
from app.master.deal_tasks import derive_tasks
from app.master.parties import derive_parties, party_key, tier_for
from app.master.repo import (
    _STUB_DRAFT_BODY,
    _STUB_DRAFT_SUBJECT,
    _STUB_DRAFT_WHY,
    _STUB_TIMELINE,
    DeadlineFieldsUnconfirmed,
    MessageNotSendable,
    NoPayloadForManualField,
    NoRecipient,
    TimelineAlreadyExists,
    _deadline_gate_state,
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
        self.risk_flags: list[dict[str, Any]] = []
        self.reminders: list[dict[str, Any]] = []
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
        txn = {"id": txn_id, "status": "open", "stage": "new", "created_at": _now()}
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

    def list_active_transaction_ids(self) -> list[str]:
        return [
            t["id"] for t in self.transactions.values() if t.get("status", "open") == "open"
        ]

    def transaction_exists(self, transaction_id: str) -> bool:
        return transaction_id in self.transactions

    def _set_transaction_status(self, transaction_id, status, actor, action, details=None):
        txn = self.transactions.get(transaction_id)
        if txn is None:
            return None
        txn["status"] = status
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action=action,
            entity_type="transaction",
            entity_id=transaction_id,
            details={"status": status, **(details or {})},
        )
        return txn

    def cancel_transaction(self, *, transaction_id, reason, actor):
        return self._set_transaction_status(
            transaction_id, "canceled", actor, "transaction.canceled", {"reason": reason}
        )

    def reactivate_transaction(self, *, transaction_id, actor):
        return self._set_transaction_status(
            transaction_id, "open", actor, "transaction.reactivated"
        )

    def set_transaction_stage(
        self, *, transaction_id: str, stage: str, actor: str
    ) -> dict[str, Any] | None:
        txn = self.transactions.get(transaction_id)
        if txn is None:
            return None
        txn["stage"] = stage
        self._audit(
            transaction_id=transaction_id, actor=actor, action="transaction.staged",
            entity_type="transaction", entity_id=transaction_id, details={"stage": stage},
        )
        return txn

    def resolve_risk_flag(
        self, *, transaction_id: str, flag_id: str, resolved: bool, actor: str
    ) -> dict[str, Any] | None:
        f = next(
            (r for r in self.risk_flags if r["id"] == flag_id and r["transaction_id"] == transaction_id),
            None,
        )
        if f is None:
            return None
        f["resolved"] = resolved
        self._audit(
            transaction_id=transaction_id, actor=actor,
            action="risk_flag.resolved" if resolved else "risk_flag.reopened",
            entity_type="risk_flag", entity_id=flag_id, details={"resolved": resolved},
        )
        return f

    def list_deal_summaries(self) -> list[dict[str, Any]]:
        from app.master.repo import _deal_summary, _effective_fields

        txns = [t for t in self.transactions.values() if t.get("status") != "archived"]
        ids = {t["id"] for t in txns}
        props = {tid: (self.properties.get(tid) or {}).get("address") for tid in ids}
        coe = {
            d["transaction_id"]: d["due_date"]
            for d in self.deadlines
            if d["transaction_id"] in ids and d.get("compute_key") == "coe"
        }
        tasks: dict[str, list[int]] = {}
        for t in self.tasks:
            if t["transaction_id"] not in ids:
                continue
            agg = tasks.setdefault(t["transaction_id"], [0, 0])
            agg[0] += 1
            if t["status"] in ("done", "complete"):
                agg[1] += 1
        risks: dict[str, int] = {}
        for r in self.risk_flags:
            if r["transaction_id"] in ids and not r.get("resolved"):
                risks[r["transaction_id"]] = risks.get(r["transaction_id"], 0) + 1
        raw_fields: dict[str, list[dict[str, Any]]] = {}
        for f in self.extracted_fields:
            if f["transaction_id"] in ids and f["name"] in ("purchase_price", "all_cash"):
                raw_fields.setdefault(f["transaction_id"], []).append(f)
        fields: dict[str, dict[str, str]] = {
            tid: {n: v["value"] for n, v in _effective_fields(rows).items()}
            for tid, rows in raw_fields.items()
        }
        return [_deal_summary(t, props, coe, tasks, risks, fields) for t in txns]

    def list_active_deadlines(self) -> list[dict[str, Any]]:
        ids = {t["id"] for t in self.transactions.values() if t.get("status") != "archived"}
        return [
            {
                "transaction_id": d["transaction_id"],
                "property_address": (self.properties.get(d["transaction_id"]) or {}).get("address"),
                "name": d["name"],
                "due_date": d["due_date"],
                "key": d.get("compute_key"),
            }
            for d in self.deadlines
            if d["transaction_id"] in ids
        ]

    def list_open_tasks(self) -> list[dict[str, Any]]:
        ids = {t["id"] for t in self.transactions.values() if t.get("status") != "archived"}
        due = {d["id"]: d["due_date"] for d in self.deadlines if d["transaction_id"] in ids}
        return [
            {
                "id": t["id"],
                "transaction_id": t["transaction_id"],
                "property_address": (self.properties.get(t["transaction_id"]) or {}).get("address"),
                "title": t["title"],
                "status": t["status"],
                "due_date": due.get(t.get("deadline_id")),
                "assigned_party_id": t.get("assigned_party_id"),
            }
            for t in self.tasks
            if t["transaction_id"] in ids and t["status"] not in ("done", "complete")
        ]

    def archive_transaction(self, *, transaction_id: str, actor: str) -> dict[str, Any] | None:
        return self._set_transaction_status(
            transaction_id, "archived", actor, "transaction.archived"
        )

    def unarchive_transaction(self, *, transaction_id: str, actor: str) -> dict[str, Any] | None:
        return self._set_transaction_status(transaction_id, "open", actor, "transaction.unarchived")

    def delete_transaction(self, *, transaction_id: str, actor: str) -> bool:
        if transaction_id not in self.transactions:
            return False
        del self.transactions[transaction_id]
        self.properties.pop(transaction_id, None)
        for d in (self.parties, self.documents, self.payloads, self.messages):
            for key in [k for k, v in d.items() if v["transaction_id"] == transaction_id]:
                del d[key]
        for name in ("extracted_fields", "deadlines", "tasks", "approvals", "risk_flags",
                     "reminders", "audit_log"):
            setattr(
                self, name,
                [r for r in getattr(self, name) if r["transaction_id"] != transaction_id],
            )
        return True

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

    def add_manual_field(
        self, *, transaction_id: str, name: str, value: str, actor: str
    ) -> dict[str, Any]:
        payload = next(
            (p for p in self.payloads.values() if p["transaction_id"] == transaction_id), None
        )
        if payload is None:
            raise NoPayloadForManualField
        field = {
            "id": str(uuid.uuid4()),
            "payload_id": payload["id"],
            "transaction_id": transaction_id,
            "name": name,
            "value": value,
            "confidence": 1.0,
            "confirmed": True,
            "deadline_driving": name in DEADLINE_DRIVING,
        }
        self.extracted_fields.append(field)
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="field.added_manually",
            entity_type="extracted_field",
            entity_id=field["id"],
            details={"name": name, "deadline_driving": name in DEADLINE_DRIVING},
        )
        return field

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
        lender = self.lender_party(transaction_id)
        message = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "subject": _STUB_DRAFT_SUBJECT,
            "body": _STUB_DRAFT_BODY,
            "party_id": lender["id"] if lender else None,
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

    def create_party(
        self, *, transaction_id, name, role, email, permission_tier, actor, phone=None, company=None
    ) -> dict[str, Any]:
        party = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "name": name,
            "role": role,
            "email": email,
            "phone": phone,
            "company": company,
            "permission_tier": permission_tier,
        }
        self.parties[party["id"]] = party
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
        party = self.parties.get(party_id)
        if party is None or party["transaction_id"] != transaction_id:
            return None
        party.update(fields)
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="party.updated",
            entity_type="party",
            entity_id=party_id,
            details={"fields": sorted(fields.keys())},
        )
        return party

    def derive_parties_from_fields(self, *, transaction_id: str, actor: str) -> int:
        # Contacts are informational — populate from ALL extracted fields.
        fields = {
            f["name"]: f["value"]
            for f in self.extracted_fields
            if f["transaction_id"] == transaction_id
        }
        desired = derive_parties(fields)
        by_key = {
            party_key(p["role"], p["name"]): p
            for p in self.parties.values()
            if p["transaction_id"] == transaction_id
        }
        created = 0
        for d in desired:
            match = by_key.get(party_key(d.role, d.name))
            if match is not None:
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
        confirmed = {
            f["name"]: f["value"]
            for f in self.extracted_fields
            if f["transaction_id"] == transaction_id and f["confirmed"]
        }
        desired = derive_tasks(confirmed)
        if not desired:
            return 0
        existing_keys = {
            t.get("compute_key")
            for t in self.tasks
            if t["transaction_id"] == transaction_id
        }
        role_to_party: dict[str, str] = {}
        for p in self.parties.values():
            if p["transaction_id"] == transaction_id:
                role_to_party.setdefault(p["role"], p["id"])
        created = 0
        for d in desired:
            if d.key in existing_keys:
                continue
            task = {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "title": d.title,
                "status": "pending",
                "assigned_party_id": role_to_party.get(d.assign_role),
                "generated_by": "rule",
                "compute_key": d.key,
            }
            self.tasks.append(task)
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
        return next(
            (
                p
                for p in self.parties.values()
                if p["transaction_id"] == transaction_id
                and p.get("role") in ("lender", "loan_officer")
            ),
            None,
        )

    def assign_task(
        self, *, transaction_id: str, task_id: str, party_id: str, actor: str
    ) -> dict[str, Any] | None:
        task = next(
            (
                t
                for t in self.tasks
                if t["id"] == task_id and t["transaction_id"] == transaction_id
            ),
            None,
        )
        if task is None:
            return None
        task["assigned_party_id"] = party_id
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="task.assigned",
            entity_type="task",
            entity_id=task_id,
            details={"party_id": party_id},
        )
        return task

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
        task = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "title": title,
            "status": "pending",
            "deadline_id": deadline_id,
            "assigned_party_id": assigned_party_id,
            "generated_by": "tc",
        }
        self.tasks.append(task)
        details: dict[str, Any] = {"source": "tc"}
        if description:
            details["description"] = description
        if due_date:
            details["due_date"] = due_date
        if priority and priority != "normal":
            details["priority"] = priority
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="task.created",
            entity_type="task",
            entity_id=task["id"],
            details=details,
        )
        return {**task, "description": description, "due_date": due_date, "priority": priority}

    def set_task_status(
        self, *, transaction_id: str, task_id: str, status: str, actor: str
    ) -> dict[str, Any] | None:
        task = next(
            (t for t in self.tasks if t["id"] == task_id and t["transaction_id"] == transaction_id),
            None,
        )
        if task is None:
            return None
        task["status"] = status
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="task.status_changed",
            entity_type="task",
            entity_id=task_id,
            details={"status": status},
        )
        return task

    def loan_deadline_iso(self, transaction_id: str) -> str | None:
        return next(
            (
                d["due_date"]
                for d in self.deadlines
                if d["transaction_id"] == transaction_id
                and d.get("compute_key") == "loan_contingency"
            ),
            None,
        )

    def create_message(
        self,
        *,
        transaction_id,
        subject,
        body,
        party_id,
        actor,
        action="message.drafted",
        details=None,
    ) -> dict[str, Any]:
        message = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "subject": subject,
            "body": body,
            "party_id": party_id,
            "status": "draft",
            "created_at": _now(),
            "sent_at": None,
        }
        self.messages[message["id"]] = message
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action=action,
            entity_type="message",
            entity_id=message["id"],
            details=details or {},
        )
        return message

    def delete_message(self, *, transaction_id, message_id, actor) -> str | None:
        m = self.messages.get(message_id)
        if m is None or m["transaction_id"] != transaction_id:
            return None
        if m["status"] == "sent":
            return "sent"
        del self.messages[message_id]
        self._audit(
            transaction_id=transaction_id, actor=actor, action="message.discarded",
            entity_type="message", entity_id=message_id, details={"status": m["status"]},
        )
        return "deleted"

    def delete_reminder(self, *, transaction_id, reminder_id, actor) -> bool:
        before = len(self.reminders)
        self.reminders = [
            r for r in self.reminders
            if not (r["id"] == reminder_id and r["transaction_id"] == transaction_id)
        ]
        if len(self.reminders) == before:
            return False
        self._audit(
            transaction_id=transaction_id, actor=actor, action="reminder.dismissed",
            entity_type="reminder", entity_id=reminder_id, details={},
        )
        return True

    def document_signed_url(self, *, transaction_id, document_id) -> str | None:
        d = self.documents.get(document_id)
        if d is None or d.get("transaction_id") != transaction_id or not d.get("storage_path"):
            return None
        return f"https://signed.example/{d['storage_path']}"

    def add_party_document(
        self, *, transaction_id, party_id, filename, content_base64, doc_type, actor
    ) -> dict[str, Any]:
        import base64
        import binascii

        try:
            base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("document content is not valid base64") from exc
        doc = {
            "id": str(uuid.uuid4()),
            "transaction_id": transaction_id,
            "external_ref": f"party:{party_id}",
            "doc_type": doc_type,
            "storage_path": f"fake/{party_id}/{filename}",
            "status": "uploaded",
            "created_at": _now(),
        }
        self.documents[doc["id"]] = doc
        self._audit(
            transaction_id=transaction_id, actor=actor, action="document.party_uploaded",
            entity_type="document", entity_id=doc["id"],
            details={"party_id": party_id, "doc_type": doc_type, "filename": filename},
        )
        return doc

    def send_invite(
        self, *, transaction_id, party_id, to, subject, body, mailer, actor
    ) -> None:
        mailer.send(to=to, subject=subject, body=body)
        self._audit(
            transaction_id=transaction_id, actor=actor, action="party.invite_sent",
            entity_type="party", entity_id=party_id, details={},
        )

    def approve_and_send(
        self, *, transaction_id, message_id, actor, subject, body, mailer, followup_days
    ) -> dict[str, Any] | None:
        message = self.messages.get(message_id)
        if message is None or message["transaction_id"] != transaction_id:
            return None
        if message["status"] not in ("draft", "approved"):
            raise MessageNotSendable
        recipient = self._recipient_email(message.get("party_id"))
        if not recipient:
            raise NoRecipient
        final_subject = subject if subject is not None else message["subject"]
        final_body = body if body is not None else message["body"]

        approval = next((a for a in self.approvals if a["message_id"] == message_id), None)
        if message["status"] == "draft":
            approval = {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "message_id": message_id,
                "approved_by": actor,
                "approved_at": _now(),
            }
            self.approvals.append(approval)
            message.update(
                {
                    "status": "approved",
                    "subject": final_subject,
                    "body": final_body,
                    "approved_by": actor,
                    "approved_at": _now(),
                }
            )
            self._audit(
                transaction_id=transaction_id,
                actor=actor,
                action="message.approved",
                entity_type="message",
                entity_id=message_id,
                details={"approval_id": approval["id"]},
            )
        else:  # retry: no new approval
            message.update({"subject": final_subject, "body": final_body})
        # The send — a guarded/failed send leaves the message 'approved'.
        sent_result = mailer.send(to=recipient, subject=final_subject, body=final_body)
        message["status"] = "sent"
        message["sent_at"] = _now()
        message["provider_message_id"] = sent_result.provider_message_id
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="message.sent",
            entity_type="message",
            entity_id=message_id,
            details={"provider_message_id": sent_result.provider_message_id},
        )
        self.reminders.append(
            {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "message_id": message_id,
                "remind_at": _now(),
                "note": "No reply from lender — consider following up.",
            }
        )
        return {"message": message, "approval": approval}

    def _recipient_email(self, party_id: str | None) -> str | None:
        if not party_id:
            return None
        party = self.parties.get(party_id)
        return party.get("email") if party else None

    def party_belongs_to_transaction(self, *, party_id: str, transaction_id: str) -> bool:
        party = self.parties.get(party_id)
        return party is not None and party["transaction_id"] == transaction_id

    def get_party(self, *, party_id: str, transaction_id: str) -> dict[str, Any] | None:
        party = self.parties.get(party_id)
        if party is None or party["transaction_id"] != transaction_id:
            return None
        return party

    def record_access_token_issued(
        self, *, transaction_id: str, party_id: str, actor: str
    ) -> None:
        self._audit(
            transaction_id=transaction_id,
            actor=actor,
            action="party.access_token_issued",
            entity_type="party",
            entity_id=party_id,
        )

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
        # Cross-document inconsistency: flag material conflicts vs confirmed fields.
        if payload.document_type == "purchase_agreement" and payload.extracted_fields:
            from app.master.inconsistency import (
                CRITICAL_FIELDS,
                MATERIAL_FIELDS,
                find_field_conflicts,
            )

            existing_confirmed = {
                f["name"]: f["value"]
                for f in self.extracted_fields
                if f["transaction_id"] == transaction_id
                and f.get("confirmed")
                and f["name"] in MATERIAL_FIELDS
            }
            incoming = {f.name: f.value for f in payload.extracted_fields}
            for name, old, new in find_field_conflicts(existing_confirmed, incoming):
                self.risk_flags.append(
                    {
                        "id": str(uuid.uuid4()),
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
                )
                self._audit(
                    transaction_id=transaction_id, actor=actor, action="risk_flag.inconsistency",
                    entity_type="risk_flag", entity_id=None, details={"field": name, "old": old, "new": new},
                )

        # A counter offer's chain/expiration facts → risk flags.
        if payload.document_type in COUNTER_OFFER_TYPES and payload.counter_meta:
            from app.master.repo import evaluate_counter_flags

            for flag in evaluate_counter_flags(payload.document_type, payload.counter_meta):
                self.risk_flags.append(
                    {
                        "id": str(uuid.uuid4()),
                        "transaction_id": transaction_id,
                        "severity": flag["severity"],
                        "description": flag["description"],
                        "generated_by": "master",
                        "case_key": flag["case_key"],
                        "resolved": False,
                    }
                )
                self._audit(
                    transaction_id=transaction_id, actor=actor, action="risk_flag.counter",
                    entity_type="risk_flag", entity_id=None, details={"case": flag["case_key"]},
                )

        # A preapproval is validated against the deal (borrower, amount, expiry).
        if payload.document_type == "preapproval" and payload.preapproval_meta:
            from app.master.repo import _effective_fields, evaluate_preapproval_flags

            eff = _effective_fields(
                [f for f in self.extracted_fields if f["transaction_id"] == transaction_id]
            )
            coe = next(
                (d["due_date"] for d in self.deadlines
                 if d["transaction_id"] == transaction_id and "escrow" in d["name"].lower()),
                None,
            )
            for flag in evaluate_preapproval_flags(
                payload.preapproval_meta,
                (eff.get("buyer_names") or {}).get("value"),
                (eff.get("loan_amount") or {}).get("value"),
                date.fromisoformat(coe) if coe else None,
            ):
                self.risk_flags.append(
                    {
                        "id": str(uuid.uuid4()),
                        "transaction_id": transaction_id,
                        "severity": flag["severity"],
                        "description": flag["description"],
                        "generated_by": "master",
                        "case_key": flag["case_key"],
                        "resolved": False,
                    }
                )
                self._audit(
                    transaction_id=transaction_id, actor=actor, action="risk_flag.preapproval",
                    entity_type="risk_flag", entity_id=None, details={"case": flag["case_key"]},
                )

        # A re-uploaded PA supersedes the prior one (cascade its payload+fields).
        if payload.document_type == "purchase_agreement":
            old_docs = [
                d["id"]
                for d in self.documents.values()
                if d["transaction_id"] == transaction_id
                and d["doc_type"] == "purchase_agreement"
                and d["id"] != doc["id"]
            ]
            old_payloads = {
                p["id"] for p in self.payloads.values() if p["document_id"] in old_docs
            }
            for did in old_docs:
                del self.documents[did]
            for pid in old_payloads:
                del self.payloads[pid]
            self.extracted_fields = [
                f for f in self.extracted_fields if f["payload_id"] not in old_payloads
            ]
        # A document reopens an archived deal.
        txn = self.transactions.get(transaction_id)
        if txn is not None and txn.get("status") == "archived":
            txn["status"] = "open"
        return row

    def apply_compliance_result(self, *, result, actor: str) -> dict[str, Any]:
        transaction_id = result.transaction_id
        rows = [
            {"name": f["name"], "confirmed": f["confirmed"]}
            for f in self.extracted_fields
            if f["transaction_id"] == transaction_id
        ]
        violations = _deadline_gate_violations(rows)
        if violations:
            raise DeadlineFieldsUnconfirmed(violations)

        # Carry over mutable task state (e.g. a party marked it done) by key.
        prior_task_state = {
            t["compute_key"]: t
            for t in self.tasks
            if t["transaction_id"] == transaction_id
            and t.get("generated_by") == "compliance"
            and t.get("compute_key")
        }

        run_id = str(uuid.uuid4())
        deadline_id_by_key: dict[str, str] = {}
        for d in result.deadlines:
            row = {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "name": d.name,
                "due_date": d.due_date.isoformat(),
                "generated_by": "compliance",
                "compliance_run_id": run_id,
                "compute_key": d.key,
            }
            self.deadlines.append(row)
            deadline_id_by_key[d.key] = row["id"]

        task_id_by_key: dict[str, str] = {}
        for t in result.tasks:
            carried = prior_task_state.get(t.key, {})
            row = {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "title": t.title,
                "status": carried.get("status", "pending"),
                "assigned_party_id": carried.get("assigned_party_id"),
                "deadline_id": deadline_id_by_key.get(t.deadline_key or ""),
                "depends_on_task_id": None,
                "generated_by": "compliance",
                "compliance_run_id": run_id,
                "compute_key": t.key,
            }
            self.tasks.append(row)
            task_id_by_key[t.key] = row["id"]
        for t in result.tasks:
            if t.depends_on_key and t.depends_on_key in task_id_by_key:
                target = next(x for x in self.tasks if x["id"] == task_id_by_key[t.key])
                target["depends_on_task_id"] = task_id_by_key[t.depends_on_key]

        for f in result.risk_flags:
            self.risk_flags.append(
                {
                    "id": str(uuid.uuid4()),
                    "transaction_id": transaction_id,
                    "severity": f.severity,
                    "description": f.description,
                    "deadline_id": deadline_id_by_key.get(f.deadline_key or ""),
                    "generated_by": "compliance",
                    "compliance_run_id": run_id,
                    "case_key": f.case,
                    "resolved": False,
                }
            )

        role_to_party: dict[str, str] = {}
        for p in self.parties.values():
            if p["transaction_id"] == transaction_id:
                role_to_party.setdefault(p["role"], p["id"])
        for r in result.draft_reminders:
            msg = {
                "id": str(uuid.uuid4()),
                "transaction_id": transaction_id,
                "subject": r.subject,
                "body": r.body,
                "status": "draft",
                "party_id": role_to_party.get(r.to_role) if r.to_role else None,
                "generated_by": "compliance",
                "compliance_run_id": run_id,
                "created_at": _now(),
                "sent_at": None,
            }
            self.messages[msg["id"]] = msg

        # New run landed — remove the prior run's rows. Messages only if still
        # 'draft' (approved/sent compliance messages stay — append-only record).
        def _prior(row) -> bool:
            return (
                row["transaction_id"] == transaction_id
                and row.get("generated_by") == "compliance"
                and row.get("compliance_run_id") != run_id
            )

        self.deadlines = [d for d in self.deadlines if not _prior(d)]
        self.tasks = [t for t in self.tasks if not _prior(t)]
        self.risk_flags = [r for r in self.risk_flags if not _prior(r)]
        for mid in [
            m["id"] for m in self.messages.values() if _prior(m) and m.get("status") == "draft"
        ]:
            del self.messages[mid]

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
        txn = self.transactions.get(transaction_id)
        if txn is None:
            return None
        from app.master.repo import _effective_fields

        fields = [f for f in self.extracted_fields if f["transaction_id"] == transaction_id]
        return {
            "transaction": txn,
            "property": self.properties.get(transaction_id),
            "timeline_gate": _deadline_gate_state(fields),
            "effective_fields": _effective_fields(fields),
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
            "reminders": [r for r in self.reminders if r["transaction_id"] == transaction_id],
            "risk_flags": [r for r in self.risk_flags if r["transaction_id"] == transaction_id],
            "approvals": [a for a in self.approvals if a["transaction_id"] == transaction_id],
            "audit_log": [a for a in self.audit_log if a["transaction_id"] == transaction_id],
        }
