"""Trivial hardcoded timeline (Prompt 2). Clearly a stub — real CA rules are
Phase 5 and come only from ca-rules-researcher + human verification."""


def _txn(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "742 Synthetic Ave"}, headers=tc_headers
    ).json()["id"]


def test_stub_timeline_creates_deadlines_and_tasks(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    r = client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers)
    assert r.status_code == 201
    state = client.get(f"/transactions/{txn_id}", headers=tc_headers).json()
    assert len(state["deadlines"]) == 3
    assert len(state["tasks"]) == 3
    # Every stub item is labeled as such — nobody mistakes this for CA rules.
    assert all("(stub)" in d["name"] for d in state["deadlines"])
    assert all("(stub)" in t["title"] for t in state["tasks"])


def test_stub_timeline_writes_audit_row(client, tc_headers, repo):
    txn_id = _txn(client, tc_headers)
    client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers)
    assert any(a["action"] == "timeline.stub_generated" for a in repo.audit_log)


def test_stub_timeline_twice_is_409(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    assert (
        client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers).status_code == 201
    )
    assert (
        client.post(f"/transactions/{txn_id}/timeline/stub", headers=tc_headers).status_code == 409
    )


def test_stub_timeline_unknown_transaction_is_404(client, tc_headers):
    r = client.post(
        "/transactions/00000000-0000-0000-0000-000000000000/timeline/stub",
        headers=tc_headers,
    )
    assert r.status_code == 404


def test_stub_timeline_requires_auth(client, tc_headers):
    txn_id = _txn(client, tc_headers)
    assert client.post(f"/transactions/{txn_id}/timeline/stub").status_code == 401
