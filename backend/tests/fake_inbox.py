"""In-memory fakes for ingestion's inbox repo and the master API client.

The fake master client applies calls straight to the shared InMemoryRepo so
flow tests can observe what ingestion committed — mirroring the real client,
which calls the master's HTTP API and never imports master internals.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.contracts.payload import Payload
from tests.fake_repo import InMemoryRepo


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryInboxRepo:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

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
            "status": "pending",
            "confirmed_transaction_id": None,
            "created_at": _now(),
            "confirmed_at": None,
        }
        self.items[item["id"]] = item
        return item

    def list_pending(self) -> list[dict[str, Any]]:
        return [i for i in self.items.values() if i["status"] == "pending"]

    def get(self, item_id: str) -> dict[str, Any] | None:
        return self.items.get(item_id)

    def mark_confirmed(self, item_id: str, transaction_id: str) -> dict[str, Any] | None:
        item = self.items[item_id]
        if item["status"] != "pending":
            return None
        item["status"] = "confirmed"
        item["confirmed_transaction_id"] = transaction_id
        item["confirmed_at"] = _now()
        return item


class FakeMasterClient:
    """Stands in for the HTTP client ingestion uses to reach the master API.

    Returns (status_code, body) tuples like the real client.
    """

    def __init__(self, repo: InMemoryRepo) -> None:
        self.repo = repo

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
        if not self.repo.transaction_exists(transaction_id):
            return 404, {"detail": "Transaction not found"}
        row = self.repo.write_payload(
            transaction_id=transaction_id, payload=payload, actor="tc@example.test"
        )
        return 201, row
