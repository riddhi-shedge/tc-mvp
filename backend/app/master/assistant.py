"""Deal Q&A assistant: answers a TC's question grounded ONLY in the deal's own
records (confirmed contract fields, computed deadlines, parties, documents, tasks,
risk flags). It never uses outside knowledge and says so when the answer isn't in
the deal — a retrieval-grounded chat over the system of record for one deal.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from app.common.zdr import check_zdr_gate


class AssistantError(Exception):
    """The assistant couldn't produce an answer (service error / refusal)."""


_SYSTEM = (
    "You are a helpful assistant for a California residential real-estate TRANSACTION "
    "COORDINATOR (TC). Answer the TC's question using ONLY the DEAL CONTEXT provided — it "
    "is drawn from the uploaded documents (the purchase agreement and any others) and this "
    "deal's records. Rules:\n"
    "1. If the answer is not present in the context, say plainly that you couldn't find it "
    "in this deal's documents/data. Never guess or use outside knowledge.\n"
    "2. Be concise and factual; quote the specific values, names, and dates from the context.\n"
    "3. Do NOT give legal advice or opinions (e.g. whether to remove a contingency, how to "
    "negotiate, or how to respond to a Notice to Perform) — for those, tell the TC to consult "
    "the agent or broker.\n"
    "4. Never provide wiring or payment-transfer instructions.\n"
    "5. Flag when a value you're citing is extracted-but-not-yet-confirmed by the TC."
)


def build_context(state: dict[str, Any]) -> str:
    """Assemble a readable, grounded context block from a deal's full state."""
    out: list[str] = []
    prop = state.get("property") or {}
    out.append(f"PROPERTY: {prop.get('address', '(unknown)')}")
    txn = state.get("transaction") or {}
    if txn.get("status"):
        out.append(f"DEAL STATUS: {txn['status']}")

    fields = state.get("extracted_fields", [])
    confirmed = [f for f in fields if f.get("confirmed")]
    unconfirmed = [f for f in fields if not f.get("confirmed")]
    if confirmed:
        out.append("\nCONTRACT FIELDS (confirmed by the TC):")
        out += [f"- {f['name']}: {f['value']}" for f in confirmed]
    if unconfirmed:
        out.append("\nCONTRACT FIELDS (extracted but NOT yet confirmed — may be uncertain):")
        out += [f"- {f['name']}: {f['value']} (confidence {f.get('confidence')})" for f in unconfirmed]

    dls = state.get("deadlines", [])
    if dls:
        out.append("\nCOMPUTED DEADLINES:")
        out += [f"- {d['name']}: {d['due_date']}" for d in sorted(dls, key=lambda x: x.get("due_date", ""))]

    parties = state.get("parties", [])
    if parties:
        out.append("\nPARTIES / CONTACTS:")
        for p in parties:
            bits = [p.get("name") or "(unnamed)", p.get("role"), p.get("company"), p.get("email"), p.get("phone")]
            out.append("- " + " · ".join(str(b) for b in bits if b))

    docs = state.get("documents", [])
    if docs:
        out.append("\nDOCUMENTS ON FILE:")
        out += [f"- {d.get('doc_type', 'document')} ({d.get('status', '')})" for d in docs]

    tasks = state.get("tasks", [])
    if tasks:
        out.append("\nTASKS:")
        out += [f"- [{t.get('status')}] {t.get('title')}" for t in tasks]

    risks = [r for r in state.get("risk_flags", []) if not r.get("resolved")]
    if risks:
        out.append("\nOPEN RISK FLAGS:")
        out += [f"- ({r.get('severity')}) {r.get('description')}" for r in risks]

    return "\n".join(out)


class DealAssistant(Protocol):
    def answer(self, *, context: str, question: str) -> str: ...


class ClaudeAssistant:
    def answer(self, *, context: str, question: str) -> str:
        check_zdr_gate()
        import anthropic

        client = anthropic.Anthropic(timeout=120.0, max_retries=1)
        model = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5")
        prompt = f"DEAL CONTEXT:\n{context}\n\nTC QUESTION: {question}"
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIStatusError as exc:
            raise AssistantError(f"assistant service error (HTTP {exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise AssistantError("assistant service unreachable") from exc
        if response.stop_reason == "refusal":
            raise AssistantError("the assistant declined to answer")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise AssistantError("the assistant returned no answer")
        return text.strip()
