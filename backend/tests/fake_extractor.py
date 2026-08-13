"""In-memory fake of the Extractor seam — synthetic canned fields only.

Mirrors ClaudeExtractor's result shape so confirm-flow tests run with no
network and no model. Six canned fields (matching the retired Phase 2 stub's
count) with a spread of confidences, four of them deadline-driving.
"""

from __future__ import annotations

from app.contracts.documents import DocType
from app.contracts.payload import CounterMeta, ExtractedField
from app.ingestion.extractor import (
    ContingencyRemoval,
    ExtractionBlocked,
    ExtractionFailed,
    ExtractionResult,
    InspectionReport,
    Preapproval,
    PreliminaryReport,
)

# All 10 deadline-driving fields + two informational ones: the coverage gate
# requires every DEADLINE_DRIVING name to exist AND be confirmed before the
# timeline builds, so the canned set must cover them.
CANNED_FIELDS: list[tuple[str, str, float]] = [
    ("property_address", "123 Stub St, Sacramento, CA 95814", 0.97),
    ("purchase_price", "850000", 0.98),
    ("acceptance_date", "2026-07-10", 0.62),  # low: Confirmation box is optional
    ("close_of_escrow", "30 days after acceptance", 0.88),
    ("possession_date", "at close of escrow, 6:00 PM", 0.90),
    ("emd_due_days", "3 business days", 0.85),
    ("inspection_contingency_days", "17", 0.91),
    ("loan_contingency_days", "21", 0.90),
    ("appraisal_contingency_days", "17", 0.90),
    ("insurance_contingency_days", "17", 0.89),
    ("disclosure_delivery_days", "7", 0.92),
    ("verification_of_funds_days", "3", 0.87),
]


class FakeExtractor:
    def __init__(
        self,
        *,
        doc_looks_like: str = "purchase_agreement",
        signature_detected: bool = True,
        fields: list[ExtractedField] | None = None,
        raise_blocked: bool = False,
        raise_failed: bool = False,
        subject_to_counter_offer: bool = False,
        counter_meta: CounterMeta | None = None,
        contingency_removal: ContingencyRemoval | None = None,
        preapproval: Preapproval | None = None,
        preliminary: PreliminaryReport | None = None,
        inspection: InspectionReport | None = None,
    ) -> None:
        self.doc_looks_like = doc_looks_like
        self.signature_detected = signature_detected
        self.subject_to_counter_offer = subject_to_counter_offer
        self.counter_meta = counter_meta or CounterMeta(
            recipient_signed=True, signed_date="2026-07-10", expiration="2026-07-12"
        )
        self.contingency_removal = contingency_removal or ContingencyRemoval()
        self.preapproval = preapproval or Preapproval()
        self.preliminary = preliminary or PreliminaryReport()
        self.inspection = inspection or InspectionReport()
        self.fields = (
            fields
            if fields is not None
            else [ExtractedField(name=n, value=v, confidence=c) for n, v, c in CANNED_FIELDS]
        )
        self.raise_blocked = raise_blocked
        self.raise_failed = raise_failed
        self.calls: list[int] = []  # byte sizes seen, for assertions

    def extract(self, *, pdf_bytes: bytes, doc_type: DocType) -> ExtractionResult:
        self.calls.append(len(pdf_bytes))
        if self.raise_blocked:
            raise ExtractionBlocked("Extraction is disabled (synthetic test gate)")
        if self.raise_failed:
            raise ExtractionFailed("extraction service error (synthetic)")
        return ExtractionResult(
            fields=list(self.fields),
            doc_looks_like=self.doc_looks_like,
            signature_detected=self.signature_detected,
            subject_to_counter_offer=self.subject_to_counter_offer,
        )

    def extract_counter_meta(self, *, pdf_bytes: bytes) -> CounterMeta:
        self.calls.append(len(pdf_bytes))
        if self.raise_blocked:
            raise ExtractionBlocked("Extraction is disabled (synthetic test gate)")
        if self.raise_failed:
            raise ExtractionFailed("extraction service error (synthetic)")
        return self.counter_meta

    def extract_contingency_removal(self, *, pdf_bytes: bytes) -> ContingencyRemoval:
        self.calls.append(len(pdf_bytes))
        if self.raise_blocked:
            raise ExtractionBlocked("Extraction is disabled (synthetic test gate)")
        if self.raise_failed:
            raise ExtractionFailed("extraction service error (synthetic)")
        return self.contingency_removal

    def extract_preapproval(self, *, pdf_bytes: bytes) -> Preapproval:
        self.calls.append(len(pdf_bytes))
        if self.raise_blocked:
            raise ExtractionBlocked("Extraction is disabled (synthetic test gate)")
        if self.raise_failed:
            raise ExtractionFailed("extraction service error (synthetic)")
        return self.preapproval

    def extract_preliminary(self, *, pdf_bytes: bytes) -> PreliminaryReport:
        self.calls.append(len(pdf_bytes))
        if self.raise_blocked:
            raise ExtractionBlocked("Extraction is disabled (synthetic test gate)")
        if self.raise_failed:
            raise ExtractionFailed("extraction service error (synthetic)")
        return self.preliminary

    def extract_inspection(self, *, pdf_bytes: bytes) -> InspectionReport:
        self.calls.append(len(pdf_bytes))
        if self.raise_blocked:
            raise ExtractionBlocked("Extraction is disabled (synthetic test gate)")
        if self.raise_failed:
            raise ExtractionFailed("extraction service error (synthetic)")
        return self.inspection
