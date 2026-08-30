"""Per-role personalization of an invited party's workspace (§8 + privacy).

Each party sees a view tailored to their ROLE: the sections and the deal fields
that matter to them — and nothing they shouldn't (a vendor never sees the price).

A role maps to an ARCHETYPE; each archetype declares (a) an ordered list of
section keys the frontend renders, and (b) a field-visibility allowlist that is
enforced HERE, server-side, so a restricted role's payload never even contains
the hidden fields. Pure config + assembly, no I/O — fully unit-testable.
"""

from __future__ import annotations

import re
from typing import Any

from app.master.event_catalog import principal_activity

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


# --- buyer workspace: extra derived data (activity feed, callable team, deposit) ---

# Roles the buyer legitimately CALLS (their service team) — phone is exposed to the
# buyer only for these, a scoped exception to the contact-PII rule so the buyer can
# verify wires / reach their team. Seller-side + other buyers stay private.
_BUYER_CALLABLE_ROLES = frozenset(
    {"escrow", "title", "lender", "loan_officer", "buyer_agent", "broker",
     "inspector_general", "inspector_termite", "inspector_roof", "inspector_sewer", "appraiser"}
)

# The buyer/seller activity feed now derives from the shared cross-surface event
# catalog (event_catalog.principal_activity), so the same SOR event renders
# role-relative text on every surface. These constants remain for the deposit /
# disclosure / disbursement state reads below.
_DEPOSIT_VERIFIED_ACTION = "party.deposit_verified"
_DISCLOSURE_ATTESTED_ACTION = "party.disclosure_attested"
_DISBURSEMENT_VERIFIED_ACTION = "party.disbursement_verified"


