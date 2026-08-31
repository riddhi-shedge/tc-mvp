"""Per-role party workspace personalization + field-visibility privacy (§8).

A party's view is tailored to their role, and — critically — a restricted role's
payload never even CONTAINS the fields they shouldn't see (a vendor never sees the
price). These unit-test the pure assembly in app/master/party_views.py.
"""

from __future__ import annotations

from app.master.party_views import archetype_for, build_party_workspace, sections_for


def _state(role: str) -> dict:
    return {
        "transaction": {"stage": "cont"},
        "property": {
            "address": "21989 McClellan Rd", "city": "Cupertino", "zip": "95014",
            "included_items": "refrigerator", "excluded_items": None,
        },
        "effective_fields": {
            "purchase_price": {"value": "$1,900,000"},
            "loan_amount": {"value": "$680,000"},
            "initial_deposit_amount": {"value": "$25,500"},
            "buyer_names": {"value": "Alex Buyer"},
            "seller_names": {"value": "Pat Seller"},
            "property_address": {"value": "21989 McClellan Rd"},
            "acceptance_date": {"value": "2026-07-10"},
            "inspection_contingency_days": {"value": "17"},
            "buyer_agent_email": {"value": "agent@example.test"},  # contact PII
            "buyer_agent_phone": {"value": "555-0100"},
        },
        "parties": [
            {"id": "me", "name": "Me", "role": role, "email": "me@example.test", "company": None},
            {"id": "p2", "name": "Pat Seller", "role": "seller"},
        ],
        "deadlines": [{"id": "d1", "name": "Close of escrow", "due_date": "2026-08-10"}],
        "tasks": [
            {"id": "t1", "title": "My task", "status": "pending", "assigned_party_id": "me"},
            {"id": "t2", "title": "Not mine", "status": "pending", "assigned_party_id": "p2"},
        ],
        "documents": [
            {"id": "doc1", "doc_type": "inspection_report", "status": "uploaded", "external_ref": "party:me"},
            {"id": "doc2", "doc_type": "disclosure", "status": "uploaded", "external_ref": "party:p2"},
        ],
    }


def _ws(role: str) -> dict:
    state = _state(role)
    me = next(p for p in state["parties"] if p["id"] == "me")
    return build_party_workspace(state=state, me=me, tier="receiving_end")


def test_archetype_mapping():
    assert archetype_for("inspector_termite") == "inspector"
    assert archetype_for("loan_officer") == "lender"
    assert archetype_for("buyer_agent") == "agent"
    assert archetype_for("something_new") == "default"


def test_sections_differ_by_role():
    assert sections_for("buyer") != sections_for("inspector")
    assert "money_milestones" in sections_for("buyer")
    assert "closing_summary" in sections_for("escrow")
    assert "loan_summary" in sections_for("lender")


def test_inspector_never_sees_financials():
    ws = _ws("inspector_termite")
    assert ws["archetype"] == "inspector"
    for hidden in ("purchase_price", "loan_amount", "initial_deposit_amount"):
        assert hidden not in ws["fields"], f"{hidden} leaked to an inspector"
    assert ws["fields"].get("property_address")  # but sees what it needs to find/access
    assert "property_card" in ws["sections"]


def test_escrow_sees_the_money_to_close():
    ws = _ws("escrow")
    assert ws["fields"].get("purchase_price") == "$1,900,000"
    assert ws["fields"].get("initial_deposit_amount") == "$25,500"
    assert "closing_summary" in ws["sections"]


def test_buyer_gets_the_home_view():
    ws = _ws("buyer")
    assert {"property_card", "money_milestones"} <= set(ws["sections"])
    assert ws["fields"].get("purchase_price")
    assert ws["property"]["address"] == "21989 McClellan Rd"


def test_lender_sees_loan_terms_and_price_not_everything():
    ws = _ws("loan_officer")
    assert ws["fields"].get("loan_amount") and ws["fields"].get("purchase_price")
    assert "seller_names" not in ws["fields"]  # not in the lender allowlist
    assert "loan_summary" in ws["sections"]


def test_contact_pii_never_leaks_to_any_party():
    ws = _ws("buyer_agent")  # a full-visibility (agent) role
    assert not any(k.endswith("_email") or k.endswith("_phone") for k in ws["fields"])
    assert all("email" not in p and "phone" not in p for p in ws["roster"])


def test_scoped_to_my_own_tasks_and_documents():
    ws = _ws("buyer")
    assert [t["id"] for t in ws["my_tasks"]] == ["t1"]
    assert [d["id"] for d in ws["my_documents"]] == ["doc1"]


def _buyer_state_rich() -> dict:
    st = _state("buyer")
    st["parties"].append({"id": "esc", "name": "CA Escrow Co", "role": "escrow", "phone": "555-0199"})
    st["audit_log"] = [
        {"id": "a1", "action": "payload.written", "created_at": "2026-07-10T10:00:00Z"},
        {"id": "a2", "action": "risk_flag.counter", "created_at": "2026-07-11T10:00:00Z"},  # internal
        {"id": "a3", "action": "compliance.run", "created_at": "2026-07-12T10:00:00Z"},
    ]
    return st


def test_buyer_gets_activity_deposit_and_callable_roster():
    st = _buyer_state_rich()
    me = next(p for p in st["parties"] if p["id"] == "me")
    ws = build_party_workspace(state=st, me=me, tier="email_participant")

    texts = [e["text"] for e in ws["activity"]]
    assert "Your timeline was updated" in texts and "A new document was added to your deal" in texts
    assert all("risk" not in t.lower() for t in texts)  # internal events never surface

    assert ws["deposit"]["amount"] == "$25,500"
    assert ws["deposit"]["payee"] == "CA Escrow Co"
    assert ws["deposit"]["escrowContactId"] == "esc"
    assert ws["deposit"]["verifiedByBuyer"] is False

    esc = next(p for p in ws["roster"] if p["role"] == "escrow")
    assert esc.get("phone") == "555-0199" and esc.get("id") == "esc"  # escrow phone exposed to buyer
    seller = next(p for p in ws["roster"] if p["role"] == "seller")
    assert "phone" not in seller  # seller-side contact stays private


