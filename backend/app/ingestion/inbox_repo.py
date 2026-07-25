"""Ingestion's own queue + attachment storage (part a). Owns the
ingestion_inbox table and the private ingestion-attachments bucket ONLY —
never the master's tables (rules/architecture.md). Rows store the storage
path, never document content. Synthetic files only until ZDR clears (§3)."""

from __future__ import annotations

import base64
import binascii
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from app.common.db import ThreadLocalSupabase

BUCKET = "ingestion-attachments"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(filename: str) -> str:
    return _SAFE_NAME.sub("_", filename)[-100:] or "attachment.pdf"


class StorageUnavailable(Exception):
    """The attachment store rejected or failed the upload (outage, quota…).
    Message must stay generic — never echo document content."""


class InboxRepo(Protocol):
    def store_attachment(self, *, source: str, filename: str, content_base64: str) -> str:
        """Persist the file; returns the storage path. Raises ValueError on
        undecodable base64 content and StorageUnavailable on upload failure."""
        ...

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
    ) -> dict[str, Any]: ...

    def download_attachment(self, path: str) -> bytes:
        """Fetch stored attachment bytes for extraction (part a internal only —
        content never crosses to the master or the frontend). Raises
        StorageUnavailable on failure."""
        ...

    def list_open(self) -> list[dict[str, Any]]:
        """Pending + needs_manual items — the queue the TC works through."""
        ...

    def get(self, item_id: str) -> dict[str, Any] | None: ...

    def sender_history(self) -> dict[str, str]:
        """from_email (lowercased) -> most recently confirmed transaction id."""
        ...

    def claim(self, item_id: str) -> dict[str, Any] | None:
        """Reserve a pending item (pending -> processing) BEFORE any master
        write, so a concurrent confirm can't duplicate side effects. None if
        the item was not pending (another request won)."""
        ...

    def release(self, item_id: str) -> dict[str, Any] | None:
        """Return a claimed item to pending (processing -> pending) after a
        failed confirm, so the TC can retry."""
        ...

    def mark_confirmed(self, item_id: str, transaction_id: str) -> dict[str, Any] | None:
        """Finalize a claimed item (processing -> confirmed)."""
        ...

    def mark_ignored(self, item_id: str) -> dict[str, Any] | None:
        """Conditionally close out a pending/needs_manual item."""
        ...


class SupabaseInboxRepo:
    def __init__(self) -> None:
        # Thread-local client (see app/common/db) — this repo is a singleton used
        # from FastAPI's threadpool and the Supabase client isn't thread-safe.
        self._pool = ThreadLocalSupabase(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )

    @property
    def _db(self):
        return self._pool.client

    def store_attachment(self, *, source: str, filename: str, content_base64: str) -> str:
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("attachment content is not valid base64") from exc
        path = f"{source}/{uuid.uuid4()}/{safe_filename(filename)}"
        try:
            self._db.storage.from_(BUCKET).upload(
                path, content, {"content-type": "application/pdf"}
            )
        except Exception as exc:
            # Generic on purpose: no document content in the message (Rule 5).
            raise StorageUnavailable(f"attachment store failed ({type(exc).__name__})") from exc
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
                    "detected_doc_type": detected_doc_type,
                    "storage_path": storage_path,
                    "source": source,
                    "status": status,
                    "needs_manual_reason": needs_manual_reason,
                }
            )
            .execute()
            .data[0]
        )

    def download_attachment(self, path: str) -> bytes:
        try:
            return self._db.storage.from_(BUCKET).download(path)
        except Exception as exc:
            raise StorageUnavailable(f"attachment store failed ({type(exc).__name__})") from exc

    def list_open(self) -> list[dict[str, Any]]:
        return (
            self._db.table("ingestion_inbox")
            .select("*")
            .in_("status", ["pending", "needs_manual"])
            .order("created_at")
            .execute()
            .data
        )

    def get(self, item_id: str) -> dict[str, Any] | None:
        rows = self._db.table("ingestion_inbox").select("*").eq("id", item_id).execute().data
        return rows[0] if rows else None

    def sender_history(self) -> dict[str, str]:
        rows = (
            self._db.table("ingestion_inbox")
            .select("from_email, confirmed_transaction_id, confirmed_at")
            .eq("status", "confirmed")
            .not_.is_("confirmed_transaction_id", "null")
            .order("confirmed_at")
            .execute()
            .data
        )
        # Later confirmations overwrite earlier ones -> most recent wins.
        return {r["from_email"].lower(): r["confirmed_transaction_id"] for r in rows}

    def _transition(self, item_id: str, from_status: str, updates: dict[str, Any]):
        rows = (
            self._db.table("ingestion_inbox")
            .update(updates)
            .eq("id", item_id)
            .eq("status", from_status)  # compare-and-swap: loses gracefully
            .execute()
            .data
        )
        return rows[0] if rows else None

    def claim(self, item_id: str) -> dict[str, Any] | None:
        return self._transition(item_id, "pending", {"status": "processing"})

    def release(self, item_id: str) -> dict[str, Any] | None:
        return self._transition(item_id, "processing", {"status": "pending"})

    def mark_confirmed(self, item_id: str, transaction_id: str) -> dict[str, Any] | None:
        return self._transition(
            item_id,
            "processing",
            {
                "status": "confirmed",
                "confirmed_transaction_id": transaction_id,
                "confirmed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def mark_ignored(self, item_id: str) -> dict[str, Any] | None:
        rows = (
            self._db.table("ingestion_inbox")
            .update({"status": "ignored"})
            .eq("id", item_id)
            .in_("status", ["pending", "needs_manual"])
            .execute()
            .data
        )
        return rows[0] if rows else None
