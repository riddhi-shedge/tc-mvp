"""Pure-function tests for the buyer's-agent portfolio aggregation."""

from __future__ import annotations

from datetime import timedelta

from app.common.dates import ca_today
from app.master.agent_portfolio import (
    build_agent_portfolio,
    build_listing_portfolio,
    build_offer_comparison,
    copilot_feed,
    deadline_radar,
    deal_summary,
    draft_targets,
    listing_stats,
    listing_summary,
    portfolio_stats,
)


def _iso(days_from_today: int) -> str:
    # Anchor to the CA calendar day — deadline math evaluates in America/Los_Angeles,
    # so a server-local date.today() here would drift by ±1 day on non-PT machines.
    return (ca_today() + timedelta(days=days_from_today)).isoformat()


def _state(*, tid: str, stage: str = "cont", deadlines=None, parties=None, messages=None, audit=None, fields=None) -> dict:
    base_fields = {"buyer_names": "Rajkumar Methuku", "initial_deposit_amount": "$57,000",
                   "loan_amount": "$1,100,000", "property_address": "21989 McClellan Rd"}
    base_fields.update(fields or {})
    return {
        "transaction": {"id": tid, "stage": stage},
        "property": {"address": "21989 McClellan Rd"},
        "effective_fields": {k: {"value": v} for k, v in base_fields.items()},
        "deadlines": deadlines or [],
        "parties": parties or [],
        "messages": messages or [],
        "audit_log": audit or [],
        "tasks": [], "documents": [],
    }


def test_deal_summary_picks_soonest_deadline_and_risk():
    st = _state(
        tid="d1", stage="cont",
        deadlines=[
            {"id": "x", "name": "Close of escrow", "due_date": _iso(20)},
            {"id": "y", "name": "Loan contingency", "due_date": _iso(1)},  # imminent → at_risk
        ],
    )
    s = deal_summary(st)
    assert s["stage"] == "contingencies"
    assert s["nextDeadline"]["label"] == "Loan contingency" and s["nextDeadline"]["risk"] == "at_risk"
    assert s["closeDate"] == _iso(20)
    assert s["risk"] == "at_risk"  # worst of its deadlines
    assert s["peek"]["emd"] == "$57,000"


def test_deadline_radar_skips_closed_and_sorts_by_date():
    deals = [
        _state(tid="d1", stage="cont", deadlines=[{"id": "a", "name": "Appraisal", "due_date": _iso(5)}]),
        _state(tid="d2", stage="closed", deadlines=[{"id": "b", "name": "Old", "due_date": _iso(-2)}]),
    ]
    radar = deadline_radar(deals)
    assert [r["dealId"] for r in radar] == ["d1"]  # closed deal excluded
    assert radar[0]["risk"] == "watch"  # 5 days out


def test_overdue_counts_as_at_risk():
    st = _state(tid="d1", deadlines=[{"id": "a", "name": "Loan contingency", "due_date": _iso(-10)}])
    assert deal_summary(st)["risk"] == "at_risk"


def test_portfolio_stats():
    deals = [deal_summary(s) for s in [
        _state(tid="d1", stage="cont", deadlines=[{"id": "a", "name": "Loan", "due_date": _iso(1)}]),
        _state(tid="d2", stage="closing", deadlines=[{"id": "b", "name": "Close of escrow", "due_date": _iso(4)}]),
        _state(tid="d3", stage="closed"),
    ]]
    stats = portfolio_stats(deals, pending_drafts=6)
    assert stats["activeDeals"] == 2  # closed excluded
    assert stats["needYouToday"] == 6
    assert stats["atRisk"] == 1  # d1 imminent
    assert stats["closingThisWeek"] == 1  # d2 closes in 4 days