def test_buyer_deposit_reflects_verification():
    st = _buyer_state_rich()
    st["audit_log"].append(
        {"id": "a4", "action": "party.deposit_verified", "created_at": "2026-07-13T10:00:00Z", "details": {"party_id": "me"}}
    )
    me = next(p for p in st["parties"] if p["id"] == "me")
    ws = build_party_workspace(state=st, me=me, tier="email_participant")
    assert ws["deposit"]["verifiedByBuyer"] is True


def test_non_buyer_has_no_activity_or_deposit_block():
    st = _buyer_state_rich()
    me = next(p for p in st["parties"] if p["id"] == "me")
    me = {**me, "role": "escrow"}  # same person as an escrow archetype
    ws = build_party_workspace(state=st, me=me, tier="email_participant")
    assert "activity" not in ws and "deposit" not in ws


def _seller_state_rich() -> dict:
    st = _state("seller")
    st["parties"].append({"id": "la", "name": "Coco Tan", "role": "listing_agent", "phone": "555-0100"})
    st["parties"].append({"id": "esc", "name": "CA Escrow", "role": "escrow"})
    st["audit_log"] = [{"id": "a1", "action": "payload.written", "created_at": "2026-07-10T10:00:00Z"}]
    return st


def test_seller_gets_deal_health_disclosures_and_net_sheet():
    st = _seller_state_rich()
    me = next(p for p in st["parties"] if p["id"] == "me")
    ws = build_party_workspace(state=st, me=me, tier="email_participant")

    assert ws["dealHealth"]["meter"] in {"on_track", "watch", "at_risk"}
    assert ws["dealHealth"]["milestones"]  # buyer-side milestones
    assert all(m["actionableBySeller"] is False for m in ws["dealHealth"]["milestones"])  # read-only

    kinds = {d["kind"] for d in ws["disclosures"]}
    assert {"tds", "spq", "nhd"} <= kinds
    assert all(d["state"] == "draft" for d in ws["disclosures"])  # nothing attested yet

    sale = next(row["amountCents"] for row in ws["netSheet"]["lines"] if row["label"] == "Sale price")
    assert ws["netSheet"]["estimatedNetProceedsCents"] == sale - round(sale * 0.05) - round(sale * 0.012)
    assert ws["netSheet"]["disbursementVerified"] is False
    assert ws["netSheet"]["beforeMortgagePayoff"] is True

    la = next(p for p in ws["roster"] if p["role"] == "listing_agent")
    assert la.get("phone") == "555-0100"  # seller can call their listing agent
    esc = next(p for p in ws["roster"] if p["role"] == "escrow")
    assert "phone" not in esc  # no number on file → not fabricated
    assert len(ws["activity"]) >= 1 and ws["requests"] == []


def test_seller_disclosure_and_disbursement_attestations_read_back():
    st = _seller_state_rich()
    me = next(p for p in st["parties"] if p["id"] == "me")
    st["audit_log"] += [
        {"id": "a2", "action": "party.disclosure_attested", "created_at": "2026-07-12T10:00:00Z", "details": {"party_id": "me", "kind": "spq"}},
        {"id": "a3", "action": "party.disbursement_verified", "created_at": "2026-07-13T10:00:00Z", "details": {"party_id": "me"}},
    ]
    ws = build_party_workspace(state=st, me=me, tier="email_participant")
    spq = next(d for d in ws["disclosures"] if d["kind"] == "spq")
    assert spq["state"] == "delivered"
    tds = next(d for d in ws["disclosures"] if d["kind"] == "tds")
    assert tds["state"] == "draft"  # only the attested one flips
    assert ws["netSheet"]["disbursementVerified"] is True


def test_buyer_has_no_seller_sections():
    st = _seller_state_rich()
    me = {**next(p for p in st["parties"] if p["id"] == "me"), "role": "buyer"}
    ws = build_party_workspace(state=st, me=me, tier="email_participant")
    assert "dealHealth" not in ws and "disclosures" not in ws and "netSheet" not in ws


def test_unknown_role_falls_back_to_default_view():
    ws = _ws("home_warranty")
    assert ws["archetype"] == "default"
    assert "purchase_price" not in ws["fields"]  # default is a restricted allowlist
    assert ws["sections"] == sections_for("default")


def test_embed_links_gated_on_key_and_address(monkeypatch):
    from app.enrichment import property_data

    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert property_data.embed_links("1 Main St, Fresno, CA") == {}  # no key -> hidden
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "synthetic-key")
    assert property_data.embed_links(None) == {}  # no address -> hidden

    # pano resolved -> streetview embeds by pano id (addresses are rejected by
    # the Embed API's streetview mode); no network in tests.
    monkeypatch.setattr(property_data, "_street_pano", lambda a: ("PANO123", 36.7, -119.8))
    out = property_data.embed_links("1 Main St, Fresno, CA")
    assert set(out) == {"street", "map"}
    assert "pano=PANO123" in out["street"] and "synthetic-key" in out["street"]
    assert "maptype=satellite" in out["map"]

    # no panorama at the address -> map still ships, street is omitted
    monkeypatch.setattr(property_data, "_street_pano", lambda a: (None, None, None))
    assert set(property_data.embed_links("1 Main St, Fresno, CA")) == {"map"}
