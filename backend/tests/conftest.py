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
from app.master.routes import get_drafter, get_mailer, get_party_access_issuer, get_repo
from tests.fake_extractor import FakeExtractor
from tests.fake_inbox import FakeMasterClient, InMemoryInboxRepo
from tests.fake_mailer import FakeDrafter, FakeMailer, FakePartyAccessIssuer
from tests.fake_repo import InMemoryRepo

TEST_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
WEBHOOK_TOKEN = os.environ["POSTMARK_WEBHOOK_TOKEN"]
DEAL_ADDRESS = os.environ["POSTMARK_INBOUND_ADDRESS"]

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
def client(
    repo: InMemoryRepo,
    inbox: InMemoryInboxRepo,
    extractor: FakeExtractor,
    mailer: FakeMailer,
    drafter: FakeDrafter,
    party_access_issuer: FakePartyAccessIssuer,
):
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_inbox_repo] = lambda: inbox
    app.dependency_overrides[get_master_client] = lambda: FakeMasterClient(repo)
    app.dependency_overrides[get_extractor] = lambda: extractor
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_drafter] = lambda: drafter
    app.dependency_overrides[get_party_access_issuer] = lambda: party_access_issuer
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def tc_headers() -> dict[str, str]:
    """Authorization header for a synthetic TC who has completed MFA (aal2)."""
    return {"Authorization": f"Bearer {make_token()}"}
