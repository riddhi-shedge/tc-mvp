"""Ingestion's client to the master API — the ONLY way part (a) reaches the SOR.

Talks HTTP with the TC's own bearer token forwarded, so the master's auth and
HITL semantics hold: ingestion has no credentials of its own and never imports
master internals (rules/architecture.md)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.contracts.payload import Payload

_TIMEOUT = 30.0


class HttpMasterClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base = (
            base_url or os.environ.get("MASTER_API_BASE", "http://localhost:8000")
        ).rstrip("/")

    def _request(
        self, method: str, path: str, *, token: str, json: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        try:
            r = httpx.request(
                method,
                f"{self._base}{path}",
                json=json,
                headers={"Authorization": f"Bearer {token}"},
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            # Network-level failure to reach the master — no NPI in this message.
            return 502, {"detail": f"master API unreachable ({type(exc).__name__})"}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"detail": f"master API returned non-JSON ({r.status_code})"}

    def list_transactions(self, *, token: str) -> tuple[int, Any]:
        return self._request("GET", "/transactions", token=token)

    def create_transaction(
        self, *, token: str, property_address: str
    ) -> tuple[int, dict[str, Any]]:
        return self._request(
            "POST", "/transactions", token=token, json={"property_address": property_address}
        )

    def write_payload(
        self, *, token: str, transaction_id: str, payload: Payload
    ) -> tuple[int, dict[str, Any]]:
        return self._request(
            "POST",
            f"/transactions/{transaction_id}/payloads",
            token=token,
            json=payload.model_dump(),
        )
