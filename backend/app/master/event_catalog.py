"""Cross-surface event catalog — the §4 heart of the data/event contract.

One fact is written once to the SOR (an audit-log row) and *fans out* to four
projections. This module is the single place that maps a SOR audit action to a
canonical ``TransactionEventType`` and renders its **role-relative** text: the
same event reads "You confirmed your earnest-money deposit" to the buyer who did
it, "The buyer confirmed their earnest-money deposit" to everyone else, and
"Buyer confirmed the earnest-money deposit" in an agent's operator feed.

All four surfaces' activity feeds derive from here, so they can never drift.
Nothing in this module does I/O; it's pure and unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# The canonical event vocabulary (contract §4). The SOR does not yet emit every
# one as a discrete audit action — several are derived from state today — but the
# type is the forward contract every surface maps its projections onto.
TransactionEventType = Literal[
    "listing_activated", "showing_logged", "offer_received", "offers_presented", "offer_accepted",
    "escrow_opened", "emd_due", "emd_received",
    "disclosures_completed", "disclosures_delivered", "disclosures_acknowledged",
    "inspection_scheduled", "inspection_report_ready",
    "repair_requested", "repair_resolved",
    "appraisal_ordered", "appraisal_result",
    "loan_status_changed", "contingency_removed", "all_contingencies_removed",
    "walkthrough_scheduled", "clear_to_close", "funded", "recorded", "proceeds_disbursed", "possession_transferred",
    "deadline_approaching", "deadline_missed", "deal_cancelled",
]

ActorRole = Literal["buyer", "seller", "buyer_agent", "listing_agent", "system", "ai"]
Mode = Literal["autonomous", "needs_you"]

_PRINCIPALS = frozenset({"buyer", "seller"})
_AGENTS = frozenset({"buyer_agent", "listing_agent"})


@dataclass(frozen=True)
class _Entry:
    event: str | None            # canonical TransactionEventType, if this maps to one
    actor: ActorRole             # who performed it (for role-relative rendering)
    principal: bool              # visible in a principal (buyer/seller) feed?
    agent: bool                  # visible in an agent (co-pilot) feed?
    self_text: str | None        # shown to the acting principal ("You …")
    other_text: str              # shown to other principals ("The buyer …")
    agent_text: str              # operator phrasing for the agent feed
    mode: Mode                   # agent feed: autonomous vs escalated (needs you)


# SOR audit action -> catalog entry. Buyer-facing strings preserved verbatim from
# the prior per-surface maps so existing projections are unchanged; seller/agent
# variants are the new role-relative renderings the contract (§4) requires.
CATALOG: dict[str, _Entry] = {
    "payload.written": _Entry(None, "system", True, True, None, "A new document was added to your deal", "Logged new deal activity from an update", "autonomous"),
    "document.party_uploaded": _Entry(None, "system", True, True, None, "A document was uploaded", "Filed an uploaded document", "autonomous"),
    "compliance.run": _Entry(None, "system", True, True, None, "Your timeline was updated", "Refreshed the deadline timeline", "autonomous"),
    "message.sent": _Entry(None, "system", True, True, None, "A message went out on your deal", "An outbound message was sent", "autonomous"),
    "field.confirmed": _Entry(None, "system", True, True, None, "Deal details were confirmed", "Confirmed a deal term", "autonomous"),
    "party.created": _Entry(None, "system", True, True, None, "Someone joined your deal team", "Added a party to the deal", "autonomous"),
    "transaction.stage": _Entry("escrow_opened", "system", True, True, None, "Your deal moved to a new stage", "Advanced the deal to a new stage", "autonomous"),
    "party.deposit_verified": _Entry(
        "emd_received", "buyer", True, True,
        "You confirmed your earnest-money deposit", "The buyer confirmed their earnest-money deposit",
        "Buyer confirmed the earnest-money deposit", "autonomous"),
    "party.disclosure_attested": _Entry(
        "disclosures_delivered", "seller", True, True,
        "You marked a disclosure delivered", "The seller delivered a disclosure",
        "Seller delivered a disclosure", "autonomous"),
    "party.disbursement_verified": _Entry(
        None, "seller", True, True,
        "You confirmed your proceeds account", "The seller confirmed their proceeds account",
        "Seller confirmed their proceeds account", "autonomous"),
    # AI/agent operational events — never shown to principals (they don't see the
    # co-pilot's internal drafting), only in the agent feed.
    "message.drafted": _Entry(None, "ai", False, True, None, "", "Drafted an outbound message for your approval", "needs_you"),
    "message.approved": _Entry(None, "buyer_agent", False, True, None, "", "You approved and logged an outbound message", "autonomous"),
}


def event_type(action: str) -> str | None:
    entry = CATALOG.get(action)
    return entry.event if entry else None


def _sorted(audit_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(audit_log, key=lambda r: r.get("created_at") or "", reverse=True)


def principal_activity(audit_log: list[dict[str, Any]], viewer_role: str, limit: int = 14) -> list[dict[str, Any]]:
    """Role-relative activity feed for a principal (buyer/seller). Events the
    principal shouldn't see (the co-pilot's internal ops) never appear."""
    out: list[dict[str, Any]] = []
    for row in _sorted(audit_log):
        entry = CATALOG.get(row.get("action") or "")
        if not entry or not entry.principal:
            continue
        text = entry.self_text if (entry.actor == viewer_role and entry.self_text) else entry.other_text
        out.append({"id": row.get("id"), "text": text, "occurredAt": row.get("created_at"), "type": entry.event})
        if len(out) >= limit:
            break
    return out


def agent_activity(audit_log: list[dict[str, Any]], deal_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Operator/co-pilot feed rows for an agent: autonomous vs escalated, with the
    canonical event type and actor role attached (contract §2.8 / §4)."""
    out: list[dict[str, Any]] = []
    for row in _sorted(audit_log):
        entry = CATALOG.get(row.get("action") or "")
        if not entry or not entry.agent:
            continue
        out.append({
            "id": row.get("id"), "dealId": deal_id, "text": entry.agent_text,
            "mode": entry.mode, "actorRole": entry.actor, "type": entry.event,
            "occurredAt": row.get("created_at"),
        })
        if limit is not None and len(out) >= limit:
            break
    return out
