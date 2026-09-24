"""Tenancy conformance: no TC route may leak across orgs.

This test walks the ENTIRE FastAPI route table and forces every route into a
known bucket:

  * TC routes naming a {transaction_id} — attacked: org B calls them against an
    org-A deal and must get 404 (existence is never confirmed cross-org).
  * TC inbox routes naming an {item_id} — attacked the same way.
  * TC routes with no resource in the path — must appear in EXPECTED_GLOBAL_TC,
    each verified org-scoped by the list-emptiness assertions below.
  * Party/agent routes — skipped: the credential itself binds one party to one
    deal (require_party), and the portfolio aggregates only the home deal's org.
  * Service/public endpoints — must appear in EXPECTED_UNSCOPED exactly.

Any route that fits no bucket FAILS this test. That is the point: a new
endpoint added without tenancy classification breaks CI until it is scoped
(use require_scoped_tc / an org guard) or explicitly listed here.
"""

from __future__ import annotations

import uuid

from fastapi.routing import APIRoute

from app.common.auth import (
    require_agent_portfolio,
    require_party,
    require_tc,
    require_tc_candidate,
)
from app.main import app
from app.master.routes import require_compliance_service, require_scoped_tc
from tests.conftest import ORG_B_SUB, SYNTHETIC_PA_B64, make_token

# TC-authenticated routes with no {transaction_id}/{item_id} in the path. Each
# is org-scoped inside its handler (org comes from the token, never the client):
EXPECTED_GLOBAL_TC = {
    ("POST", "/transactions"),               # stamps tc.org_id on the new deal
    ("GET", "/transactions"),                # list_transactions(org_id=...)
    ("GET", "/transactions/board"),          # list_deal_summaries(org_id=...)
    ("GET", "/transactions/calendar"),       # list_active_deadlines(org_id=...)
    ("GET", "/transactions/tasks"),          # list_open_tasks(org_id=...)
    ("GET", "/transactions/attention"),      # list_full_states(org_id=...)
    ("GET", "/transactions/calendar/feed-url"),  # org-derived HMAC key
    ("POST", "/ingestion/manual-upload"),    # stamps tc.org_id on the item
    ("GET", "/ingestion/inbox"),             # list_open(org_id=...)
    ("GET", "/orgs/me"),                     # everything keyed by tc.org_id
    ("POST", "/orgs/members/invites"),       # owner-only; invite in tc.org_id
    ("POST", "/orgs/members/invites/{invite_id}/revoke"),  # repo eq(org_id)
    ("DELETE", "/orgs/members/{user_id}"),   # remove within tc.org_id only
    ("PATCH", "/orgs/settings"),             # upsert keyed by tc.org_id
}

# Onboarding routes: a verified MFA'd session with NO org yet. Both write only
# memberships for the caller themself (org creation / invite acceptance).
EXPECTED_CANDIDATE = {
    ("POST", "/orgs"),
    ("POST", "/orgs/members/accept"),
}

# No TC auth by design: public, token-gated, or service-token endpoints.
EXPECTED_UNSCOPED = {
    ("GET", "/health"),
    ("GET", "/orgs/config"),                  # public: signup mode only
    ("GET", "/calendar.ics"),                 # org-derived HMAC key in the URL
    ("POST", "/ingestion/webhooks/postmark"),  # webhook token; org from address
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}

# Bodies for attacked POST routes whose Pydantic model has required fields —
# without a valid body those could 422 in the same solve pass and mask the 404.
ATTACK_BODIES = {
    "/ingestion/inbox/{item_id}/confirm": {"decision": "new"},
}


def _all_api_routes(routes) -> list[APIRoute]:
    """Flatten the route table: this FastAPI version keeps included routers
    nested (_IncludedRouter), so walk .routes recursively."""
    out: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            out.append(route)
        elif hasattr(route, "original_router"):  # fastapi _IncludedRouter
            out.extend(_all_api_routes(route.original_router.routes))
        elif hasattr(route, "routes"):
            out.extend(_all_api_routes(route.routes))
    return out


def _dependency_calls(route: APIRoute) -> set:
    calls: set = set()

    def walk(dep) -> None:
        if dep.call is not None:
            calls.add(dep.call)
        for sub in dep.dependencies:
            walk(sub)

    walk(route.dependant)
    return calls


def _fill_path(path: str, transaction_id: str, item_id: str) -> str:
    out = path.replace("{transaction_id}", transaction_id).replace("{item_id}", item_id)
    while "{" in out:  # any other params: a random uuid (the org guard fires first)
        start, end = out.index("{"), out.index("}")
        out = out[:start] + str(uuid.uuid4()) + out[end + 1 :]
    return out


