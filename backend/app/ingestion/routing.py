"""Routing suggestions: match an inbound document to an existing transaction by
transaction ID, sender history, or property address — or return None so the TC
is ASKED (the agent suggests; it never commits — HITL, rules/security.md).

Computed at HITL time with the TC's own view of the deals (master list fetched
with the TC's forwarded token) plus ingestion's OWN confirmed-sender history —
no master tables are read from here."""

from __future__ import annotations

import re
from typing import Any

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

_WORD_RE = re.compile(r"[a-z0-9]{3,}")


def _tokens(text: str | None) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def suggest_transaction(
    *,
    subject: str | None,
    from_email: str,
    transactions: list[dict[str, Any]],
    sender_history: dict[str, str],
) -> dict[str, str] | None:
    """{"transaction_id", "reason"} or None (= ASK the TC with no preselection)."""
    known_ids = {t["id"] for t in transactions}

    # 1. Explicit transaction UUID in the subject.
    for match in _UUID_RE.findall(subject or ""):
        if match.lower() in known_ids:
            return {
                "transaction_id": match.lower(),
                "reason": "subject references this transaction id",
            }

    # 2. This sender previously confirmed a document onto a deal.
    history_txn = sender_history.get(from_email.lower())
    if history_txn and history_txn in known_ids:
        return {
            "transaction_id": history_txn,
            "reason": f"{from_email} previously sent documents for this deal",
        }

    # 3. Property-address word overlap with the subject (>= 2 words).
    subject_tokens = _tokens(subject)
    best: tuple[int, dict[str, Any]] | None = None
    for txn in transactions:
        overlap = len(_tokens(txn.get("property_address")) & subject_tokens)
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, txn)
    if best is not None:
        return {
            "transaction_id": best[1]["id"],
            "reason": "subject matches the property address",
        }

    return None
