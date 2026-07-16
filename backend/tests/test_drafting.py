"""ClaudeDrafter unit tests: the ZDR gate (Rule 5) and Rule 2 (no wiring in the
prompt/output). The real model call is exercised opt-in in test_llm_extraction
style if needed; here we test the gate and the fake."""

import pytest

from app.common.zdr import ZdrNotConfirmed
from app.master.drafting import ClaudeDrafter, DraftContext
from tests.fake_mailer import FakeDrafter


def _ctx() -> DraftContext:
    return DraftContext(
        property_address="123 Stub St (synthetic)",
        lender_name="Synthetic Lender",
        loan_deadline="2026-07-31",
        loan_status_note=None,
    )


def test_zdr_gate_blocks_real_drafter(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_ONLY", "false")
    monkeypatch.setenv("ZDR_CONFIRMED", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-key")
    with pytest.raises(ZdrNotConfirmed):
        ClaudeDrafter().draft_lender_status(_ctx())


def test_fake_drafter_references_context_and_has_why():
    draft = FakeDrafter().draft_lender_status(_ctx())
    assert "123 Stub St" in draft.subject or "123 Stub St" in draft.body
    assert "2026-07-31" in draft.body or "2026-07-31" in draft.why
    assert draft.why
    # Rule 2: no wiring/payment language anywhere in the draft.
    text = f"{draft.subject} {draft.body} {draft.why}".lower()
    for banned in ("wire", "routing", "account number", "iban", "swift"):
        assert banned not in text
    # Rule 1: not a form.
    assert "c.a.r." not in text and "contingency removal" not in text
