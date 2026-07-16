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
from app.contracts.payload import ExtractedField

# Back-compat alias — the gate now lives in app/common/zdr.py (shared).
ExtractionBlocked = ZdrNotConfirmed


class ExtractionFailed(Exception):
    """The extraction service failed. Message must stay generic (no content)."""


@dataclass(frozen=True)
class ExtractionResult:
    fields: list[ExtractedField]
    doc_looks_like: str
    signature_detected: bool


class Extractor(Protocol):
    def extract(self, *, pdf_bytes: bytes, doc_type: DocType) -> ExtractionResult: ...


def _output_schema() -> dict[str, Any]:
    # `fields` is an ARRAY (name enum + value + confidence), not a per-field
    # nullable map: the structured-outputs compiler caps union-typed parameters
    # at 16, and 30 nullable properties exceeded it (learned from a live 400).
    # A field that isn't on the document is simply omitted from the array.
    return {
        "type": "object",
        "properties": {
            "doc_looks_like": {
                "type": "string",
                "enum": [
                    "purchase_agreement",
                    "proof_of_funds",
                    "disclosure",
                    "inspection_report",
                    "other",
                ],
            },
            "signature_indicators": {"type": "boolean"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": [spec.name for spec in S5_FIELDS],
                        },
                        "value": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["name", "value", "confidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["doc_looks_like", "signature_indicators", "fields"],
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
        "3. confidence is 0.0–1.0: how certain you are the value is exactly "
        "what the document says. Use low confidence (<0.7) for anything "
        "inferred, ambiguous, or partially legible.\n"
        "4. Report doc_looks_like: what kind of document this actually is.\n"
        "5. Report signature_indicators: true only if the document shows "
        "signature blocks that appear executed (names/marks/dates in them).\n\n"
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


_DOC_LOOKS_LIKE = {
    "purchase_agreement",
    "proof_of_funds",
    "disclosure",
    "inspection_report",
    "other",
}


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
        if name not in best:
            order.append(name)
            best[name] = ExtractedField(name=name, value=value, confidence=confidence)
        elif confidence > best[name].confidence:
            best[name] = ExtractedField(name=name, value=value, confidence=confidence)
    doc_looks_like = str(data.get("doc_looks_like", "other"))
    if doc_looks_like not in _DOC_LOOKS_LIKE:  # schema-enforced, re-validated anyway
        doc_looks_like = "other"
    return ExtractionResult(
        fields=[best[name] for name in order],
        doc_looks_like=doc_looks_like,
        signature_detected=bool(data.get("signature_indicators", False)),
    )