def _headers(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


def test_every_route_is_tenancy_classified_and_cross_org_reads_404(client):
    headers_a = _headers()
    headers_b = _headers(sub=ORG_B_SUB, email="tc-b@example.test")

    # Seed org A: one deal, one inbox item.
    txn_a = client.post(
        "/transactions", json={"property_address": "1 Tenant St, Ana"}, headers=headers_a
    ).json()["id"]
    item_a = client.post(
        "/ingestion/manual-upload",
        json={"filename": "tenancy.pdf", "content_base64": SYNTHETIC_PA_B64},
        headers=headers_a,
    ).json()["id"]

    unclassified: list[str] = []
    attacked = 0

    routes = _all_api_routes(app.routes)
    assert len(routes) > 60, f"route flattening looks broken: {len(routes)} routes"
    for route in routes:
        methods = sorted(route.methods - {"HEAD", "OPTIONS"})
        calls = _dependency_calls(route)
        is_tc = require_scoped_tc in calls or require_tc in calls
        is_candidate = require_tc_candidate in calls
        is_party = require_party in calls or require_agent_portfolio in calls
        is_service = require_compliance_service in calls

        for method in methods:
            key = (method, route.path)
            if is_party:
                continue  # credential-bound to one deal (and its org) by construction
            if is_candidate:
                if key not in EXPECTED_CANDIDATE:
                    unclassified.append(
                        f"{method} {route.path}: candidate-auth route — verify it only "
                        "writes the caller's own membership, then add to EXPECTED_CANDIDATE"
                    )
                continue
            if is_service or key in EXPECTED_UNSCOPED:
                if is_tc:
                    unclassified.append(f"{method} {route.path}: both TC-authed and unscoped?")
                continue
            if not is_tc:
                unclassified.append(
                    f"{method} {route.path}: no recognized auth — classify it in test_tenancy.py"
                )
                continue

            has_txn = "{transaction_id}" in route.path
            has_item = "{item_id}" in route.path
            if not has_txn and not has_item:
                if key not in EXPECTED_GLOBAL_TC:
                    unclassified.append(
                        f"{method} {route.path}: TC route with no resource param — "
                        "verify its org scoping and add it to EXPECTED_GLOBAL_TC"
                    )
                continue

            # The attack: org B hits org A's resource and must see a 404.
            url = _fill_path(route.path, txn_a, item_a)
            body = ATTACK_BODIES.get(route.path, {})
            response = client.request(method, url, headers=headers_b, json=body)
            assert response.status_code == 404, (
                f"TENANT LEAK: {method} {route.path} returned "
                f"{response.status_code} for a cross-org caller: {response.text[:300]}"
            )
            attacked += 1

    assert not unclassified, "\n".join(unclassified)
    assert attacked >= 40, f"route walk looks broken: only {attacked} routes attacked"

    # Global TC reads: org B sees an EMPTY book, not org A's.
    assert client.get("/transactions", headers=headers_b).json() == []
    assert client.get("/transactions/board", headers=headers_b).json() == []
    assert client.get("/transactions/calendar", headers=headers_b).json() == []
    assert client.get("/transactions/tasks", headers=headers_b).json() == []
    assert client.get("/ingestion/inbox", headers=headers_b).json() == []
    attention_b = client.get("/transactions/attention", headers=headers_b)
    assert attention_b.status_code == 200
    assert all(not v for v in attention_b.json().values() if isinstance(v, list))

    # Positive control: org A still reaches its own deal (the guard is a tenancy
    # check, not a wall), and org A's inbox still lists its item.
    assert client.get(f"/transactions/{txn_a}/notes", headers=headers_a).status_code == 200
    assert any(
        i["id"] == item_a for i in client.get("/ingestion/inbox", headers=headers_a).json()
    )


def test_membershipless_user_is_rejected(client, org_directory):
    """An authenticated Supabase session with NO org membership gets 403 —
    a stranger who somehow obtains an account in the auth project sees nothing."""
    original = org_directory.membership
    org_directory.membership = lambda user_id: None
    try:
        from app.common import orgs as orgs_module

        orgs_module.set_directory(org_directory)  # clear the membership cache
        r = client.get("/transactions", headers=_headers(sub="stranger-1"))
        assert r.status_code == 403
        assert "organization" in r.json()["detail"].lower()
    finally:
        org_directory.membership = original
        from app.common import orgs as orgs_module

        orgs_module.set_directory(org_directory)


def test_second_org_lives_alongside_the_first(client):
    """Two orgs in one deployment: each sees exactly its own deals."""
    headers_a = _headers()
    headers_b = _headers(sub=ORG_B_SUB, email="tc-b@example.test")
    a_txn = client.post(
        "/transactions", json={"property_address": "2 Alpha Ave, Ana"}, headers=headers_a
    ).json()["id"]
    b_txn = client.post(
        "/transactions", json={"property_address": "3 Beta Blvd, Bakersfield"}, headers=headers_b
    ).json()["id"]

    a_ids = {t["id"] for t in client.get("/transactions", headers=headers_a).json()}
    b_ids = {t["id"] for t in client.get("/transactions", headers=headers_b).json()}
    assert a_txn in a_ids and b_txn not in a_ids
    assert b_txn in b_ids and a_txn not in b_ids

    # And the cross-org 404 in both directions, for good measure.
    assert client.get(f"/transactions/{b_txn}/notes", headers=headers_a).status_code == 404
    assert client.get(f"/transactions/{a_txn}/notes", headers=headers_b).status_code == 404
