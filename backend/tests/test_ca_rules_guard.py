"""The CA-rules guard: production must not compute on unverified rules."""

import pytest

from app.compliance.ca_rules import (
    VERIFIED_RULESET,
    RulesNotVerified,
    load_verified_ruleset,
    synthetic_ruleset,
)


def test_verified_ruleset_is_filled_with_6_26_values():
    # Signed against RPA 6/26 (docs/ca-rules-verification.md) — no longer empty.
    assert VERIFIED_RULESET is not None
    assert VERIFIED_RULESET.default_periods["loan_contingency_days"].days == 17
    assert VERIFIED_RULESET.default_periods["emd_due_days"].unit == "business"
    assert VERIFIED_RULESET.nbp_cure.days == 2
    assert VERIFIED_RULESET.dce_earliest_days_before == 3


def test_loader_raises_when_flag_unset(monkeypatch):
    # Values exist, but production must still explicitly opt in via the env flag.
    monkeypatch.delenv("CA_RULES_VERIFIED", raising=False)
    with pytest.raises(RulesNotVerified, match="not verified"):
        load_verified_ruleset()


def test_loader_returns_ruleset_when_flag_set(monkeypatch):
    monkeypatch.setenv("CA_RULES_VERIFIED", "true")
    rules = load_verified_ruleset()
    assert rules is VERIFIED_RULESET
    assert rules.default_periods["loan_contingency_days"].days == 17


def test_synthetic_ruleset_is_usable_but_clearly_not_verified():
    rules = synthetic_ruleset()
    # Structurally complete so the engine runs...
    assert rules.period_for("inspection_contingency_days") is not None
    assert rules.nbp_earliest_days_before == 2
    # ...but it is NOT wired into the production loader.
    assert rules is not VERIFIED_RULESET
