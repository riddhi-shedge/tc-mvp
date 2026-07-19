"""The ZDR preflight reports posture and exit code consistent with the gate."""

from __future__ import annotations

from scripts.zdr_preflight import main


def test_synthetic_only_default_is_coherent(monkeypatch, capsys):
    monkeypatch.delenv("SYNTHETIC_ONLY", raising=False)
    monkeypatch.delenv("ZDR_CONFIRMED", raising=False)
    assert main(["prog"]) == 0
    assert "synthetic-only" in capsys.readouterr().out.lower()


def test_real_data_without_zdr_is_blocked(monkeypatch, capsys):
    monkeypatch.setenv("SYNTHETIC_ONLY", "false")
    monkeypatch.delenv("ZDR_CONFIRMED", raising=False)
    assert main(["prog"]) == 1
    assert "blocked" in capsys.readouterr().out.lower()


def test_real_data_with_zdr_is_allowed(monkeypatch, capsys):
    monkeypatch.setenv("SYNTHETIC_ONLY", "false")
    monkeypatch.setenv("ZDR_CONFIRMED", "true")
    assert main(["prog"]) == 0
    assert "real-data enabled" in capsys.readouterr().out.lower()
