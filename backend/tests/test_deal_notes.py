"""P3 — the TC's notes live in the SOR: CRUD on the TC API, audited without
content (Rule 5), fed to the assistant's context, and never served to parties."""


def _txn(client, tc_headers) -> str:
    return client.post(
        "/transactions", json={"property_address": "3 Note Ln"}, headers=tc_headers
    ).json()["id"]


def test_notes_crud_and_content_free_audit(client, tc_headers, repo):
    txn = _txn(client, tc_headers)
    r = client.post(f"/transactions/{txn}/notes", json={"body": "Seller wants a rent-back", "color": "b"}, headers=tc_headers)
    assert r.status_code == 201
    note = r.json()

    listed = client.get(f"/transactions/{txn}/notes", headers=tc_headers).json()
    assert listed["available"] is True
    assert [n["body"] for n in listed["notes"]] == ["Seller wants a rent-back"]

    # audited as an event, never the content (Rule-5 logging discipline)
    audit = [a for a in repo.audit_log if a["action"] == "note.added"]
    assert len(audit) == 1 and "rent-back" not in str(audit[0].get("details"))

    assert client.delete(f"/transactions/{txn}/notes/{note['id']}", headers=tc_headers).status_code == 200
    assert client.get(f"/transactions/{txn}/notes", headers=tc_headers).json()["notes"] == []
    assert client.delete(f"/transactions/{txn}/notes/{note['id']}", headers=tc_headers).status_code == 404


def test_notes_join_assistant_context(client, tc_headers, repo):
    from app.master.assistant import build_context

    txn = _txn(client, tc_headers)
    client.post(f"/transactions/{txn}/notes", json={"body": "Buyer prefers e-sign only"}, headers=tc_headers)
    state = repo.get_full_state(txn)
    state["deal_notes"] = repo.list_deal_notes(txn) or []
    ctx = build_context(state)
    assert "TC'S OWN NOTES" in ctx and "Buyer prefers e-sign only" in ctx


def test_notes_never_reach_a_party_workspace(client, tc_headers):
    import time

    import jwt

    from tests.conftest import TEST_JWT_SECRET

    txn = _txn(client, tc_headers)
    pid = client.post(
        f"/transactions/{txn}/parties",
        json={"name": "Basant Somani", "role": "buyer_agent", "email": "a@ex.test"},
        headers=tc_headers,
    ).json()["id"]
    client.post(f"/transactions/{txn}/notes", json={"body": "PRIVATE: seller is motivated"}, headers=tc_headers)

    now = int(time.time())
    tok = jwt.encode(
        {"sub": f"party-{pid}", "role": "authenticated", "aud": "authenticated", "aal": "aal1",
         "iat": now, "exp": now + 3600,
         "app_metadata": {"party_id": pid, "transaction_id": txn, "tier": "collaborator"}},
        TEST_JWT_SECRET, algorithm="HS256",
    )
    ws = client.get("/party/workspace", headers={"Authorization": f"Bearer {tok}"})
    assert ws.status_code == 200
    assert "PRIVATE: seller is motivated" not in ws.text  # notes never leave the TC API

    # and the party token can't hit the notes endpoint itself
    denied = client.get(f"/transactions/{txn}/notes", headers={"Authorization": f"Bearer {tok}"})
    assert denied.status_code in (401, 403)