def test_copilot_feed_modes_and_weekly():
    st = _state(tid="d1", audit=[
        {"id": "1", "action": "message.drafted", "entity_id": "m1", "created_at": _iso(-1) + "T10:00:00Z"},
        {"id": "2", "action": "compliance.run", "created_at": _iso(-2) + "T10:00:00Z"},
        {"id": "3", "action": "secret.internal", "created_at": _iso(-1) + "T10:00:00Z"},  # never surfaces
    ])
    feed = copilot_feed([st])
    modes = {e["text"]: e["mode"] for e in feed["events"]}
    assert len(feed["events"]) == 2  # internal event filtered out
    assert feed["weekly"] == {"handled": 1, "escalated": 1}
    assert any(m == "needs_you" for m in modes.values())


def test_draft_targets_matches_and_dedupes():
    st = _state(
        tid="d1", stage="cont",
        deadlines=[{"id": "l", "name": "Loan contingency", "due_date": _iso(3)}],
        parties=[{"id": "p1", "name": "Wells Fargo", "role": "lender"}],
    )
    targets = draft_targets(st, existing_purposes=set())
    assert [t["purpose"] for t in targets] == ["lender_status"]
    assert targets[0]["recipient"]["id"] == "p1" and targets[0]["urgency"] == "urgent"
    # already-drafted purpose is skipped
    assert draft_targets(st, existing_purposes={"lender_status"}) == []


def test_draft_targets_needs_a_recipient_party():
    st = _state(tid="d1", deadlines=[{"id": "l", "name": "Loan contingency", "due_date": _iso(3)}], parties=[])
    assert draft_targets(st, existing_purposes=set()) == []


def test_build_agent_portfolio_sorts_risky_deals_first():
    deals = [
        _state(tid="calm", stage="cont", deadlines=[{"id": "a", "name": "Appraisal", "due_date": _iso(40)}]),
        _state(tid="hot", stage="cont", deadlines=[{"id": "b", "name": "Loan", "due_date": _iso(0)}]),
    ]
    port = build_agent_portfolio(deals=deals, me={"name": "Dinesh", "role": "buyer_agent"}, pending_drafts=2)
    assert port["deals"][0]["id"] == "hot"  # at_risk first
    assert port["me"]["name"] == "Dinesh"
    assert port["stats"]["needYouToday"] == 2


# ---- listing-agent surface ---------------------------------------------------

_LISTING_FIELDS = {
    "seller_names": "Karthik Anantharaman", "purchase_price": "$1,900,000",
    "down_payment": "$646,000", "financing_type": "Conventional",
    "close_of_escrow": "15 Days after Acceptance", "inspection_contingency_present": "false",
}


def test_listing_summary_active_surfaces_offers_and_dom():
    st = _state(tid="L1", stage="new", fields=_LISTING_FIELDS)
    s = listing_summary(st)
    assert s["status"] == "active"
    assert s["offerCount"] == 3 and s["daysOnMarket"] is not None  # on-market signal
    assert s["listPriceCents"] == 190_000_000


def test_listing_summary_in_escrow_uses_deadline_signal():
    st = _state(tid="L2", stage="cont", fields=_LISTING_FIELDS,
                deadlines=[{"id": "d", "name": "Loan contingency", "due_date": _iso(1)}])
    s = listing_summary(st)
    assert s["status"] == "in_escrow" and s["offerCount"] == 0
    assert s["nextDeadline"]["risk"] == "at_risk"


def test_listing_stats_counts():
    summaries = [listing_summary(s) for s in [
        _state(tid="a", stage="new", fields=_LISTING_FIELDS),
        _state(tid="b", stage="cont", fields=_LISTING_FIELDS),
        _state(tid="c", stage="closed", fields=_LISTING_FIELDS),
    ]]
    stats = listing_stats(summaries, pending_drafts=4)
    assert stats["liveListings"] == 2  # closed excluded
    assert stats["offersToReview"] == 1  # only the active one
    assert stats["inEscrow"] == 1
    assert stats["needYouToday"] == 4


