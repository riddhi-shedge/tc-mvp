"""Routing suggestions (Phase 3): ID beats sender history beats address
overlap; no match means None — the TC is ASKED, never guessed for."""

from app.ingestion.routing import suggest_transaction

TXN_A = "11111111-1111-4111-8111-111111111111"
TXN_B = "22222222-2222-4222-8222-222222222222"

TRANSACTIONS = [
    {"id": TXN_A, "property_address": "742 Evergreen Terrace, Springfield CA"},
    {"id": TXN_B, "property_address": "123 Stub St, Sacramento CA"},
]


def test_uuid_in_subject_wins():
    s = suggest_transaction(
        subject=f"Re: deal {TXN_B} — appraisal",
        from_email="anyone@example.test",
        transactions=TRANSACTIONS,
        sender_history={"anyone@example.test": TXN_A},  # history says A; id says B
    )
    assert s is not None
    assert s["transaction_id"] == TXN_B
    assert "transaction id" in s["reason"]


def test_unknown_uuid_in_subject_is_not_suggested():
    s = suggest_transaction(
        subject="Re: deal 99999999-9999-4999-8999-999999999999",
        from_email="new@example.test",
        transactions=TRANSACTIONS,
        sender_history={},
    )
    assert s is None


def test_sender_history_beats_address_overlap():
    s = suggest_transaction(
        subject="Docs for 123 Stub St Sacramento",  # address points at B
        from_email="lender@example.test",
        transactions=TRANSACTIONS,
        sender_history={"lender@example.test": TXN_A},
    )
    assert s is not None
    assert s["transaction_id"] == TXN_A
    assert "previously sent" in s["reason"]


def test_address_overlap_matches():
    s = suggest_transaction(
        subject="Appraisal for 742 Evergreen Terrace",
        from_email="new-appraiser@example.test",
        transactions=TRANSACTIONS,
        sender_history={},
    )
    assert s is not None
    assert s["transaction_id"] == TXN_A
    assert "property address" in s["reason"]


def test_single_word_overlap_is_not_enough():
    s = suggest_transaction(
        subject="Question about Sacramento",
        from_email="new@example.test",
        transactions=TRANSACTIONS,
        sender_history={},
    )
    assert s is None


def test_no_signal_asks_the_tc():
    s = suggest_transaction(
        subject="Attached documents",
        from_email="stranger@example.test",
        transactions=TRANSACTIONS,
        sender_history={},
    )
    assert s is None


def test_stale_sender_history_for_unknown_transaction_is_ignored():
    s = suggest_transaction(
        subject="More docs",
        from_email="lender@example.test",
        transactions=TRANSACTIONS,
        sender_history={"lender@example.test": "99999999-9999-4999-8999-999999999999"},
    )
    assert s is None
