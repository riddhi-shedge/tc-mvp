"""HTTP client the compliance runner uses to reach the master API (part c → b).

Reads the confirmed deal slice and writes the computed ComplianceResult back —
never touches the master's tables. Both calls authenticate with
COMPLIANCE_SERVICE_TOKEN (a scheduled machine can't do MFA), so the runner has
only compliance-scoped access, never full TC privileges.
"""

from __future__ import annotations

import os

import httpx

from app.contracts.compliance import (
    ComplianceResult,
    DealDocState,
    DealFieldState,
    DealPartyState,
    DealState,
    DealTaskState,
)

_TIMEOUT = 30.0


class ComplianceMasterError(Exception):
    """The master API could not be reached or returned an error. Generic
    message — no deal content (Rule 5)."""


class HttpComplianceMasterClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self._base = (
            base_url or os.environ.get("MASTER_API_BASE", "http://localhost:8000")
        ).rstrip("/")
        self._token = token or os.environ.get("COMPLIANCE_SERVICE_TOKEN", "")

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Compliance-Token": self._token}

    def read_deal_state(self, transaction_id: str) -> DealState | None:
        try:
            r = httpx.get(
                f"{self._base}/transactions/{transaction_id}/compliance-state",
                headers=self._headers,
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ComplianceMasterError(f"master API unreachable ({type(exc).__name__})") from exc
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise ComplianceMasterError(f"master read failed (HTTP {r.status_code})")
        return _state_from_slice(r.json())

    def write_compliance_result(self, result: ComplianceResult) -> None:
        try:
            r = httpx.post(
                f"{self._base}/transactions/{result.transaction_id}/compliance-result",
                json=result.model_dump(mode="json"),
                headers=self._headers,
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ComplianceMasterError(f"master API unreachable ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            raise ComplianceMasterError(f"master write failed (HTTP {r.status_code})")

    def list_active_transactions(self) -> list[str]:
        try:
            r = httpx.get(
                f"{self._base}/transactions/compliance-active",
                headers=self._headers,
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ComplianceMasterError(f"master API unreachable ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            raise ComplianceMasterError(f"master list failed (HTTP {r.status_code})")
        return list(r.json().get("transaction_ids", []))


def _state_from_slice(slice_: dict) -> DealState:
    """Map the compliance-state slice onto the DealState boundary."""
    return DealState(
        transaction_id=slice_["transaction_id"],
        fields=[DealFieldState(**f) for f in slice_.get("fields", [])],
        parties=[DealPartyState(**p) for p in slice_.get("parties", [])],
        documents=[DealDocState(**d) for d in slice_.get("documents", [])],
        tasks=[DealTaskState(**t) for t in slice_.get("tasks", [])],
    )
