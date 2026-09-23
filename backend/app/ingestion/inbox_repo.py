"""Ingestion's own queue + attachment storage (part a). Owns the
ingestion_inbox table and the private ingestion-attachments bucket ONLY —
never the master's tables (rules/architecture.md). Rows store the storage
path, never document content. Synthetic files only until ZDR clears (§3)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.common.db import ThreadLocalSupabase

BUCKET = "ingestion-attachments"

# An inbox item claimed (pending -> processing) longer ago than this is treated as
# abandoned by a crashed confirm and reclaimed back to 'pending' (BUG-17).
_INBOX_CLAIM_STALE_SECONDS = 300

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(filename: str) -> str:
    return _SAFE_NAME.sub("_", filename)[-100:] or "attachment.pdf"


def content_addressed_path(source: str, filename: str, content: bytes) -> str:
    """A deterministic, content-addressed storage path: identical bytes always map
    to the SAME path. This is what makes duplicate-delivery detection exact — a
    Postmark redelivery re-derives this path, while a genuinely different document
    (even same filename/size) hashes elsewhere and is NEVER mistaken for it."""
    digest = hashlib.sha256(content).hexdigest()
    return f"{source}/{digest}/{safe_filename(filename)}"


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
        org_id: str,
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

    def find_duplicate_by_storage_path(
        self, *, org_id: str, storage_path: str, attachment_count: int
    ) -> dict[str, Any] | None:
        """An existing inbox item IN THIS ORG for the EXACT same stored bytes
        (content-addressed storage_path) — used to absorb Postmark at-least-once
        redelivery without creating a duplicate queue item. Matches by exact
        content, so a genuinely different document is never mistaken for a
        duplicate (no silent data loss). Org-scoped: two orgs receiving the same
        bytes each get their own queue item. None if none."""
        ...

    def find_items_by_digest(self, digest: str, *, org_id: str) -> list[dict[str, Any]]:
        """This org's inbox items whose stored bytes hash to this sha256 digest —
        regardless of source, filename, or status. Storage paths are
        content-addressed ({source}/{digest}/{filename}), so this is an EXACT
        same-bytes match: a renamed copy is found, a revised document never is.
        Used to tell the TC 'you already have this exact file'."""
        ...

    def download_attachment(self, path: str) -> bytes:
        """Fetch stored attachment bytes for extraction (part a internal only —
        content never crosses to the master or the frontend). Raises
        StorageUnavailable on failure."""
        ...

    def list_open(self, *, org_id: str) -> list[dict[str, Any]]:
        """The org's pending + needs_manual items — the queue the TC works through."""
        ...

    def get(self, item_id: str) -> dict[str, Any] | None: ...

    def sender_history(self, *, org_id: str) -> dict[str, str]:
        """from_email (lowercased) -> most recently confirmed transaction id,
        within one org (suggestions must never leak another org's deals)."""
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

    def set_detected_doc_type(
        self, item_id: str, doc_type: str, doc_guess: str | None = None
    ) -> dict[str, Any] | None:
        """Persist a (re)classified type on a still-pending item — used by the
        content-level classify endpoint so a batch upload's labels survive a
        refresh. doc_guess is the model's free-text best guess when the type is
        outside the known set. CAS on status=pending: never relabels an item
        mid-confirm."""
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
        path = content_addressed_path(source, filename, content)
        try:
            # upsert: a duplicate delivery re-derives the same path; overwriting
            # identical bytes is harmless and avoids a conflict error → retry loop.
            self._db.storage.from_(BUCKET).upload(
                path, content, {"content-type": "application/pdf", "upsert": "true"}
            )
        except Exception as exc:
            # Generic on purpose: no document content in the message (Rule 5).
            raise StorageUnavailable(f"attachment store failed ({type(exc).__name__})") from exc
        return path

    def add_item(
        self,
        *,
        org_id: str,
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
                    "org_id": org_id,
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

    def find_duplicate_by_storage_path(
        self, *, org_id: str, storage_path: str, attachment_count: int
    ) -> dict[str, Any] | None:
        rows = (
            self._db.table("ingestion_inbox")
            .select("id, status")
            .eq("org_id", org_id)
            .eq("storage_path", storage_path)
            .eq("attachment_count", attachment_count)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def find_items_by_digest(self, digest: str, *, org_id: str) -> list[dict[str, Any]]:
        return (
            self._db.table("ingestion_inbox")
            .select("*")
            .eq("org_id", org_id)
            .like("storage_path", f"%/{digest}/%")
            .order("created_at", desc=True)
            .execute()
            .data
        )

    def download_attachment(self, path: str) -> bytes:
        try:
            return self._db.storage.from_(BUCKET).download(path)
        except Exception as exc:
            raise StorageUnavailable(f"attachment store failed ({type(exc).__name__})") from exc

    def list_open(self, *, org_id: str) -> list[dict[str, Any]]:
        self._reclaim_stale_processing()
        return (
            self._db.table("ingestion_inbox")
            .select("*")
            .eq("org_id", org_id)
            .in_("status", ["pending", "needs_manual"])
            .order("created_at")
            .execute()
            .data
        )

    def _reclaim_stale_processing(self) -> None:
        """Return items stranded in 'processing' by a crashed confirm (claimed longer
        ago than the stale window) back to 'pending' so they resurface (BUG-17).
        Self-healing, like the compliance lock — no separate reaper job needed."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=_INBOX_CLAIM_STALE_SECONDS)
        ).isoformat()
        self._db.table("ingestion_inbox").update({"status": "pending", "claimed_at": None}).eq(
            "status", "processing"
        ).lt("claimed_at", cutoff).execute()

    def get(self, item_id: str) -> dict[str, Any] | None:
        rows = self._db.table("ingestion_inbox").select("*").eq("id", item_id).execute().data
        return rows[0] if rows else None

    def sender_history(self, *, org_id: str) -> dict[str, str]:
        rows = (
            self._db.table("ingestion_inbox")
            .select("from_email, confirmed_transaction_id, confirmed_at")
            .eq("org_id", org_id)
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
        return self._transition(
            item_id,
            "pending",
            {"status": "processing", "claimed_at": datetime.now(timezone.utc).isoformat()},
        )

    def release(self, item_id: str) -> dict[str, Any] | None:
        return self._transition(item_id, "processing", {"status": "pending", "claimed_at": None})

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

    def set_detected_doc_type(
        self, item_id: str, doc_type: str, doc_guess: str | None = None
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {"detected_doc_type": doc_type}
        if doc_guess is not None:
            updates["doc_guess"] = doc_guess
        try:
            return self._transition(item_id, "pending", updates)
        except Exception:
            if "doc_guess" not in updates:
                raise
            # Graceful pre-migration: persist the label even before the
            # doc_guess column exists (the guess is advisory).
            return self._transition(item_id, "pending", {"detected_doc_type": doc_type})

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
