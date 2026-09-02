"""Wave 3B: the weekly status ritual — one role-aware draft per key party,
all landing in the approval queue (Rule 3: drafts only)."""


def test_weekly_status_drafts_per_party_and_reports_skips(client, tc_headers, repo):
    txn_id = client.post(
        "/transactions", json={"property_address": "6 Ritual Rd"}, headers=tc_headers
    ).json()["id"]
    b = repo.add_party(transaction_id=txn_id, name="Bay Buyer", role="buyer")
    b["email"] = "buyer@example.test"
    repo.add_party(transaction_id=txn_id, name="Sal Seller", role="seller")  # no email
    a = repo.add_party(transaction_id=txn_id, name="Ana Agent", role="buyer_agent")
    a["email"] = "agent@example.test"

    r = client.post(f"/transactions/{txn_id}/status-updates", headers=tc_headers)
    assert r.status_code == 201
    body = r.json()
    assert {d["role"] for d in body["drafted"]} == {"buyer", "buyer_agent"}
    assert body["skipped"] == [{"name": "Sal Seller", "role": "seller", "reason": "no email"}]

    state = repo.get_full_state(txn_id)
    drafts = [m for m in state["messages"] if m["status"] == "draft"]
    assert len(drafts) == 2  # drafts await Approve & Send — nothing sent
