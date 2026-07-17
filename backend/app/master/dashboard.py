"""Dashboard aggregation (Prompt 7) — a pure view over the SOR full-state.

No new data, no I/O: given the master's get_full_state dict it computes the
party drill-downs, role-count rollups, prioritized risk alerts, and the
communication center. Pure so it's tested without a database.
"""

from __future__ import annotations

from typing import Any

_SEVERITY_RANK = {"critical": 0, "high": 1, "warning": 2, "info": 3}
_PENDING_STATUSES = {"draft", "approved"}
_DONE_STATUSES = {"done", "complete"}


def build_dashboard(state: dict[str, Any]) -> dict[str, Any]:
    parties = state.get("parties", [])
    tasks = state.get("tasks", [])
    documents = state.get("documents", [])
    messages = state.get("messages", [])
    risk_flags = state.get("risk_flags", [])

    # --- per-party drill-down: outstanding items ---------------------------
    party_views = []
    for p in parties:
        pid = p["id"]
        their_tasks = [t for t in tasks if t.get("assigned_party_id") == pid]
        # Rows arrive unordered from PostgREST; pick the newest by created_at.
        their_msgs = sorted(
            (m for m in messages if m.get("party_id") == pid),
            key=lambda m: m.get("created_at") or "",
        )
        last_msg = their_msgs[-1] if their_msgs else None
        party_views.append(
            {
                "party": p,
                "open_tasks": [t for t in their_tasks if t.get("status") not in _DONE_STATUSES],
                "done_tasks": [t for t in their_tasks if t.get("status") in _DONE_STATUSES],
                "last_message_status": last_msg.get("status") if last_msg else None,
            }
        )

    # --- document rollups --------------------------------------------------
    # Counts of confirmed documents by type. NB: the documents table isn't
    # party-scoped in the MVP schema, so this is a document count, not a
    # distinct-buyer count — named accordingly to avoid misrepresentation.
    def _confirmed_doc(doc_type: str) -> int:
        return sum(
            1 for d in documents if d.get("doc_type") == doc_type and d.get("status") == "confirmed"
        )

    progress = {
        "buyers_total": sum(1 for p in parties if p.get("role") == "buyer"),
        "proof_of_funds_confirmed": _confirmed_doc("proof_of_funds"),
        "disclosures_confirmed": _confirmed_doc("disclosure"),
    }

    # --- prioritized risk alerts (severity, then unresolved first) ---------
    alerts = sorted(
        (f for f in risk_flags if not f.get("resolved", False)),
        key=lambda f: _SEVERITY_RANK.get(f.get("severity", "warning"), 2),
    )

    # --- communication center ---------------------------------------------
    communication = {
        "sent": [m for m in messages if m.get("status") == "sent"],
        "pending": [m for m in messages if m.get("status") in _PENDING_STATUSES],
        # Inbound reply threading is a future feature (§17); present but empty.
        "replies": [],
    }

    return {
        "transaction_id": state.get("transaction", {}).get("id"),
        "parties": party_views,
        "party_progress": progress,
        "risk_alerts": alerts,
        "communication": communication,
    }
