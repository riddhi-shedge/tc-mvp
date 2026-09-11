"""Real §5 field extraction via Claude (Phase 4) — part (a) only.

Hard gates, in order:
1. ZDR gate (Rule 5): refuses to run unless ZDR_CONFIRMED=true or the operator
   has explicitly acknowledged SYNTHETIC_ONLY=true. No real client document may
   enter this pipeline until Anthropic zero-data-retention is confirmed.
2. Whitelist: the model is asked for exactly the human-verified §5 fields and
   the output is filtered to those names regardless (Rule 2: wiring/payment
   data can never come through — it isn't on the list).

The model runs with structured output (JSON schema), returns per-field
{value, confidence}, and reports doc type + signature indicators so "wrong doc
type" and "unsigned" become explicit §4 error states — never silent guesses.
No document content or field values are ever logged or placed in error
messages.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from app.common.zdr import ZdrNotConfirmed, check_zdr_gate
from app.contracts.documents import DocType
from app.contracts.fields import S5_FIELDS, is_extractable_field
from app.contracts.payload import CounterMeta, ExtractedField

# Back-compat alias — the gate now lives in app/common/zdr.py (shared).
ExtractionBlocked = ZdrNotConfirmed


class ExtractionFailed(Exception):
    """The extraction service failed. Message must stay generic (no content)."""


@dataclass(frozen=True)
class ExtractionResult:
    fields: list[ExtractedField]
    doc_looks_like: str
    signature_detected: bool
    # True when the PA indicates acceptance is subject to a counter offer (so the
    # PA's terms may not be final until that counter is uploaded).
    subject_to_counter_offer: bool = False
    # When doc_looks_like is 'other': the model's free-text best guess at what
    # the document actually is (e.g. "AVID — Agent Visual Inspection Disclosure").
    # Advisory only — surfaced to the TC, never filed without their say-so.
    doc_guess: str = ""


@dataclass(frozen=True)
class ContingencyRemoval:
    """Which contingencies a C.A.R. Contingency Removal (CR-B) form removes. The
    model resolves the form's paragraph 2 (individual), 3 (all-except), and 4 (all)
    checkboxes into the net removed state per contingency. A removed contingency's
    deadline no longer applies — the buyer can't back out on that basis."""

    all_contingencies_removed: bool = False
    loan_removed: bool = False
    appraisal_removed: bool = False
    inspection_removed: bool = False
    insurance_removed: bool = False
    effective_date: str | None = None


@dataclass(frozen=True)
class Preapproval:
    """A mortgage preapproval / underwriter letter: who it approves, its
    expiration, the approved amount, and the loan officer's contact + NMLS id."""

    buyer_names: str | None = None
    expiration: str | None = None
    loan_amount: str | None = None
    officer_name: str | None = None
    officer_nmls: str | None = None
    officer_company: str | None = None
    officer_email: str | None = None
    officer_phone: str | None = None


@dataclass(frozen=True)
class PreliminaryReport:
    """A preliminary ("title") report: its effective date, the vested owner
    ("title to said estate or interest at the date hereof is vested in ..."), and
    the APN of the property."""

    effective_date: str | None = None
    vestee: str | None = None
    apn: str | None = None


@dataclass(frozen=True)
class InspectionReport:
    """A property or termite/pest inspection report: the inspected address, the
    inspection date, and the inspector (individual and/or company) with contact."""

    property_address: str | None = None
    inspection_date: str | None = None
    inspector_name: str | None = None
    inspector_company: str | None = None
    inspector_email: str | None = None
    inspector_phone: str | None = None


@dataclass(frozen=True)
class DocFact:
    """One fact read off a document outside the typed §5 paths. ADVISORY ONLY:
    facts inform the TC in the ledger — they never create fields, parties,
    deadlines, or any SOR record. Only the human-verified §5 list drives those."""

    label: str
    value: str
    kind: str  # date | amount | name | term | other
    confidence: float


@dataclass(frozen=True)
class DocFacts:
    doc_kind: str
    summary: str
    facts: list[DocFact]
    signature_detected: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "doc_kind": self.doc_kind,
            "summary": self.summary,
            "signature_detected": self.signature_detected,
            "facts": [
                {"label": f.label, "value": f.value, "kind": f.kind, "confidence": f.confidence}
                for f in self.facts
            ],
        }


