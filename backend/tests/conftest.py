"""Shared fixtures for Phase 1+2 tests. Synthetic data only.

The API is tested against in-memory fakes of the repository interfaces so each
part is exercised in isolation (rules/testing.md). Ingestion talks to a fake
master client (the real one calls the master's HTTP API). DB-integration tests
live in test_db_integration.py and skip unless Supabase env is present.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

# Set BEFORE the app is imported so auth/webhook/extractor have synthetic config.
os.environ.setdefault(
    "SUPABASE_JWT_SECRET", "synthetic-test-secret-not-a-real-key-0123456789abcdef"
)
os.environ.setdefault("POSTMARK_WEBHOOK_TOKEN", "synthetic-webhook-token")
os.environ.setdefault("POSTMARK_INBOUND_ADDRESS", "deal-synthetic@inbound.example.test")
os.environ.setdefault("SYNTHETIC_ONLY", "true")  # ZDR gate: synthetic-only dev mode

import jwt
import pytest
from fastapi.testclient import TestClient

from app.ingestion.routes import get_extractor, get_inbox_repo, get_master_client
from app.main import app
from app.master.routes import (
    get_assistant,
    get_drafter,
    get_mailer,
    get_party_access_issuer,
    get_repo,
)
from app.master.org_routes import get_mfa_admin, get_orgs_repo
from tests.fake_extractor import FakeExtractor
from tests.fake_inbox import FakeMasterClient, InMemoryInboxRepo
from tests.fake_mailer import (
    FakeAssistant,
    FakeDrafter,
    FakeMailer,
    FakeMfaAdmin,
    FakePartyAccessIssuer,
)
from tests.fake_orgs import InMemoryOrgsRepo
from tests.fake_repo import TEST_ORG_B_ID, TEST_ORG_ID, InMemoryRepo

TEST_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
WEBHOOK_TOKEN = os.environ["POSTMARK_WEBHOOK_TOKEN"]
DEAL_ADDRESS = os.environ["POSTMARK_INBOUND_ADDRESS"]

# Tenancy: the in-memory org directory require_tc resolves memberships from.
# Default user(s) belong to org A; the dedicated "tc-user-b" sub belongs to
# org B so tests can act as a second, unrelated TC business.
ORG_B_SUB = "tc-user-b"


class FakeOrgDirectory:
    """Membership defaults: any sub belongs to org A (org B for ORG_B_SUB) so
    the legacy suite runs as one TC business — EXCEPT subs starting with
    'cand-', which have no membership (onboarding tests). Explicit memberships
    written through the fake OrgsRepo always win over the defaults."""

    def __init__(self, orgs_repo: InMemoryOrgsRepo | None = None) -> None:
        self.orgs_repo = orgs_repo

    def membership(self, user_id: str) -> dict | None:
        if self.orgs_repo is not None:
            explicit = self.orgs_repo.membership_of(user_id)
            if explicit is not None:
                return explicit
        if user_id.startswith("cand-"):
            return None
        if user_id == ORG_B_SUB:
            return {"org_id": TEST_ORG_B_ID, "role": "owner"}
        return {"org_id": TEST_ORG_ID, "role": "owner"}

    def org_for_inbound_key(self, key: str) -> str | None:
        return {"terra": TEST_ORG_ID, "org-b": TEST_ORG_B_ID}.get(key)

    def sole_org_id(self) -> str | None:
        return TEST_ORG_ID


@pytest.fixture()
def orgs_repo() -> InMemoryOrgsRepo:
    return InMemoryOrgsRepo()


@pytest.fixture()
def mfa_admin() -> FakeMfaAdmin:
    return FakeMfaAdmin()


@pytest.fixture(autouse=True)
def org_directory(orgs_repo: InMemoryOrgsRepo):
    """Every test runs with the fake org directory installed (and the membership
    cache cleared on both sides), so require_tc resolves synthetic orgs and the
    webhook can route untagged mail to org A."""
    from app.common import orgs as orgs_module

    directory = FakeOrgDirectory(orgs_repo)
    orgs_module.set_directory(directory)
    yield directory
    orgs_module.set_directory(None)

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC_PA_BYTES = (FIXTURES / "synthetic_pa_signed.pdf").read_bytes()
SYNTHETIC_PA_B64 = base64.standard_b64encode(SYNTHETIC_PA_BYTES).decode()


def make_token(
    *,
    sub: str = "tc-user-1",
    email: str = "tc@example.test",
    role: str = "authenticated",
    aal: str = "aal2",
    secret: str = TEST_JWT_SECRET,
    expires_in: int = 3600,
    user_metadata: dict | None = None,
) -> str:
    """Mint a synthetic Supabase-shaped JWT for tests."""
    now = int(time.time())
    claims = {
        "sub": sub,
        "email": email,
        "role": role,
        "aal": aal,
        "aud": "authenticated",
        "iat": now,
        "exp": now + expires_in,
    }
    if user_metadata is not None:
        claims["user_metadata"] = user_metadata
    return jwt.encode(claims, secret, algorithm="HS256")


def postmark_inbound(
    *,
    to: str = DEAL_ADDRESS,
    subject: str = "Signed RPA — 123 Stub St (synthetic)",
    attachment_name: str = "synthetic-signed-rpa.pdf",
) -> dict:
    """A synthetic Postmark inbound-webhook body. Never real content."""
    return {
        "From": "listing-agent@example.test",
        "FromFull": {"Email": "listing-agent@example.test", "Name": "Synthetic Agent"},
        "To": to,
        "ToFull": [{"Email": to, "Name": ""}],
        "OriginalRecipient": to,
        "Subject": subject,
        "Attachments": [
            {
                "Name": attachment_name,
                "ContentType": "application/pdf",
                "ContentLength": len(SYNTHETIC_PA_BYTES),
                # A real (but synthetic-content) PDF: the Phase 4 pre-check and
                # extraction paths parse it. Stored ONLY in the (fake) private
                # bucket, never on the inbox row or in logs.
                "Content": SYNTHETIC_PA_B64,
            }
        ],
    }


@pytest.fixture()
def repo() -> InMemoryRepo:
    return InMemoryRepo()


@pytest.fixture()
def inbox() -> InMemoryInboxRepo:
    return InMemoryInboxRepo()


@pytest.fixture()
def extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture()
def mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture()
def drafter() -> FakeDrafter:
    return FakeDrafter()


@pytest.fixture()
def party_access_issuer() -> FakePartyAccessIssuer:
    return FakePartyAccessIssuer()


@pytest.fixture()
def assistant() -> FakeAssistant:
    return FakeAssistant()


@pytest.fixture()
def client(
    repo: InMemoryRepo,
    inbox: InMemoryInboxRepo,
    extractor: FakeExtractor,
    mailer: FakeMailer,
    drafter: FakeDrafter,
    party_access_issuer: FakePartyAccessIssuer,
    assistant: FakeAssistant,
    orgs_repo: InMemoryOrgsRepo,
    mfa_admin: FakeMfaAdmin,
):
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_orgs_repo] = lambda: orgs_repo
    app.dependency_overrides[get_mfa_admin] = lambda: mfa_admin
    # permanent invite tokens (pi_…) resolve against the fake's invite store
    from app.common.auth import set_invite_resolver

    set_invite_resolver(repo.resolve_party_invite)
    app.dependency_overrides[get_inbox_repo] = lambda: inbox
    app.dependency_overrides[get_master_client] = lambda: FakeMasterClient(repo)
    app.dependency_overrides[get_extractor] = lambda: extractor
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_drafter] = lambda: drafter
    app.dependency_overrides[get_party_access_issuer] = lambda: party_access_issuer
    app.dependency_overrides[get_assistant] = lambda: assistant
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def tc_headers() -> dict[str, str]:
    """Authorization header for a synthetic TC who has completed MFA (aal2)."""
    return {"Authorization": f"Bearer {make_token()}"}
