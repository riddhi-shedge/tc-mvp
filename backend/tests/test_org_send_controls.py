"""PostmarkMailer recipient policy (Track A5): the org's send settings gate
every outbound send, layered with the env SEND_ALLOWLIST which can only ever
NARROW. All refusal paths run before any network call; the one allowed case
stubs the provider."""

from __future__ import annotations

import pytest

from app.master.mailer import PostmarkMailer, RecipientNotAllowed, SendDisabled, SendFailed

ORG = "org-x"


def _mailer(settings: dict | None) -> PostmarkMailer:
    return PostmarkMailer(settings_lookup=lambda org_id: settings if org_id == ORG else None)


def test_disabled_wins_over_everything(monkeypatch):
    monkeypatch.delenv("SEND_ENABLED", raising=False)
    with pytest.raises(SendDisabled):
        _mailer({"send_mode": "open", "send_allowlist": []}).send(
            to="a@b.test", subject="s", body="b", org_id=ORG
        )


def test_no_settings_row_and_no_env_refuses(monkeypatch):
    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.delenv("SEND_ALLOWLIST", raising=False)
    with pytest.raises(RecipientNotAllowed):
        _mailer(None).send(to="a@b.test", subject="s", body="b", org_id=ORG)


def test_no_settings_row_falls_back_to_env_list(monkeypatch):
    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.setenv("SEND_ALLOWLIST", "ok@x.test")
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: type(
            "R", (), {"status_code": 200, "json": lambda self: {"MessageID": "m1"}}
        )(),
    )
    monkeypatch.setenv("POSTMARK_SERVER_TOKEN", "t")
    monkeypatch.setenv("POSTMARK_FROM_EMAIL", "from@x.test")
    sent = _mailer(None).send(to="OK@x.test", subject="s", body="b", org_id=ORG)
    assert sent.provider_message_id == "m1"
    with pytest.raises(RecipientNotAllowed):
        _mailer(None).send(to="other@x.test", subject="s", body="b", org_id=ORG)


def test_org_allowlist_mode_gates_recipients(monkeypatch):
    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.delenv("SEND_ALLOWLIST", raising=False)
    monkeypatch.setenv("POSTMARK_SERVER_TOKEN", "t")
    monkeypatch.setenv("POSTMARK_FROM_EMAIL", "from@x.test")
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: type(
            "R", (), {"status_code": 200, "json": lambda self: {"MessageID": "m2"}}
        )(),
    )
    mailer = _mailer({"send_mode": "allowlist", "send_allowlist": ["Escrow@Title.test"]})
    assert (
        mailer.send(to="escrow@title.test", subject="s", body="b", org_id=ORG)
        .provider_message_id
        == "m2"
    )
    with pytest.raises(RecipientNotAllowed):
        mailer.send(to="stranger@x.test", subject="s", body="b", org_id=ORG)


def test_env_list_narrows_even_an_open_org(monkeypatch):
    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.setenv("SEND_ALLOWLIST", "only@here.test")
    mailer = _mailer({"send_mode": "open", "send_allowlist": []})
    with pytest.raises(RecipientNotAllowed):
        mailer.send(to="anyone@else.test", subject="s", body="b", org_id=ORG)


def test_open_org_with_no_env_list_sends(monkeypatch):
    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.delenv("SEND_ALLOWLIST", raising=False)
    monkeypatch.setenv("POSTMARK_SERVER_TOKEN", "t")
    monkeypatch.setenv("POSTMARK_FROM_EMAIL", "from@x.test")
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: type(
            "R", (), {"status_code": 200, "json": lambda self: {"MessageID": "m3"}}
        )(),
    )
    mailer = _mailer({"send_mode": "open", "send_allowlist": []})
    assert (
        mailer.send(to="anyone@else.test", subject="s", body="b", org_id=ORG)
        .provider_message_id
        == "m3"
    )


def test_settings_lookup_outage_fails_closed(monkeypatch):
    """A settings-read failure must not fall back to the env path (which could
    WIDEN an org's allowlist policy) — the send fails and the TC retries."""
    monkeypatch.setenv("SEND_ENABLED", "true")
    monkeypatch.setenv("SEND_ALLOWLIST", "someone@x.test")

    def boom(org_id: str):
        raise RuntimeError("db down")

    mailer = PostmarkMailer(settings_lookup=boom)
    with pytest.raises(SendFailed):
        mailer.send(to="someone@x.test", subject="s", body="b", org_id=ORG)