class Extractor(Protocol):
    def extract(self, *, pdf_bytes: bytes, doc_type: DocType) -> ExtractionResult: ...

    def extract_facts(self, *, pdf_bytes: bytes) -> DocFacts: ...

    def verify_identity(self, *, pdf_bytes: bytes) -> dict[str, str | None]: ...

    def extract_counter_meta(self, *, pdf_bytes: bytes) -> CounterMeta: ...

    def extract_contingency_removal(self, *, pdf_bytes: bytes) -> ContingencyRemoval: ...

    def extract_preapproval(self, *, pdf_bytes: bytes) -> Preapproval: ...

    def extract_preliminary(self, *, pdf_bytes: bytes) -> PreliminaryReport: ...

    def extract_inspection(self, *, pdf_bytes: bytes) -> InspectionReport: ...


# The classify vocabulary — ONE source of truth for the model schema enum AND
# parse-time validation. These two drifted once (schema knew 13 types, the
# parser coerced 5 of them back to 'other'); the eval suite caught it.
_DOC_LOOKS_LIKE = {
    "purchase_agreement",
    "counter_offer",
    "seller_counter_offer",
    "buyer_counter_offer",
    "contingency_removal",
    "preapproval",
    "preliminary_report",
    "proof_of_funds",
    "disclosure",
    "property_inspection",
    "termite_inspection",
    "inspection_report",
    "other",
}


