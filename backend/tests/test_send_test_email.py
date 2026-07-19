"""The guarded test-send CLI maps each guard to a clear exit code — and never
sends in the default (disabled) config."""

from __future__ import annotations

from scripts.send_test_email import main


def test_usage_error_returns_2(capsys):
    assert main(["prog"]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_blocks_when_sending_disabled(monkeypatch, capsys):
    # Default posture: SEND_ENABLED unset → fails closed, nothing delivered.
    monkeypatch.delenv("SEND_ENABLED", raising=False)
    assert main(["prog", "someone@allowlisted.test"]) == 1
    assert "disabled" in capsys.readouterr().out.lower()


def test_blocks_when_recipient_not_allowlisted(monkeypatch, capsys):
    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.setenv("SEND_ALLOWLIST", "allowed@example.test")
    assert main(["prog", "not-allowed@example.test"]) == 1
    assert "allow" in capsys.readouterr().out.lower()
