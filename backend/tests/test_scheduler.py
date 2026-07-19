"""The compliance scheduler sweeps every open deal, isolates failures, and
respects the CA-rules gate. Plus the compliance-active endpoint (auth + open-only)."""

from __future__ import annotations

from datetime import date

import pytest

from app.compliance.ca_rules import RulesNotVerified, synthetic_ruleset
from app.compliance.scheduler import run_all
from app.contracts.compliance import DealFieldState, DealState


def _deal(txn_id: str) -> DealState:
    return DealState(
        transaction_id=txn_id,
        fields=[
            DealFieldState(
                name="acceptance_date", value="2026-07-10", confirmed=True, deadline_driving=True
            ),
            DealFieldState(
                name="inspection_contingency_days", value="17", confirmed=True, deadline_driving=True
            ),
        ],
    )


class FakeSchedulerMaster:
    def __init__(self, ids: list[str], *, fail: tuple[str, ...] = ()) -> None:
        self._ids = ids
        self._fail = set(fail)
        self.written: list[str] = []

    def list_active_transactions(self) -> list[str]:
        return list(self._ids)

    def read_deal_state(self, transaction_id: str) -> DealState | None:
        if transaction_id in self._fail:
            raise RuntimeError("simulated per-deal failure")
        return _deal(transaction_id)

    def write_compliance_result(self, result) -> None:
        self.written.append(result.transaction_id)


def test_run_all_sweeps_every_open_deal():
    master = FakeSchedulerMaster(["a", "b", "c"])
    summary = run_all(master, rules=synthetic_ruleset(), as_of=date(2026, 7, 10))
    assert [r["status"] for r in summary] == ["ok", "ok", "ok"]
    assert set(master.written) == {"a", "b", "c"}
    assert all(r["deadlines"] >= 1 for r in summary)


def test_run_all_isolates_a_failing_deal():
    master = FakeSchedulerMaster(["a", "bad", "c"], fail=("bad",))
    summary = run_all(master, rules=synthetic_ruleset(), as_of=date(2026, 7, 10))
    by = {r["transaction_id"]: r for r in summary}
    assert by["a"]["status"] == "ok" and by["c"]["status"] == "ok"
    assert by["bad"]["status"] == "error"
    assert set(master.written) == {"a", "c"}  # the good deals still ran and wrote


def test_run_all_blocks_when_rules_unverified(monkeypatch):
    monkeypatch.delenv("CA_RULES_VERIFIED", raising=False)
    master = FakeSchedulerMaster(["a"])
    with pytest.raises(RulesNotVerified):
        run_all(master, rules=None)  # verified loader raises before any deal is touched
    assert master.written == []


def test_compliance_active_endpoint_lists_open_ids(client, tc_headers, monkeypatch):
    monkeypatch.setenv("COMPLIANCE_SERVICE_TOKEN", "tok")
    t1 = client.post(
        "/transactions", json={"property_address": "1 A"}, headers=tc_headers
    ).json()["id"]
    t2 = client.post(
        "/transactions", json={"property_address": "2 B"}, headers=tc_headers
    ).json()["id"]
    r = client.get("/transactions/compliance-active", headers={"X-Compliance-Token": "tok"})
    assert r.status_code == 200
    assert set(r.json()["transaction_ids"]) == {t1, t2}


def test_main_handles_setup_failure_cleanly(monkeypatch, capsys):
    # Gate closed → run_all raises before any HTTP call; main() prints a clean
    # line (error type only, no traceback) and exits non-zero.
    monkeypatch.delenv("CA_RULES_VERIFIED", raising=False)
    from app.compliance.scheduler import main

    assert main([]) == 1
    out = capsys.readouterr().out.lower()
    assert "could not run" in out and "rulesnotverified" in out


def test_compliance_active_requires_service_token(client, monkeypatch):
    monkeypatch.setenv("COMPLIANCE_SERVICE_TOKEN", "tok")
    assert client.get("/transactions/compliance-active").status_code == 401
    assert (
        client.get(
            "/transactions/compliance-active", headers={"X-Compliance-Token": "wrong"}
        ).status_code
        == 401
    )
