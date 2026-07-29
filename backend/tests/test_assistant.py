"""Deal Q&A assistant: grounded context building + the /ask endpoint."""

from app.master.assistant import build_context


def test_build_context_includes_confirmed_fields_and_parties():
    state = {
        "property": {"address": "1057 Foxglove Pl"},
        "transaction": {"status": "open"},
        "extracted_fields": [
            {"name": "purchase_price", "value": "$1,200,000", "confirmed": True},
            {"name": "close_of_escrow", "value": "2026-08-11", "confirmed": True},
            {"name": "loan_amount", "value": "$900,000", "confirmed": False, "confidence": 0.6},
        ],
        "deadlines": [{"name": "Close of escrow", "due_date": "2026-08-11"}],
        "parties": [{"name": "Amarendra Verma", "role": "buyer", "email": "a@x.test"}],
        "documents": [{"doc_type": "purchase_agreement", "status": "confirmed"}],
        "tasks": [{"title": "Confirm loan approval", "status": "pending"}],
        "risk_flags": [{"severity": "warning", "description": "loan due soon", "resolved": False}],
    }
    ctx = build_context(state)
    assert "1057 Foxglove Pl" in ctx
    assert "purchase_price: $1,200,000" in ctx
    assert "NOT yet confirmed" in ctx and "loan_amount" in ctx  # unconfirmed flagged
    assert "Amarendra Verma" in ctx and "buyer" in ctx
    assert "Close of escrow: 2026-08-11" in ctx


def _deal_with_price(client, tc_headers) -> str:
    txn = client.post("/transactions", json={"property_address": "1 Ask St"}, headers=tc_headers).json()["id"]
    return txn


def test_ask_endpoint_answers_and_requires_auth(client, tc_headers):
    txn = _deal_with_price(client, tc_headers)
    r = client.post(f"/transactions/{txn}/ask", json={"question": "What is the property address?"}, headers=tc_headers)
    assert r.status_code == 200
    assert "Ask St" in r.json()["answer"]  # grounded in the deal (FakeAssistant)

    # a question the deal can't answer -> the honest not-found reply
    r2 = client.post(f"/transactions/{txn}/ask", json={"question": "What is the seller's dog's name?"}, headers=tc_headers)
    assert r2.status_code == 200 and "couldn't find" in r2.json()["answer"].lower()

    assert client.post(f"/transactions/{txn}/ask", json={"question": "x"}).status_code in (401, 403)


def test_ask_unknown_deal_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/ask",
        json={"question": "hello"}, headers=tc_headers,
    )
    assert r.status_code == 404
