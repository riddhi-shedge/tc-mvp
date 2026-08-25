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


def test_unknown_role_falls_back_to_default_view():
    ws = _ws("home_warranty")
    assert ws["archetype"] == "default"
    assert "purchase_price" not in ws["fields"]  # default is a restricted allowlist
    assert ws["sections"] == sections_for("default")
