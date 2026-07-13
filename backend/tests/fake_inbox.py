"""In-memory fakes for ingestion's inbox repo (queue + attachment storage) and
the master API client.

The fake master client applies calls straight to the shared InMemoryRepo so
flow tests can observe what ingestion committed — mirroring the real client,
which calls the master's HTTP API and never imports master internals.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime, timezone
from typing import Any

from app.contracts.payload import Payload
from app.ingestion.inbox_repo import StorageUnavailable
from app.master.routes import _MONEY_FIELD_NAME
from tests.fake_repo import InMemoryRepo


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryInboxRepo:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.files: dict[str, bytes] = {}  # storage_path -> content
        self.fail_storage = False  # simulate a bucket outage

    def store_attachment(self, *, source: str, filename: str, content_base64: str) -> str:
        if self.fail_storage:
            raise StorageUnavailable("attachment store failed (SyntheticOutage)")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("attachment content is not valid base64") from exc
        path = f"{source}/{uuid.uuid4()}/{filename}"
        self.files[path] = content
        return path

    def add_item(
        self,
        *,
        from_email: str,
        to_email: str,
        subject: str | None,
        attachment_name: str | None,
        attachment_content_type: str | None,
        attachment_size: int | None,
        attachment_count: int,
        detected_doc_type: str | None,
        storage_path: str | None,
        source: str,
        status: str = "pending",
        needs_manual_reason: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": str(uuid.uuid4()),
            "from_email": from_email,
            "to_email": to_email,
            "subject": subject,
            "attachment_name": attachment_name,
            "attachment_content_type": attachment_content_type,
            "attachment_size": attachment_size,
            "attachment_count": attachment_count,
            "detected_doc_type": detected_doc_type,
            "storage_path": storage_path,
            "source": source,
            "status": status,
            "needs_manual_reason": needs_manual_reason,
            "confirmed_transaction_id": None,
            "created_at": _now(),
            "confirmed_at": None,
        }
        self.items[item["id"]] = item
        return item

    def list_open(self) -> list[dict[str, Any]]:
        return [i for i in self.items.values() if i["status"] in ("pending", "needs_manual")]

    def get(self, item_id: str) -> dict[str, Any] | None:
        return self.items.get(item_id)

    def sender_history(self) -> dict[str, str]:
        history: dict[str, str] = {}
        confirmed = [
            i
            for i in self.items.values()
            if i["status"] == "confirmed" and i["confirmed_transaction_id"]
        ]
        for item in sorted(confirmed, key=lambda i: i["confirmed_at"] or ""):
            history[item["from_email"].lower()] = item["confirmed_transaction_id"]
        return history

    def claim(self, item_id: str) -> dict[str, Any] | None:
        item = self.items[item_id]
        if item["status"] != "pending":
            return None
        item["status"] = "processing"
        return item

    def release(self, item_id: str) -> dict[str, Any] | None:
        item = self.items[item_id]
        if item["status"] != "processing":
            return None
        item["status"] = "pending"
        return item

    def mark_confirmed(self, item_id: str, transaction_id: str) -> dict[str, Any] | None:
        item = self.items[item_id]
        if item["status"] != "processing":
            return None
        item["status"] = "confirmed"
        item["confirmed_transaction_id"] = transaction_id
        item["confirmed_at"] = _now()
        return item

    def mark_ignored(self, item_id: str) -> dict[str, Any] | None:
        item = self.items[item_id]
        if item["status"] not in ("pending", "needs_manual"):
            return None
        item["status"] = "ignored"
        return item


class FakeMasterClient:
    """Stands in for the HTTP client ingestion uses to reach the master API.

    Returns (status_code, body) tuples like the real client.
    """

    def __init__(self, repo: InMemoryRepo) -> None:
        self.repo = repo

    def list_transactions(self, *, token: str) -> tuple[int, Any]:
        return 200, self.repo.list_transactions()

    def create_transaction(
        self, *, token: str, property_address: str
    ) -> tuple[int, dict[str, Any]]:
        created = self.repo.create_transaction(
            property_address=property_address, actor="tc@example.test"
        )
        return 201, created

    def write_payload(
        self, *, token: str, transaction_id: str, payload: Payload
    ) -> tuple[int, dict[str, Any]]:
        # Mirror the real route's Rule 2 denylist so flow tests exercise it too.
        money = [f.name for f in payload.extracted_fields if _MONEY_FIELD_NAME.search(f.name)]
        if money:
            return 422, {"detail": f"Rule 2: rejected field name(s): {', '.join(money)}"}
        if not self.repo.transaction_exists(transaction_id):
            return 404, {"detail": "Transaction not found"}
        row = self.repo.write_payload(
            transaction_id=transaction_id, payload=payload, actor="tc@example.test"
        )
        return 201, row
