"""The deal story: cross-document synthesis (Prompt: universal read, layer 3).

Every document is read one by one — this module blends what was read into a
single narrative plus cross-document observations ("the FHA rider's escape
clause interacts with the appraisal contingency"; "the counter's COE governs,
not the PA's"). The model sees ONLY structured data already in the SOR
(effective fields, per-document facts/labels, deadlines, parties, open flags) —
never raw documents — and its output is advisory display text: it creates no
records, sends nothing, and is money-language-guarded at the route.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from app.common.zdr import check_zdr_gate


class StoryFailed(Exception):
    """Synthesis failed. Message must stay generic — never deal content."""


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warn", "critical"]},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "severity", "sources"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["narrative", "observations"],
    "additionalProperties": False,
}


def build_story_digest(state: dict[str, Any]) -> str:
    """Compact, structured, text-only digest of the deal for synthesis. Only
    SOR data — no raw document content, no storage paths, no tokens."""
    lines: list[str] = []
    prop = state.get("property") or {}
    lines.append(f"PROPERTY: {prop.get('address', '(unknown)')}")

    eff = state.get("effective_fields") or {}
    if eff:
        lines.append("EFFECTIVE TERMS (latest-confirmed wins):")
        for name, v in sorted(eff.items()):
            sup = f" (superseded from: {v['superseded_from']})" if v.get("superseded_from") else ""
            conf = "confirmed" if v.get("confirmed") else "unconfirmed"
            lines.append(f"- {name}: {v.get('value')} [{conf}]{sup}")

    parties = state.get("parties") or []
    if parties:
        lines.append("PARTIES: " + "; ".join(f"{p.get('role')}: {p.get('name')}" for p in parties))

    lines.append("DOCUMENTS ON FILE:")
    for d in state.get("documents") or []:
        name = d.get("label") or d.get("doc_type") or "unknown"
        lines.append(f"- [{d.get('doc_type')}] {name}")
        facts = d.get("facts") or {}
        if facts.get("summary"):
            lines.append(f"  summary: {facts['summary']}")
        for f in (facts.get("facts") or [])[:10]:
            lines.append(f"  fact: {f.get('label')} = {f.get('value')} ({f.get('kind')})")

    deadlines = state.get("deadlines") or []
    if deadlines:
        lines.append(
            "DEADLINES: " + "; ".join(f"{d.get('name')}: {d.get('due_date')}" for d in deadlines)
        )
    flags = [r for r in (state.get("risk_flags") or []) if not r.get("resolved")]
    if flags:
        lines.append("OPEN RISK FLAGS: " + "; ".join(r.get("description", "") for r in flags))
    return "\n".join(lines)


def _prompt(digest: str) -> str:
    return (
        "You are a California residential transaction coordinator's analyst. Below "
        "is the structured record of one deal: effective terms, parties, every "
        "document on file (with key facts read from each), deadlines, and open "
        "flags.\n\n"
        "Write, as JSON:\n"
        "1. narrative: 4–8 sentences telling the deal's story so far — how the "
        "documents fit together (what the contract set, what the counter changed, "
        "what the riders add, what's still outstanding). Plain, factual, useful to "
        "a TC. Refer to documents by name.\n"
        "2. observations: 2–6 cross-document observations — places where documents "
        "interact, agree, conflict, or leave a gap (e.g. a financing rider's "
        "appraisal clause vs the appraisal contingency; a fact on one document "
        "contradicting a term on another; something referenced but not on file). "
        "Each with severity (info | warn | critical) and sources = the document "
        "names it draws on. Only observations grounded in the data below — never "
        "invent facts.\n\n"
        "Rules: NEVER mention wiring instructions, bank/routing/account numbers, "
        "or payment-transfer details. No advice to remove contingencies — surface "
        "facts, the humans decide.\n\n"
        f"DEAL RECORD:\n{digest}"
    )


class Storyteller(Protocol):
    def tell(self, digest: str) -> dict[str, Any]: ...


class ClaudeStoryteller:
    def tell(self, digest: str) -> dict[str, Any]:
        check_zdr_gate()
        import anthropic

        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("STORY_MODEL", os.environ.get("DRAFTING_MODEL", "claude-sonnet-5"))
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8000,
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
                messages=[{"role": "user", "content": _prompt(digest)}],
            )
        except anthropic.APIStatusError as exc:
            raise StoryFailed(f"synthesis service error (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise StoryFailed("synthesis service unreachable") from exc
        if response.stop_reason == "refusal":
            raise StoryFailed("synthesis request was refused by the model")
        if response.stop_reason == "max_tokens":
            raise StoryFailed("synthesis output was truncated — try again")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise StoryFailed("synthesis returned no output")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise StoryFailed("synthesis returned unparseable output") from exc
        return parse_story(data)


def parse_story(data: dict[str, Any]) -> dict[str, Any]:
    obs = []
    for o in list(data.get("observations") or [])[:8]:
        text = str(o.get("text", "")).strip()[:400]
        if not text:
            continue
        sev = str(o.get("severity", "info"))
        if sev not in ("info", "warn", "critical"):
            sev = "info"
        obs.append(
            {
                "text": text,
                "severity": sev,
                "sources": [str(s)[:80] for s in (o.get("sources") or [])[:5]],
            }
        )
    return {"narrative": str(data.get("narrative", "")).strip()[:2400], "observations": obs}
