"""Per-role personalization of an invited party's workspace (§8 + privacy).

Each party sees a view tailored to their ROLE: the sections and the deal fields
that matter to them — and nothing they shouldn't (a vendor never sees the price).

A role maps to an ARCHETYPE; each archetype declares (a) an ordered list of
section keys the frontend renders, and (b) a field-visibility allowlist that is
enforced HERE, server-side, so a restricted role's payload never even contains
the hidden fields. Pure config + assembly, no I/O — fully unit-testable.
"""

from __future__ import annotations

from typing import Any

# role -> archetype (unlisted roles fall back to "default").
_ARCHETYPE: dict[str, str] = {
    "buyer": "buyer",
    "seller": "seller",
    "buyer_agent": "agent",
    "listing_agent": "agent",
    "broker": "agent",
    "lender": "lender",
    "loan_officer": "lender",
    "escrow": "escrow",
    "title": "title",
    "appraiser": "appraiser",
    "inspector_general": "inspector",
    "inspector_termite": "inspector",
    "inspector_roof": "inspector",
    "inspector_sewer": "inspector",
}


def archetype_for(role: str) -> str:
    return _ARCHETYPE.get(role, "default")


# archetype -> ordered section keys the frontend renders.
_SECTIONS: dict[str, list[str]] = {
    "buyer": ["property_card", "money_milestones", "key_dates", "my_tasks", "my_documents", "roster"],
    "seller": ["property_card", "offer_summary", "deal_progress", "included_items", "my_tasks", "my_documents", "roster"],
    "escrow": ["closing_summary", "key_dates", "roster", "my_tasks", "my_documents"],
    "inspector": ["property_card", "my_tasks", "key_dates", "my_documents"],
    "lender": ["loan_summary", "key_dates", "my_tasks", "my_documents"],
    "agent": ["property_card", "money_milestones", "key_dates", "deal_progress", "roster", "my_tasks", "my_documents"],
    "default": ["key_dates", "my_tasks", "my_documents", "roster"],
}


def sections_for(archetype: str) -> list[str]:
    return _SECTIONS.get(archetype, _SECTIONS["default"])


# archetype -> allowed effective-field names; None means "all deal fields".
# Restricted roles get a targeted set that deliberately EXCLUDES financials.
_FIELD_ALLOW: dict[str, frozenset[str] | None] = {
    "buyer": None,
    "seller": None,
    "agent": None,
    "escrow": None,  # escrow must see the money to close
    "appraiser": frozenset(
        {"property_address", "apn", "purchase_price", "acceptance_date",
         "appraisal_contingency_days", "close_of_escrow"}
    ),  # an appraiser legitimately sees the contract price
    "lender": frozenset(
        {"buyer_names", "purchase_price", "loan_amount", "down_payment", "initial_deposit_amount",
         "acceptance_date", "loan_contingency_days", "appraisal_contingency_days", "close_of_escrow"}
    ),  # loan officer needs the price (LTV) + loan terms
    "title": frozenset(
        {"seller_names", "apn", "property_address", "acceptance_date", "close_of_escrow"}
    ),
    "inspector": frozenset(
        {"property_address", "acceptance_date", "inspection_contingency_days"}
    ),  # NO financials
    "default": frozenset({"property_address", "acceptance_date", "close_of_escrow"}),
}


def visible_field_names(archetype: str) -> frozenset[str] | None:
    """Allowlist of effective-field names an archetype may see (None = all)."""
    return _FIELD_ALLOW.get(archetype, _FIELD_ALLOW["default"])


def _is_contact_pii(name: str) -> bool:
    # Other parties' emails/phones stay private — the coordinator holds contacts.
    return name.endswith("_email") or name.endswith("_phone")


def _due_for(task: dict[str, Any], deadlines: list[dict[str, Any]]) -> str | None:
    if task.get("due_date"):
        return task["due_date"]
    did = task.get("deadline_id")
    return next((d["due_date"] for d in deadlines if d["id"] == did), None) if did else None


def build_party_workspace(
    *, state: dict[str, Any], me: dict[str, Any], tier: str, property_view: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble the personalized, role-scoped workspace payload for one party.

    `state` is the master's full deal state; `me` is the party's own row; `tier`
    is from the signed invite session; `property_view` is optional address
    enrichment (facts/photo/links) merged onto the property card (Phase 3)."""
    archetype = archetype_for(me["role"])
    allow = visible_field_names(archetype)
    eff = state.get("effective_fields") or {}
    fields = {
        name: info.get("value")
        for name, info in eff.items()
        if info.get("value") is not None
        and not _is_contact_pii(name)
        and (allow is None or name in allow)
    }
    deadlines = state.get("deadlines", [])
    prop = state.get("property") or {}
    return {
        "me": {
            "name": me.get("name"), "role": me.get("role"), "email": me.get("email"),
            "company": me.get("company"), "tier": tier,
        },
        "archetype": archetype,
        "sections": sections_for(archetype),
        "property": {
            "address": prop.get("address"),
            "city": prop.get("city"),
            "zip": prop.get("zip"),
            "included_items": prop.get("included_items"),
            "excluded_items": prop.get("excluded_items"),
            **(property_view or {}),
        },
        "fields": fields,
        "stage": (state.get("transaction") or {}).get("stage"),
        # Everyone can see WHO is involved — names + roles only, no contact/financials.
        "roster": [{"name": p.get("name"), "role": p.get("role")} for p in state.get("parties", [])],
        "deadlines": [
            {"name": d["name"], "due_date": d["due_date"]}
            for d in sorted(deadlines, key=lambda x: x.get("due_date", ""))
        ],
        "my_tasks": [
            {
                "id": t["id"], "title": t["title"], "status": t["status"],
                "due_date": _due_for(t, deadlines), "priority": t.get("priority", "normal"),
            }
            for t in state.get("tasks", [])
            if t.get("assigned_party_id") == me["id"]
        ],
        "my_documents": [
            {"id": d["id"], "doc_type": d.get("doc_type"), "status": d.get("status"), "created_at": d.get("created_at")}
            for d in state.get("documents", [])
            if d.get("external_ref") == f"party:{me['id']}"
        ],
    }
