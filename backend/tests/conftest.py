"""Shared fixtures for Phase 1 (SOR core) tests. Synthetic data only.

The API is tested against an in-memory fake of the repository interface so the
master's logic is exercised in isolation (rules/testing.md). DB-integration
tests live in test_db_integration.py and skip unless Supabase env is present.
"""

from __future__ import annotations

import os
import time

# Set BEFORE the app is imported so auth has a (synthetic) secret to verify with.
os.environ.setdefault(
    "SUPABASE_JWT_SECRET", "synthetic-test-secret-not-a-real-key-0123456789abcdef"
)

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.master.routes import get_repo
from tests.fake_repo import InMemoryRepo

TEST_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]


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


@pytest.fixture()
def repo() -> InMemoryRepo:
    return InMemoryRepo()


@pytest.fixture()
def client(repo: InMemoryRepo):
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_repo, None)


@pytest.fixture()
def tc_headers() -> dict[str, str]:
    """Authorization header for a synthetic TC who has completed MFA (aal2)."""
    return {"Authorization": f"Bearer {make_token()}"}
