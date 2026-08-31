"""The TC's decision queue (P1) — cross-deal "what needs me", assembled pure.

The SOR generates decisions; the TC's job is clearing them. This module rolls the
whole book's pending decisions into one queue: drafts awaiting approval (Rule 3),
follow-up reminders that have come due, deadline-driving fields blocking a
timeline, unresolved risk flags — plus a deadline horizon over the next N
California business days. Pending inbox items stay ingestion-side (architecture
boundary); the frontend fetches that count from the existing ingestion endpoint.

Pure functions over repo.list_full_states() output; no I/O; unit-tested.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.common.dates import ca_today
from app.compliance.ca_holidays import ca_legal_holidays
from app.compliance.date_engine import is_business_day

_URGENCY_RANK = {"overdue": 0, "today": 1, "soon": 2, "later": 3}


def _days_to(iso: str | None, today: date) -> int | None:
    if not iso:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return None
    return (date(int(m[1]), int(m[2]), int(m[3])) - today).days


def _urgency(days: int | None) -> str:
    if days is None:
        return "later"
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days <= 3:
        return "soon"
    return "later"


def _address(state: dict[str, Any]) -> str:
    prop = state.get("property") or {}
    if prop.get("address"):
        return prop["address"]
    eff = state.get("effective_fields") or {}
    v = (eff.get("property_address") or {}).get("value")
    return v or "(no address)"


def _business_cutoff(today: date, business_days: int) -> date:
    """The calendar date `business_days` CA business days from today."""
    holidays = ca_legal_holidays({today.year, today.year + 1})
    d, counted = today, 0
    while counted < business_days:
        d = d + timedelta(days=1)
        if is_business_day(d, holidays):
            counted += 1
    return d


def build_attention(
    states: list[dict[str, Any]], *, now: datetime | None = None, horizon_business_days: int = 7
) -> dict[str, Any]:
    today = ca_today()
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff = _business_cutoff(today, horizon_business_days)

    items: list[dict[str, Any]] = []
    horizon: list[dict[str, Any]] = []
    counts = {"drafts": 0, "remindersDue": 0, "gateBlockedDeals": 0, "riskFlags": 0}

    for st in states:
        txn = st.get("transaction") or {}
        if (txn.get("status") or "open") != "open" or (txn.get("stage") or "") == "closed":
            continue
        tid = txn.get("id")
        addr = _address(st)
        parties = {p["id"]: p for p in st.get("parties") or []}
        messages = {m["id"]: m for m in st.get("messages") or []}

        # 1. Drafts awaiting approval — the Rule-3 queue. Full body + recipient
        # ride along so the review-before-send happens right in the queue row.
        for m in st.get("messages") or []:
            if m.get("status") != "draft":
                continue
            counts["drafts"] += 1
            rec = parties.get(m.get("party_id")) or {}
            items.append({
                "kind": "draft", "id": m["id"], "dealId": tid, "address": addr,
                "title": m.get("subject") or "Outbound message",
                "detail": f"To {rec.get('name') or 'recipient'}"
                          + (f" ({rec.get('role', '').replace('_', ' ')})" if rec.get("role") else ""),
                "recipientName": rec.get("name"), "recipientRole": rec.get("role"),
                "body": m.get("body") or "",
                "date": (m.get("created_at") or "")[:10] or None,
                "urgency": "later",
            })

        # 2. Follow-up reminders that have come due (the sent message got no
        # logged reply — P2 clears these automatically when a reply matches).
        for r in st.get("reminders") or []:
            if (r.get("remind_at") or "") > now_iso:
                continue
            msg = messages.get(r.get("message_id")) or {}
            if msg and msg.get("replied_at"):
                continue  # answered — nothing to chase
            counts["remindersDue"] += 1
            rec = parties.get(msg.get("party_id")) or {}
            items.append({
                "kind": "reminder", "id": r["id"], "dealId": tid, "address": addr,
                "title": f"No reply: {msg.get('subject') or 'sent message'}",
                "detail": (r.get("note") or "Consider following up")
                          + (f" · {rec.get('name')}" if rec.get("name") else ""),
                "messageId": r.get("message_id"),
                "recipientName": rec.get("name"), "recipientRole": rec.get("role"),
                "date": (r.get("remind_at") or "")[:10] or None,
                "urgency": "today",
            })

        # 3. Deadline-driving fields blocking this deal's timeline.
        gate = st.get("timeline_gate") or {}
        blocked = list(gate.get("missing_fields") or []) + list(gate.get("unconfirmed_fields") or [])
        if blocked and not gate.get("ready", True):
            counts["gateBlockedDeals"] += 1
            n_unconf = len(gate.get("unconfirmed_fields") or [])
            n_missing = len(gate.get("missing_fields") or [])
            bits = []
            if n_unconf:
                bits.append(f"{n_unconf} to confirm")
            if n_missing:
                bits.append(f"{n_missing} to enter")
            items.append({
                "kind": "gate", "id": f"gate-{tid}", "dealId": tid, "address": addr,
                "title": "Timeline blocked on deal terms",
                "detail": " · ".join(bits) + " — deadlines can't compute until these are set",
                "fields": blocked, "date": None, "urgency": "soon",
            })

        # 4. Unresolved risk flags.
        deadlines_by_id = {d["id"]: d for d in st.get("deadlines") or []}
        for f in st.get("risk_flags") or []:
            if f.get("resolved"):
                continue
            counts["riskFlags"] += 1
            dl = deadlines_by_id.get(f.get("deadline_id")) or {}
            days = _days_to(dl.get("due_date"), today)
            items.append({
                "kind": "risk", "id": f["id"], "dealId": tid, "address": addr,
                "title": f.get("description") or "Risk flagged",
                "detail": (f"{dl.get('name')} · " if dl.get("name") else "") + (f.get("severity") or "warning"),
                "severity": f.get("severity") or "warning",
                "date": dl.get("due_date"), "urgency": _urgency(days),
            })

        # 5. Deadline horizon: overdue + next N CA business days, whole book.
        for d in st.get("deadlines") or []:
            due = d.get("due_date")
            days = _days_to(due, today)
            if days is None:
                continue
            if days < 0 or due <= cutoff.isoformat():
                horizon.append({
                    "dealId": tid, "address": addr, "label": d.get("name"),
                    "date": due, "days": days, "urgency": _urgency(days),
                })

    items.sort(key=lambda x: (_URGENCY_RANK.get(x["urgency"], 3), x.get("date") or "9999", x["kind"]))
    horizon.sort(key=lambda x: x["date"] or "9999")
    return {
        "counts": counts,
        "total": len(items),
        "items": items,
        "horizon": horizon,
        "horizonCutoff": cutoff.isoformat(),
    }
