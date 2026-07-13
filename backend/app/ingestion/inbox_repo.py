"""Ingestion's own queue storage (part a). Owns the ingestion_inbox table ONLY —
never the master's tables (rules/architecture.md). Attachment metadata only in
Phase 2; no document content is stored anywhere."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Protocol


class InboxRepo(Protocol):
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
    ) -> dict[str, Any]: ...

    def list_pending(self) -> list[dict[str, Any]]: ...

    def get(self, item_id: str) -> dict[str, Any] | None: ...

    def mark_confirmed(self, item_id: str, transaction_id: str) -> dict[str, Any] | None:
        """Conditionally flip pending -> confirmed; None if it was no longer
        pending (another request won the race)."""
        ...


class SupabaseInboxRepo:
    def __init__(self) -> None:
        from supabase import create_client

        self._db = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )

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
        return (
            self._db.table("ingestion_inbox")
            .insert(
                {
                    "from_email": from_email,
                    "to_email": to_email,
                    "subject": subject,
                    "attachment_name": attachment_name,
                    "attachment_content_type": attachment_content_type,
                    "attachment_size": attachment_size,
                    "attachment_count": attachment_count,
                }
            )
            .execute()
            .data[0]
        )

    def list_pending(self) -> list[dict[str, Any]]:
        return (
            self._db.table("ingestion_inbox")
            .select("*")
            .eq("status", "pending")
            .order("created_at")
            .execute()
            .data
        )

    def get(self, item_id: str) -> dict[str, Any] | None:
        rows = self._db.table("ingestion_inbox").select("*").eq("id", item_id).execute().data
        return rows[0] if rows else None

    def mark_confirmed(self, item_id: str, transaction_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("ingestion_inbox")
            .update(
                {
                    "status": "confirmed",
                    "confirmed_transaction_id": transaction_id,
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", item_id)
            .eq("status", "pending")  # conditional: loses gracefully in a race
            .execute()
            .data
        )
        return rows[0] if rows else None
