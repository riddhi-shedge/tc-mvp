"""Buyer's-agent command center — cross-deal portfolio aggregation (pure).

Unlike the principal workspaces (one deal, calm), the agent runs a *book*. These
pure functions take the full state of every deal in the book and assemble the
portfolio the agent triages from: pipeline summaries, a stats bar, the cross-book
deadline radar, and the co-pilot activity feed. The approval queue (AI drafts) and
its live drafting live alongside in routes.py — this module is I/O-free and
unit-testable.

Money/PII: summaries carry only what the operator needs; no bank/account fields.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.master.event_catalog import agent_activity

# DB stage -> the agent-facing DealStage vocabulary.
_STAGE: dict[str, str] = {
    "new": "escrow_open", "cont": "contingencies", "closing": "closing", "closed": "closed",
}


def _today() -> date:
    return date.today()


def _days_to(iso: str | None) -> int | None:
    if not iso:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return None
    d = date(int(m[1]), int(m[2]), int(m[3]))
    return (d - _today()).days


def _risk(days: int | None) -> str:
    if days is None:
        return "ok"
    if days <= 2:  # overdue (negative) or imminent — the dropped-ball zone
        return "at_risk"
    if days <= 7:
        return "watch"
    return "ok"


_RISK_RANK = {"ok": 0, "watch": 1, "at_risk": 2}


def _flat_fields(state: dict[str, Any]) -> dict[str, Any]:
    eff = state.get("effective_fields") or {}
    return {k: v.get("value") for k, v in eff.items() if v.get("value") is not None}


def _first_party(parties: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    return next((p for p in parties if p.get("role") == role), None)


def deal_summary(state: dict[str, Any]) -> dict[str, Any]:
    txn = state.get("transaction") or {}
    fields = _flat_fields(state)
    prop = state.get("property") or {}
    deadlines = state.get("deadlines") or []

    # upcoming deadlines (overdue first, then soonest); "next critical" is the head
    dated = [
        {"id": d.get("id"), "label": d.get("name"), "date": d.get("due_date"), "days": _days_to(d.get("due_date"))}
        for d in deadlines if d.get("due_date")
    ]
    # include overdue (negative days) — a missed deadline is the top risk to flag
    upcoming = sorted([d for d in dated if d["days"] is not None], key=lambda x: x["days"])
    nxt = upcoming[0] if upcoming else None
    close = next((d for d in dated if re.search(r"escrow|clos", d["label"] or "", re.I)), None)

    deal_risk = "ok"
    for d in upcoming:
        r = _risk(d["days"])
        if _RISK_RANK[r] > _RISK_RANK[deal_risk]:
            deal_risk = r

    appraisal = fields.get("appraisal_contingency_present")
    return {
        "id": txn.get("id"),
        "clientName": fields.get("buyer_names") or "Buyer",
        "propertyAddress": prop.get("address") or fields.get("property_address") or "Property",
        "stage": _STAGE.get(txn.get("stage") or "", "escrow_open"),
        "nextDeadline": (
            {"label": nxt["label"], "date": nxt["date"], "risk": _risk(nxt["days"])} if nxt else None
        ),
        "closeDate": close["date"] if close else None,
        "risk": deal_risk,
        "peek": {
            "emd": fields.get("initial_deposit_amount") or "—",
            "loan": fields.get("loan_amount") or fields.get("financing_type") or "—",
            "appraisalOrNext": (
                "Appraisal contingency active" if str(appraisal).lower() == "true"
                else (nxt["label"] if nxt else "No upcoming deadline")
            ),
        },
    }


def deadline_radar(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for state in deals:
        txn = state.get("transaction") or {}
        if (txn.get("stage") or "") == "closed":
            continue
        fields = _flat_fields(state)
        prop = state.get("property") or {}
        client = fields.get("buyer_names") or "Buyer"
        addr = prop.get("address") or fields.get("property_address") or "Property"
        for d in state.get("deadlines") or []:
            days = _days_to(d.get("due_date"))
            if days is None:
                continue
            out.append({
                "id": d.get("id"), "dealId": txn.get("id"), "label": d.get("name"),
                "date": d.get("due_date"), "risk": _risk(days),
                "clientName": client, "propertyAddress": addr,
            })
    return sorted(out, key=lambda x: x["date"] or "")


def copilot_feed(deals: list[dict[str, Any]], limit: int = 40) -> dict[str, Any]:
    """Cross-book co-pilot feed, rendered from the shared event catalog (§4) so the
    agent surfaces and the principal surfaces project the same SOR events."""
    events: list[dict[str, Any]] = []
    handled = escalated = 0
    for state in deals:
        txn = state.get("transaction") or {}
        for ev in agent_activity(state.get("audit_log") or [], deal_id=txn.get("id")):
            events.append(ev)
            days_ago = _days_to((ev.get("occurredAt") or "")[:10])  # last-7-days tally
            if days_ago is not None and days_ago >= -7:
                if ev["mode"] == "needs_you":
                    escalated += 1
                else:
                    handled += 1
    events.sort(key=lambda e: e.get("occurredAt") or "", reverse=True)
    return {"events": events[:limit], "weekly": {"handled": handled, "escalated": escalated}}


def portfolio_stats(summaries: list[dict[str, Any]], pending_drafts: int) -> dict[str, Any]:
    active = [s for s in summaries if s["stage"] != "closed"]
    at_risk = sum(1 for s in active if s["risk"] == "at_risk")
    closing = 0
    for s in active:
        days = _days_to(s.get("closeDate"))
        if days is not None and 0 <= days <= 7:
            closing += 1
    return {
        "activeDeals": len(active),
        "needYouToday": pending_drafts,
        "atRisk": at_risk,
        "closingThisWeek": closing,
    }


def build_agent_portfolio(*, deals: list[dict[str, Any]], me: dict[str, Any], pending_drafts: int) -> dict[str, Any]:
    summaries = [deal_summary(s) for s in deals]
    # Most urgent deals first (at_risk, then watch), then soonest close.
    summaries.sort(key=lambda s: (-_RISK_RANK[s["risk"]], s.get("closeDate") or "9999"))
    feed = copilot_feed(deals)
    return {
        "me": {"name": me.get("name"), "role": me.get("role")},
        "stats": portfolio_stats(summaries, pending_drafts),
        "deals": summaries,
        "radar": deadline_radar(deals),
        "activity": feed["events"],
        "weekly": feed["weekly"],
    }


# ---- co-pilot draft targets (which outreach a deal needs) --------------------

# A purpose the co-pilot can draft, matched to the deadline it chases and the
# party role it addresses. Ordered by urgency of the underlying obligation.
_DRAFT_RULES: list[tuple[str, str, str]] = [
    # (deadline name regex, purpose, recipient role)
    ("loan", "lender_status", "lender"),
    ("appraisal", "appraisal_status", "lender"),
    ("inspection", "inspection_schedule", "inspector_general"),
    ("disclosure", "disclosure_reminder", "listing_agent"),
    ("earnest|deposit|emd", "escrow_checkin", "buyer"),
    ("escrow|clos", "escrow_checkin", "escrow"),
]


# ---- Listing-agent surface (near-mirror; listing frame) ---------------------

# DB stage -> ListingStatus. "new" (freshly opened) is framed as an on-market
# listing with offers to present; cont/closing are in escrow.
_LISTING_STATUS: dict[str, str] = {
    "new": "active", "cont": "in_escrow", "closing": "in_escrow", "closed": "closed",
}
_STALE_DOM = 30  # days-on-market above which a listing surfaces as stale (clay)


def _cents(value: Any) -> int | None:
    if value is None:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return round(float(m.group(0).replace(",", "")) * 100)
    except ValueError:
        return None


def _synth_dom(tid: str) -> int:
    """Deterministic illustrative days-on-market (no list date in the SOR)."""
    return 6 + (abs(hash(tid)) % 58)


def _financing(fields: dict[str, Any]) -> str:
    if str(fields.get("all_cash", "")).lower() == "true":
        return "cash"
    ft = str(fields.get("financing_type") or "").lower()
    for k in ("cash", "fha", "va"):
        if k in ft:
            return k
    return "conventional"


def listing_summary(state: dict[str, Any]) -> dict[str, Any]:
    txn = state.get("transaction") or {}
    tid = txn.get("id") or ""
    fields = _flat_fields(state)
    prop = state.get("property") or {}
    status = _LISTING_STATUS.get(txn.get("stage") or "", "in_escrow")
    price = _cents(fields.get("purchase_price"))
    dom = _synth_dom(tid) if status == "active" else None

    dated = [
        {"id": d.get("id"), "label": d.get("name"), "date": d.get("due_date"), "days": _days_to(d.get("due_date"))}
        for d in state.get("deadlines") or [] if d.get("due_date")
    ]
    upcoming = sorted([d for d in dated if d["days"] is not None], key=lambda x: x["days"])
    nxt = upcoming[0] if upcoming else None
    close = next((d for d in dated if re.search(r"escrow|clos", d["label"] or "", re.I)), None)

    if status == "active":
        risk = "at_risk" if (dom or 0) > _STALE_DOM else "watch" if (dom or 0) > 20 else "ok"
        peek = {"line1": f"List {fields.get('purchase_price') or '—'}", "line2": "3 offers in", "line3": f"{dom} days on market"}
    elif status == "in_escrow":
        risk = _risk(nxt["days"]) if nxt else "ok"
        peek = {"line1": f"EMD {fields.get('initial_deposit_amount') or '—'}",
                "line2": f"Loan {fields.get('loan_amount') or fields.get('financing_type') or '—'}",
                "line3": nxt["label"] if nxt else "No upcoming deadline"}
    else:
        risk = "ok"
        peek = {"line1": "Closed", "line2": fields.get("purchase_price") or "—", "line3": ""}

    return {
        "id": tid,
        "sellerName": fields.get("seller_names") or "Seller",
        "propertyAddress": prop.get("address") or fields.get("property_address") or "Property",
        "status": status,
        "listPriceCents": price,
        "daysOnMarket": dom,
        "offerCount": 3 if status == "active" else 0,  # illustrative pending offers
        "nextDeadline": ({"label": nxt["label"], "date": nxt["date"], "risk": _risk(nxt["days"])} if (status == "in_escrow" and nxt) else None),
        "closeDate": close["date"] if close else None,
        "risk": risk,
        "peek": peek,
    }


def listing_stats(summaries: list[dict[str, Any]], pending_drafts: int) -> dict[str, Any]:
    live = [s for s in summaries if s["status"] != "closed"]
    return {
        "liveListings": len(live),
        "offersToReview": sum(1 for s in summaries if s["offerCount"] > 0),
        "inEscrow": sum(1 for s in summaries if s["status"] == "in_escrow"),
        "needYouToday": pending_drafts,
    }


def build_listing_portfolio(*, deals: list[dict[str, Any]], me: dict[str, Any], pending_drafts: int) -> dict[str, Any]:
    summaries = [listing_summary(s) for s in deals]
    summaries.sort(key=lambda s: (-1 if s["offerCount"] > 0 else 0, -_RISK_RANK[s["risk"]], s.get("closeDate") or "9999"))
    feed = copilot_feed(deals)
    return {
        "me": {"name": me.get("name"), "role": me.get("role")},
        "stats": listing_stats(summaries, pending_drafts),
        "listings": summaries,
        "radar": deadline_radar(deals),
        "activity": feed["events"],
        "weekly": feed["weekly"],
    }


def build_offer_comparison(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Illustrative side-by-side offers for a listing. The SOR holds one accepted
    offer per deal; competing offers are synthesized (sample=True) around the real
    accepted terms to demonstrate the present-to-seller workflow. The app/AI never
    marks a winner — tradeoff tags are neutral descriptors."""
    fields = _flat_fields(state)
    base = _cents(fields.get("purchase_price"))
    if not base:
        return []
    dp = _cents(fields.get("down_payment"))
    dp_pct = round(dp / base * 100) if dp else None
    m = re.search(r"\d+", str(fields.get("close_of_escrow") or ""))
    close_days = int(m.group(0)) if m else 30
    fin = _financing(fields)
    conts = "None" if str(fields.get("inspection_contingency_present", "")).lower() == "false" else "Standard"

    return [
        {
            "id": "offer-accepted", "buyerAgentName": fields.get("buyer_agent") or "Buyer's agent",
            "priceCents": base, "financing": fin, "downPaymentPct": dp_pct, "contingencies": conts,
            "closeDays": close_days, "strength": "strong" if fin == "cash" or conts == "None" else "moderate",
            "tradeoffTag": "Best balance", "netToSellerEstimateCents": round(base * 0.938),
            "state": "received", "sample": False,
        },
        {
            "id": "offer-cash", "buyerAgentName": "Sample — cash buyer",
            "priceCents": round(base * 0.975), "financing": "cash", "downPaymentPct": 100, "contingencies": "None",
            "closeDays": 14, "strength": "strong", "tradeoffTag": "Most certain",
            "netToSellerEstimateCents": round(base * 0.975 * 0.955), "state": "received", "sample": True,
        },
        {
            "id": "offer-high", "buyerAgentName": "Sample — financed buyer",
            "priceCents": round(base * 1.03), "financing": "conventional", "downPaymentPct": 10, "contingencies": "Full (17d)",
            "closeDays": 45, "strength": "weak", "tradeoffTag": "Highest price",
            "netToSellerEstimateCents": round(base * 1.03 * 0.93), "state": "received", "sample": True,
        },
    ]


def draft_targets(state: dict[str, Any], *, existing_purposes: set[str], horizon_days: int = 30) -> list[dict[str, Any]]:
    """Outreach this deal needs but doesn't yet have a draft for. Each target names
    the purpose, the recipient party, and the deadline that motivates it."""
    txn = state.get("transaction") or {}
    if (txn.get("stage") or "") == "closed":
        return []
    parties = state.get("parties") or []
    deadlines = state.get("deadlines") or []
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for regex, purpose, role in _DRAFT_RULES:
        if purpose in existing_purposes or purpose in seen:
            continue
        dl = next((d for d in deadlines if re.search(regex, d.get("name") or "", re.I)), None)
        if not dl:
            continue
        days = _days_to(dl.get("due_date"))
        # draft for anything upcoming OR overdue (an overdue deadline is the urgent case)
        if days is None or days > horizon_days:
            continue
        recipient = _first_party(parties, role)
        if not recipient:
            continue
        seen.add(purpose)
        targets.append({
            "purpose": purpose, "recipient": recipient, "deadline": dl,
            "days": days, "urgency": "urgent" if days <= 3 else "normal",
            "risk_class": "low" if purpose in ("escrow_checkin", "disclosure_reminder") else "standard",
        })
    return targets
