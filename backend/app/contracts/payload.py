"""The Payload contract — the sole interface between part (a) ingestion and
part (b) master (see rules/architecture.md, §10).

A Payload describes which document was ingested, which transaction it belongs to
(or that it should create a NEW one), which party it relates to, and the fields
extracted from it (each scored and independently confirmable). Transaction
creation from a NEW payload is HITL: the master commits nothing until the TC
confirms.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.contracts.documents import DocType

# Sentinel used in `Payload.transaction_id` when ingestion cannot (and must not)
# assume an existing transaction. A NEW payload requires TC confirmation before
# the master creates anything.
NEW_TRANSACTION = "new"


class ExtractedField(BaseModel):
    """One value read from a document, with a confidence score and a confirmed
    flag. Deadline-driving fields must be confirmed before the timeline builds.
    (Which fields are deadline-driving is classified by the master from the
    verified §5 list in Phase 4 — it is not part of the ingestion contract.)"""

    name: str = Field(min_length=1)
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    confirmed: bool = False


class Payload(BaseModel):
    """A validated package handed from ingestion to the master. Validated at the
    boundary — never trusted."""

    document_id: str = Field(min_length=1)
    # A real transaction id, or the NEW_TRANSACTION sentinel.
    transaction_id: str = Field(min_length=1)
    party_id: str | None = Field(default=None, min_length=1)
    extracted_fields: list[ExtractedField] = Field(default_factory=list)
    # Which document, concretely (Phase 3): detected/TC-confirmed type and the
    # ingestion-side storage reference. Optional — older payloads stay valid.
    document_type: DocType | None = None
    document_storage_ref: str | None = Field(default=None, min_length=1)

    @property
    def is_new_transaction(self) -> bool:
        """True when this payload asks the master to create a new transaction
        (subject to HITL confirmation)."""
        return self.transaction_id == NEW_TRANSACTION
