"""Shared document-type taxonomy — part of the ingestion<->master contract.

One canonical set so detection, confirm overrides, the Payload, and the SOR's
documents.doc_type column can't drift apart. 'unknown' means the TC must be
ASKED — it is never written to the SOR (the confirm endpoint rejects it)."""

from __future__ import annotations

from typing import Literal

DocType = Literal[
    "purchase_agreement",
    "proof_of_funds",
    "disclosure",
    "inspection_report",
    "unknown",
]

UNKNOWN_DOC_TYPE: DocType = "unknown"
