"""Shared document-type taxonomy — part of the ingestion<->master contract.

One canonical set so detection, confirm overrides, the Payload, and the SOR's
documents.doc_type column can't drift apart. 'unknown' means the TC must be
ASKED — it is never written to the SOR (the confirm endpoint rejects it)."""

from __future__ import annotations

from typing import Literal

DocType = Literal[
    "purchase_agreement",
    "counter_offer",
    "seller_counter_offer",
    "buyer_counter_offer",
    "contingency_removal",
    "preapproval",
    "preliminary_report",
    "proof_of_funds",
    "disclosure",
    "inspection_report",
    "other",
    "unknown",
]

UNKNOWN_DOC_TYPE: DocType = "unknown"
# The TC can ask Terra to classify a document itself: picking this sends it
# through the model's content-level detection at confirm time.
OTHER_DOC_TYPE: DocType = "other"

# Counter offers supersede the purchase agreement's terms (price, dates). The
# generic "counter_offer" is kept for back-compat / when the side is unknown.
COUNTER_OFFER_TYPES: frozenset[str] = frozenset(
    {"counter_offer", "seller_counter_offer", "buyer_counter_offer"}
)