def test_offer_comparison_is_neutral_and_labels_samples():
    st = _state(tid="L1", stage="new", fields=_LISTING_FIELDS)
    offers = build_offer_comparison(st)
    assert len(offers) == 3
    # the real accepted offer is not a synthesized sample; the alternatives are
    assert offers[0]["sample"] is False and all(o["sample"] for o in offers[1:])
    # every offer carries a neutral tradeoff tag; NONE is flagged as a winner
    assert all(o["tradeoffTag"] for o in offers)
    assert not any("winner" in str(o).lower() for o in offers)
    assert offers[0]["priceCents"] == 190_000_000


def test_offer_comparison_empty_without_price():
    st = _state(tid="L1", stage="new", fields={"seller_names": "S"})  # no purchase_price
    assert build_offer_comparison(st) == []


def test_build_listing_portfolio_surfaces_offer_listings_first():
    deals = [
        _state(tid="escrow", stage="cont", fields=_LISTING_FIELDS, deadlines=[{"id": "d", "name": "Loan", "due_date": _iso(30)}]),
        _state(tid="offers", stage="new", fields=_LISTING_FIELDS),
    ]
    port = build_listing_portfolio(deals=deals, me={"name": "Coco", "role": "listing_agent"}, pending_drafts=1)
    assert port["listings"][0]["id"] == "offers"  # offer listings float to the top
    assert port["stats"]["offersToReview"] == 1


# ---- buyer's-agent working views: schedule, earnings, client context ---------

from app.master.agent_portfolio import agent_earnings, agent_schedule, client_context  # noqa: E402


def test_agent_schedule_mixes_deadlines_and_tasks_sorted():
    st = _state(
        tid="d1", stage="cont", fields=_LISTING_FIELDS,
        deadlines=[{"id": "dl", "name": "Loan contingency", "due_date": _iso(2)}],
    )
    st["tasks"] = [
        {"id": "t1", "title": "Order inspection", "status": "pending", "due_date": _iso(1)},
        {"id": "t2", "title": "Done thing", "status": "done", "due_date": _iso(1)},
        {"id": "t3", "title": "Far thing", "status": "pending", "due_date": _iso(90)},
    ]
    items = agent_schedule([st])
    assert [i["id"] for i in items] == ["t1", "dl"]  # date order; done + beyond-horizon excluded
    assert items[0]["kind"] == "task" and items[1]["kind"] == "deadline"


def test_agent_earnings_estimates_and_totals():
    open_deal = _state(tid="a", stage="cont", fields={"buyer_names": "B", "purchase_price": "$1,000,000"},
                       deadlines=[{"id": "c", "name": "Close of escrow", "due_date": _iso(10)}])
    closed = _state(tid="b", stage="closed", fields={"buyer_names": "C", "purchase_price": "$400,000"})
    out = agent_earnings([open_deal, closed])
    row = next(r for r in out["rows"] if r["dealId"] == "a")
    assert row["commissionEstCents"] == 2_500_000  # 2.5% of $1M
    assert out["totals"]["inEscrowCents"] == 2_500_000
    assert out["totals"]["closingSoonCents"] == 2_500_000  # closes in 10 days
    assert out["totals"]["closedCents"] == 1_000_000  # 2.5% of $400k
    assert "estimate" in out["rateNote"]


def test_client_context_snapshot():
    st = _state(
        tid="d1", stage="cont",
        fields={"buyer_names": "B", "purchase_price": "$800,000",
                "inspection_contingency_present": "false", "loan_contingency_days": "21",
                "financing_type": "Conventional"},
        deadlines=[{"id": "n", "name": "Loan contingency", "due_date": _iso(3)}],
        audit=[{"id": "e1", "action": "compliance.run", "created_at": _iso(-1) + "T10:00:00Z"}],
    )
    st["documents"] = [{"id": "x", "doc_type": "proof_of_funds", "status": "uploaded"}]
    ctx = client_context(st)
    assert ctx["nextDeadline"]["label"] == "Loan contingency"
    conts = {c["kind"]: c["removed"] for c in ctx["contingencies"]}
    assert conts["inspection"] is True and conts["loan"] is False
    assert "proof_of_funds" in ctx["docTypes"]
    assert len(ctx["talkingPoints"]) == 1  # plain-English event feed
