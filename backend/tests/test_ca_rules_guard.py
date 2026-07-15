"""The CA-rules guard: production must not compute on unverified rules."""

import pytest

from app.compliance.ca_rules import (
    VERIFIED_RULESET,
    RulesNotVerified,
    load_verified_ruleset,
    synthetic_ruleset,
)


def test_verified_ruleset_ships_empty():
    # Until a human fills it in, there are NO verified rules in the codebase.
    assert VERIFIED_RULESET is None


def test_loader_raises_when_flag_unset(monkeypatch):
    monkeypatch.delenv("CA_RULES_VERIFIED", raising=False)
    with pytest.raises(RulesNotVerified, match="not verified"):
        load_verified_ruleset()


def test_loader_raises_when_flag_true_but_values_missing(monkeypatch):
    # Flipping the flag alone must not conjure rules — the values are still None.
    monkeypatch.setenv("CA_RULES_VERIFIED", "true")
    with pytest.raises(RulesNotVerified):
        load_verified_ruleset()


def test_synthetic_ruleset_is_usable_but_clearly_not_verified():
    rules = synthetic_ruleset()
    # Structurally complete so the engine runs...
    assert rules.period_for("inspection_contingency_days") is not None
    assert rules.nbp_earliest_days_before == 2
    # ...but it is NOT wired into the production loader.
    assert rules is not VERIFIED_RULESET