def _buyer_roster(parties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in parties:
        entry: dict[str, Any] = {"id": p.get("id"), "name": p.get("name"), "role": p.get("role")}
        if p.get("role") in _BUYER_CALLABLE_ROLES and p.get("phone"):
            entry["phone"] = p.get("phone")
        out.append(entry)
    return out


def _buyer_deposit(
    *, fields: dict[str, Any], deadlines: list[dict[str, Any]],
    parties: list[dict[str, Any]], audit_log: list[dict[str, Any]], party_id: str,
) -> dict[str, Any] | None:
    amount = fields.get("initial_deposit_amount")
    if not amount:
        return None
    escrow = next((p for p in parties if p.get("role") == "escrow"), None)
    due = next((d["due_date"] for d in deadlines if re.search(r"earnest|deposit|emd", d["name"], re.I)), None)
    verified = any(
        r.get("action") == _DEPOSIT_VERIFIED_ACTION and (r.get("details") or {}).get("party_id") == party_id
        for r in audit_log
    )
    return {
        "amount": amount,
        "payee": escrow.get("name") if escrow else None,
        "dueDate": due,
        "verifiedByBuyer": verified,
        "escrowContactId": escrow.get("id") if escrow else None,
    }


# --- seller workspace: extra derived data (deal-health, disclosures, net sheet) ---

# The seller calls their listing agent, escrow, and title — not the buyer's side.
_SELLER_CALLABLE_ROLES = frozenset({"listing_agent", "escrow", "title", "broker"})

# Standard CA seller cost estimates for the net sheet (clearly labeled ESTIMATE).
_COMMISSION_RATE = 0.05  # total agent commission, both sides
_CLOSING_COST_RATE = 0.012  # escrow + title + recording + misc

# The CA disclosure spine. Ordered; lead-based paint only applies pre-1978.
_SELLER_DISCLOSURES: list[tuple[str, str]] = [
    ("tds", "Transfer Disclosure Statement (TDS)"),
    ("spq", "Seller Property Questionnaire (SPQ)"),
    ("nhd", "Natural Hazard Disclosure (NHD)"),
]


def _money_to_cents(value: Any) -> int | None:
    if value is None:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return round(float(m.group(0).replace(",", "")) * 100)
    except ValueError:
        return None


def _seller_roster(parties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in parties:
        entry: dict[str, Any] = {"id": p.get("id"), "name": p.get("name"), "role": p.get("role")}
        if p.get("role") in _SELLER_CALLABLE_ROLES and p.get("phone"):
            entry["phone"] = p.get("phone")
        out.append(entry)
    return out


def _contingency_removed(fields: dict[str, Any], kind: str) -> bool:
    present = fields.get(f"{kind}_contingency_present")
    days = fields.get(f"{kind}_contingency_days")
    if present is not None:
        return str(present).lower() == "false"
    return bool(days) and re.search(r"removed|waived|none|n/?a", str(days), re.I) is not None


def _seller_deal_health(fields: dict[str, Any], audit_log: list[dict[str, Any]]) -> dict[str, Any]:
    """The buyer-side milestones the seller watches — read-only, never actionable."""
    milestones: list[dict[str, Any]] = []

    emd = fields.get("initial_deposit_amount")
    if emd:
        verified = any(r.get("action") == _DEPOSIT_VERIFIED_ACTION for r in audit_log)
        milestones.append({
            "id": "emd", "label": "Earnest money deposit",
            "detail": f"{emd} in escrow" if verified else f"{emd} — awaiting buyer",
            "state": "complete" if verified else "in_progress", "actionableBySeller": False,
        })

    active = 0
    for kind, label in (("inspection", "Inspection contingency"), ("appraisal", "Appraisal contingency"), ("loan", "Loan contingency")):
        removed = _contingency_removed(fields, kind)
        if not removed:
            active += 1
        milestones.append({
            "id": kind, "label": f"{label} {'removed' if removed else 'active'}",
            "detail": None, "state": "complete" if removed else "in_progress",
            "actionableBySeller": False,
        })

    if str(fields.get("all_cash", "")).lower() == "true":
        milestones.append({"id": "loan_status", "label": "All-cash purchase — no financing", "detail": fields.get("financing_type"), "state": "complete", "actionableBySeller": False})
    else:
        loan_ok = _contingency_removed(fields, "loan")
        milestones.append({
            "id": "loan_status",
            "label": "Buyer's financing secured" if loan_ok else "Buyer's loan in underwriting",
            "detail": fields.get("financing_type"),
            "state": "complete" if loan_ok else "in_progress", "actionableBySeller": False,
        })

    meter = "on_track" if active == 0 else "watch"
    return {"meter": meter, "milestones": milestones}


def _seller_disclosures(
    *, deadlines: list[dict[str, Any]], audit_log: list[dict[str, Any]],
    party_id: str, property_view: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    kinds = list(_SELLER_DISCLOSURES)
    year = ((property_view or {}).get("details") or {}).get("year_built")
    try:
        if year is not None and int(str(year)[:4]) < 1978:
            kinds.append(("lead_paint", "Lead-based paint disclosure"))
    except (ValueError, TypeError):
        pass

    due = next((d["due_date"] for d in deadlines if re.search(r"disclosure", d["name"], re.I)), None)
    attested = {
        (r.get("details") or {}).get("kind")
        for r in audit_log
        if r.get("action") == _DISCLOSURE_ATTESTED_ACTION and (r.get("details") or {}).get("party_id") == party_id
    }
    return [
        {
            "id": kind, "kind": kind, "title": title,
            "state": "delivered" if kind in attested else "draft",
            "dueDate": due,
        }
        for kind, title in kinds
    ]


def _seller_net_sheet(
    *, fields: dict[str, Any], audit_log: list[dict[str, Any]], party_id: str,
) -> dict[str, Any] | None:
    sale = _money_to_cents(fields.get("purchase_price"))
    if not sale:
        return None
    commission = round(sale * _COMMISSION_RATE)
    closing = round(sale * _CLOSING_COST_RATE)
    lines = [
        {"label": "Sale price", "amountCents": sale, "kind": "credit"},
        {"label": "Agent commission (est. 5%)", "amountCents": commission, "kind": "debit"},
        {"label": "Escrow, title & closing (est.)", "amountCents": closing, "kind": "debit"},
    ]
    net = sale - commission - closing
    verified = any(
        r.get("action") == _DISBURSEMENT_VERIFIED_ACTION and (r.get("details") or {}).get("party_id") == party_id
        for r in audit_log
    )
    return {
        "lines": lines,
        "estimatedNetProceedsCents": net,
        "disbursementVerified": verified,
        "beforeMortgagePayoff": True,  # the seller's existing loan payoff isn't in deal data
    }


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
    parties = state.get("parties", [])
    payload: dict[str, Any] = {
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
    if archetype == "buyer":
        # Extra data the rich buyer workspace needs: a callable team roster (with the
        # escrow/team phone for the wire step), a buyer-safe activity feed, and the
        # deposit block — all derived from the existing deal state.
        payload["roster"] = _buyer_roster(parties)
        payload["activity"] = principal_activity(state.get("audit_log", []), "buyer")
        payload["deposit"] = _buyer_deposit(
            fields=fields, deadlines=deadlines, parties=parties,
            audit_log=state.get("audit_log", []), party_id=me["id"],
        )
    elif archetype == "seller":
        # The seller workspace watches the BUYER's progress (deal-health), tracks the
        # seller's disclosure spine, and shows an estimated net sheet — all derived
        # from deal state. Interactivity is limited to first-party seller actions.
        audit = state.get("audit_log", [])
        payload["roster"] = _seller_roster(parties)
        payload["activity"] = principal_activity(audit, "seller")
        payload["dealHealth"] = _seller_deal_health(fields, audit)
        payload["disclosures"] = _seller_disclosures(
            deadlines=deadlines, audit_log=audit, party_id=me["id"], property_view=property_view,
        )
        payload["netSheet"] = _seller_net_sheet(fields=fields, audit_log=audit, party_id=me["id"])
        payload["requests"] = []  # repair/credit requests — none modeled in deal state yet
    return payload