def _facts_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "doc_kind": {"type": "string"},
            "summary": {"type": "string"},
            "signature_indicators": {"type": "boolean"},
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "value": {"type": "string"},
                        "kind": {"type": "string", "enum": ["date", "amount", "name", "term", "other"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["label", "value", "kind", "confidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["doc_kind", "summary", "signature_indicators", "facts"],
        "additionalProperties": False,
    }


def _facts_prompt() -> str:
    return (
        "You are reading a document from a California residential real-estate "
        "transaction for a transaction coordinator. It may be ANY document in the "
        "real-estate universe — an addendum, FHA/VA amendatory clause, HOA packet, "
        "escrow instructions, NHD report, home-warranty invoice, appraisal, email "
        "printout, anything.\n\n"
        "Report:\n"
        "1. doc_kind: what this document is, in a few words a CA TC would use.\n"
        "2. summary: 1–3 plain sentences — what the document does for the deal.\n"
        "3. facts: up to 15 key facts PRINTED ON the document — dates, amounts, "
        "names, obligations, elections/checkboxes, terms. Each with a short label, "
        "the value exactly as written, its kind, and confidence 0.0–1.0. Only what "
        "is actually on the page — NEVER infer or guess. Skip boilerplate.\n"
        "4. signature_indicators: true only if signature blocks appear executed.\n\n"
        "Rules:\n"
        "- NEVER extract, summarize, or mention wiring instructions, bank account "
        "numbers, routing numbers, or any payment-transfer details, even if "
        "present. They must not appear anywhere in your output.\n"
        "- These facts are informational context for a human. Report them plainly."
    )


def parse_doc_facts(data: dict[str, Any]) -> DocFacts:
    facts: list[DocFact] = []
    for entry in list(data.get("facts") or [])[:20]:
        label = str(entry.get("label", "")).strip()[:80]
        value = str(entry.get("value", "")).strip()[:240]
        if not label or not value:
            continue
        kind = str(entry.get("kind", "other"))
        if kind not in ("date", "amount", "name", "term", "other"):
            kind = "other"
        try:
            conf = min(1.0, max(0.0, float(entry.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        facts.append(DocFact(label=label, value=value, kind=kind, confidence=conf))
    return DocFacts(
        doc_kind=str(data.get("doc_kind", "")).strip()[:120],
        summary=str(data.get("summary", "")).strip()[:600],
        facts=facts,
        signature_detected=bool(data.get("signature_indicators", False)),
    )


def _inspection_schema() -> dict[str, Any]:
    keys = (
        "property_address", "inspection_date",
        "inspector_name", "inspector_company", "inspector_email", "inspector_phone",
    )
    return {
        "type": "object",
        "properties": {k: {"type": "string"} for k in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


def _inspection_prompt() -> str:
    return (
        "This is a property or termite/pest (wood-destroying-organisms) inspection "
        "report for a home. Report as JSON strings (empty string when absent):\n"
        "- property_address: the address of the inspected property, as written.\n"
        "- inspection_date: the date the inspection was performed, as written.\n"
        "- inspector_name: the individual inspector's full name, if given.\n"
        "- inspector_company: the inspection company's name.\n"
        "- inspector_email and inspector_phone: the inspector/company contact.\n"
        "Never extract payment, bank, or wiring details."
    )


def _preliminary_schema() -> dict[str, Any]:
    keys = ("effective_date", "vestee", "apn")
    return {
        "type": "object",
        "properties": {k: {"type": "string"} for k in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


def _preliminary_prompt() -> str:
    return (
        "This is a California preliminary ('title') report. Report as JSON strings "
        "(empty string when absent):\n"
        "- effective_date: the report's effective / dated-as-of date, as written.\n"
        "- vestee: the current owner of record — the party named in 'Title to said "
        "estate or interest at the date hereof is vested in ...'.\n"
        "- apn: the Assessor's Parcel Number of the property.\n"
        "Never extract owner SSNs, account numbers, or payment details."
    )


def _preapproval_schema() -> dict[str, Any]:
    keys = (
        "buyer_names", "expiration", "loan_amount",
        "officer_name", "officer_nmls", "officer_company", "officer_email", "officer_phone",
    )
    return {
        "type": "object",
        "properties": {k: {"type": "string"} for k in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


def _preapproval_prompt() -> str:
    return (
        "This is a mortgage preapproval / underwriter / credit-approval letter for "
        "a home purchase. Report as JSON strings (empty string when absent):\n"
        "- buyer_names: the approved borrower name(s), as written.\n"
        "- expiration: the date the approval is valid until / expires, as written.\n"
        "- loan_amount: the maximum loan amount approved (a dollar figure).\n"
        "- officer_name: the loan officer / mortgage consultant's full name.\n"
        "- officer_nmls: their NMLS / NMLSR ID number.\n"
        "- officer_company: the lender / mortgage company name.\n"
        "- officer_email and officer_phone: their contact details.\n"
        "Never extract borrower SSNs, account numbers, or wiring details."
    )


def _cr_schema() -> dict[str, Any]:
    props = {
        k: {"type": "boolean"}
        for k in (
            "all_contingencies_removed", "loan_removed", "appraisal_removed",
            "inspection_removed", "insurance_removed",
        )
    }
    props["effective_date"] = {"type": "string"}
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _cr_prompt() -> str:
    return (
        "This is a California Contingency Removal (C.A.R. Form CR-B / CR-S). Report "
        "which BUYER contingencies this form removes, resolving its checkboxes:\n"
        "- Paragraph 2 removes ONLY the individually checked contingencies "
        "(A Loan, B Appraisal, C Investigation/inspection, D Insurance, …).\n"
        "- Paragraph 3 removes ALL contingencies EXCEPT the ones checked as "
        "exceptions.\n"
        "- Paragraph 4 removes ALL contingencies unconditionally.\n\n"
        "Return the NET removed state as JSON booleans: all_contingencies_removed "
        "(true only if para 3 with no relevant exception, or para 4), and per "
        "contingency loan_removed / appraisal_removed / inspection_removed / "
        "insurance_removed (true if removed by any of paragraphs 2–4). Also "
        "effective_date: the form's date, as written (empty string if none)."
    )


def _counter_meta_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            # As written; empty string when not stated (avoids nullable unions).
            "expiration": {"type": "string"},
            "recipient_signed": {"type": "boolean"},
            "signed_date": {"type": "string"},
            "subject_to_further_counter": {"type": "boolean"},
        },
        "required": [
            "expiration", "recipient_signed", "signed_date", "subject_to_further_counter",
        ],
        "additionalProperties": False,
    }


def _counter_meta_prompt() -> str:
    return (
        "This is a California residential counter offer (C.A.R. Seller Counter "
        "Offer or Buyer Counter Offer). Report ONLY these facts as JSON:\n"
        "1. expiration: the date/time by which this counter must be accepted and "
        "signed to be valid, exactly as written (e.g. 'April 30, 2025 5:00 PM'). "
        "Empty string if none is stated.\n"
        "2. recipient_signed: true only if the party who must ACCEPT this counter "
        "(the BUYER for a seller counter offer; the SELLER for a buyer counter "
        "offer) has signed and dated their acceptance on this document.\n"
        "3. signed_date: the date that accepting party signed, as written. Empty "
        "string if they have not signed.\n"
        "4. subject_to_further_counter: true if a box such as 'SUBJECT TO THE "
        "ATTACHED COUNTER OFFER' (i.e. acceptance is subject to a further counter "
        "offer) is checked.\n"
        "Never extract wiring, bank-account, or payment-transfer details."
    )


def _output_schema() -> dict[str, Any]:
    # `fields` is an ARRAY (name enum + value + confidence), not a per-field
    # nullable map: the structured-outputs compiler caps union-typed parameters
    # at 16, and 30 nullable properties exceeded it (learned from a live 400).
    # A field that isn't on the document is simply omitted from the array.
    return {
        "type": "object",
        "properties": {
            "doc_looks_like": {"type": "string", "enum": sorted(_DOC_LOOKS_LIKE)},
            "doc_guess": {"type": "string"},
            "signature_indicators": {"type": "boolean"},
            "subject_to_counter_offer": {"type": "boolean"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    # Property ORDER is deliberate: the model writes `evidence`
                    # (a verbatim quote) BEFORE `value`, grounding each answer in
                    # the page — the quote-first technique measurably improves
                    # extraction accuracy. Evidence is advisory (not yet stored).
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": [spec.name for spec in S5_FIELDS],
                        },
                        "evidence": {"type": "string"},
                        "value": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["name", "evidence", "value", "confidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "doc_looks_like",
            "doc_guess",
            "signature_indicators",
            "subject_to_counter_offer",
            "fields",
        ],
        "additionalProperties": False,
    }


def _prompt() -> str:
    field_lines = "\n".join(f"- {spec.name}: {spec.description}" for spec in S5_FIELDS)
    return (
        "You are extracting deal fields from a signed California residential "
        "purchase agreement for a transaction coordinator.\n\n"
        "Extract ONLY the fields listed below, exactly as written on the "
        "document. Rules:\n"
        "1. NEVER extract, summarize, or mention wiring instructions, bank "
        "account numbers, routing numbers, or any payment-transfer details, "
        "even if present. They are not on the list and must not appear "
        "anywhere in your output.\n"
        "2. Return one entry in `fields` per field you can actually read on "
        "the document. If a field is not present or not legible, OMIT it — "
        "never guess or infer a value.\n"
        "2b. For each field, FIRST copy `evidence`: the exact short phrase from "
        "the document (under 120 characters) that states the value — quote it "
        "verbatim before writing `value`. If you cannot point to such a phrase "
        "on the page, the field does not belong in your output.\n"
        "3. confidence is 0.0–1.0: how certain you are the value is exactly "
        "what the document says. Use low confidence (<0.7) for anything "
        "inferred, ambiguous, or partially legible.\n"
        "4. Report doc_looks_like: what kind of document this actually is — the "
        "BEST match from this vocabulary (use 'other' only when none fits):\n"
        "   - purchase_agreement: a residential purchase agreement (C.A.R. RPA)\n"
        "   - seller_counter_offer / buyer_counter_offer / counter_offer: a counter "
        "offer form (SCO/BCO/CO), whichever side made it\n"
        "   - contingency_removal: a CR form removing buyer contingencies\n"
        "   - preapproval: a lender/underwriter letter approving the borrower's loan\n"
        "   - preliminary_report: a title company's preliminary (title) report\n"
        "   - proof_of_funds: a bank/asset statement evidencing buyer funds\n"
        "   - disclosure: a seller disclosure form (TDS, SPQ, NHD, lead paint, ...)\n"
        "   - property_inspection: a general home inspection report\n"
        "   - termite_inspection: a pest/wood-destroying-organism (WDO) report\n"
        "   - inspection_report: any other inspection report (roof, sewer, ...)\n"
        "5. Report signature_indicators: true only if the document shows "
        "signature blocks that appear executed (names/marks/dates in them).\n"
        "6. Report subject_to_counter_offer: true if the agreement indicates "
        "acceptance is subject to a counter offer — e.g. a 'Seller Counter Offer' "
        "or 'Buyer Counter Offer' checkbox is checked, or it references an attached "
        "counter offer (SCO/BCO). This means the printed terms may not be final.\n"
        "7. Report doc_guess: when doc_looks_like is 'other', name what the "
        "document most likely is in a few words, as a California transaction "
        "coordinator would say it (e.g. 'AVID — Agent Visual Inspection "
        "Disclosure', 'HOA CC&Rs package', 'Escrow general provisions', 'Home "
        "warranty invoice'). Base it only on the document itself. When "
        "doc_looks_like is any listed type, return an empty string.\n\n"
        f"Fields to extract:\n{field_lines}"
    )


class ClaudeExtractor:
    """Anthropic-backed extractor. Model from EXTRACTION_MODEL (default
    claude-sonnet-5, per the approved Phase 4 plan)."""

    def extract(self, *, pdf_bytes: bytes, doc_type: DocType) -> ExtractionResult:
        check_zdr_gate()
        import anthropic

        # Bounded like every other external boundary in this codebase.
        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("EXTRACTION_MODEL", "claude-sonnet-5")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                output_config={"format": {"type": "json_schema", "schema": _output_schema()}},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                                },
                            },
                            {"type": "text", "text": _prompt()},
                        ],
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            # Generic on purpose — never echo document content (Rule 5).
            raise ExtractionFailed(f"extraction service error (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionFailed("extraction service unreachable") from exc

        if response.stop_reason == "refusal":
            raise ExtractionFailed("extraction request was refused by the model")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ExtractionFailed("extraction returned no output")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ExtractionFailed("extraction returned unparseable output") from exc
        return parse_extraction_output(data)

    def _structured(self, pdf_bytes: bytes, schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        """Shared model call for the small single-document JSON extractors
        (counter meta, contingency removal, preapproval, …)."""
        check_zdr_gate()
        import anthropic

        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("EXTRACTION_MODEL", "claude-sonnet-5")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                output_config={"format": {"type": "json_schema", "schema": schema}},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            raise ExtractionFailed(f"extraction service error (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionFailed("extraction service unreachable") from exc
        if response.stop_reason == "refusal":
            raise ExtractionFailed("extraction request was refused by the model")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ExtractionFailed("extraction returned no output")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ExtractionFailed("extraction returned unparseable output") from exc

    def verify_identity(self, *, pdf_bytes: bytes) -> dict[str, str | None]:
        """Generator-verifier (§ CLAUDE.md adversarial Q5): an INDEPENDENT
        read answering only 'who buys, who sells' from the signature blocks
        and party designations — cross-checked against extraction. A layout
        misread here once inverted every party on a live deal."""
        data = self._structured(
            pdf_bytes,
            {
                "type": "object",
                "properties": {"buyer": {"type": "string"}, "seller": {"type": "string"}},
                "required": ["buyer", "seller"],
                "additionalProperties": False,
            },
            "Look ONLY at the party designations and signature blocks of this "
            "California real-estate document. Who is the BUYER (the party "
            "acquiring the property) and who is the SELLER? Answer with the "
            "names exactly as printed. If a side is not determinable, use an "
            "empty string. Never mention any payment or wiring details.",
        )
        return {
            "buyer": (str(data.get("buyer", "")).strip() or None),
            "seller": (str(data.get("seller", "")).strip() or None),
        }

    def extract_facts(self, *, pdf_bytes: bytes) -> DocFacts:
        """Universal read: key facts from ANY real-estate document (the types
        without a typed §5 path). Advisory output only — see DocFact."""
        return parse_doc_facts(self._structured(pdf_bytes, _facts_schema(), _facts_prompt()))

    def extract_counter_meta(self, *, pdf_bytes: bytes) -> CounterMeta:
        check_zdr_gate()
        import anthropic

        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("EXTRACTION_MODEL", "claude-sonnet-5")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                output_config={"format": {"type": "json_schema", "schema": _counter_meta_schema()}},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                                },
                            },
                            {"type": "text", "text": _counter_meta_prompt()},
                        ],
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            raise ExtractionFailed(f"extraction service error (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionFailed("extraction service unreachable") from exc

        if response.stop_reason == "refusal":
            raise ExtractionFailed("extraction request was refused by the model")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ExtractionFailed("extraction returned no output")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ExtractionFailed("extraction returned unparseable output") from exc
        return CounterMeta(
            expiration=(str(data.get("expiration", "")).strip() or None),
            recipient_signed=bool(data.get("recipient_signed", False)),
            signed_date=(str(data.get("signed_date", "")).strip() or None),
            subject_to_further_counter=bool(data.get("subject_to_further_counter", False)),
        )

    def extract_contingency_removal(self, *, pdf_bytes: bytes) -> ContingencyRemoval:
        check_zdr_gate()
        import anthropic

        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("EXTRACTION_MODEL", "claude-sonnet-5")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                output_config={"format": {"type": "json_schema", "schema": _cr_schema()}},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                                },
                            },
                            {"type": "text", "text": _cr_prompt()},
                        ],
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            raise ExtractionFailed(f"extraction service error (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionFailed("extraction service unreachable") from exc

        if response.stop_reason == "refusal":
            raise ExtractionFailed("extraction request was refused by the model")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise ExtractionFailed("extraction returned no output")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ExtractionFailed("extraction returned unparseable output") from exc
        return ContingencyRemoval(
            all_contingencies_removed=bool(data.get("all_contingencies_removed", False)),
            loan_removed=bool(data.get("loan_removed", False)),
            appraisal_removed=bool(data.get("appraisal_removed", False)),
            inspection_removed=bool(data.get("inspection_removed", False)),
            insurance_removed=bool(data.get("insurance_removed", False)),
            effective_date=(str(data.get("effective_date", "")).strip() or None),
        )

    def extract_preapproval(self, *, pdf_bytes: bytes) -> Preapproval:
        data = self._structured(pdf_bytes, _preapproval_schema(), _preapproval_prompt())
        s = lambda k: (str(data.get(k, "")).strip() or None)  # noqa: E731
        return Preapproval(
            buyer_names=s("buyer_names"),
            expiration=s("expiration"),
            loan_amount=s("loan_amount"),
            officer_name=s("officer_name"),
            officer_nmls=s("officer_nmls"),
            officer_company=s("officer_company"),
            officer_email=s("officer_email"),
            officer_phone=s("officer_phone"),
        )

    def extract_preliminary(self, *, pdf_bytes: bytes) -> PreliminaryReport:
        data = self._structured(pdf_bytes, _preliminary_schema(), _preliminary_prompt())
        s = lambda k: (str(data.get(k, "")).strip() or None)  # noqa: E731
        return PreliminaryReport(
            effective_date=s("effective_date"), vestee=s("vestee"), apn=s("apn")
        )

    def extract_inspection(self, *, pdf_bytes: bytes) -> InspectionReport:
        data = self._structured(pdf_bytes, _inspection_schema(), _inspection_prompt())
        s = lambda k: (str(data.get(k, "")).strip() or None)  # noqa: E731
        return InspectionReport(
            property_address=s("property_address"),
            inspection_date=s("inspection_date"),
            inspector_name=s("inspector_name"),
            inspector_company=s("inspector_company"),
            inspector_email=s("inspector_email"),
            inspector_phone=s("inspector_phone"),
        )





def parse_extraction_output(data: dict[str, Any]) -> ExtractionResult:
    """Whitelist-filter and normalize model output. Non-§5 names are dropped
    silently (Rule 2 defense in depth); duplicates keep the highest-confidence
    entry; confidences are clamped to [0, 1]."""
    best: dict[str, ExtractedField] = {}
    order: list[str] = []
    for entry in data.get("fields") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if not is_extractable_field(name):
            continue
        value = str(entry.get("value", "")).strip()
        if not value:
            continue
        try:
            confidence = float(entry.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        evidence = str(entry.get("evidence", "")).strip()[:200] or None
        if name not in best:
            order.append(name)
            best[name] = ExtractedField(
                name=name, value=value, confidence=confidence, evidence=evidence
            )
        elif confidence > best[name].confidence:
            best[name] = ExtractedField(
                name=name, value=value, confidence=confidence, evidence=evidence
            )
    doc_looks_like = str(data.get("doc_looks_like", "other"))
    if doc_looks_like not in _DOC_LOOKS_LIKE:  # schema-enforced, re-validated anyway
        doc_looks_like = "other"
    return ExtractionResult(
        fields=[best[name] for name in order],
        doc_looks_like=doc_looks_like,
        signature_detected=bool(data.get("signature_indicators", False)),
        subject_to_counter_offer=bool(data.get("subject_to_counter_offer", False)),
        doc_guess=str(data.get("doc_guess", "")).strip()[:120],
    )
