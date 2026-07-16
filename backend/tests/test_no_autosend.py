"""Done-when guard (Rule 3): a codebase search finds no auto-send path — the
ONLY code that transitions a message to 'sent' is the approve-and-send method,
which requires a recorded human Approval first."""

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def _sent_writes(text: str) -> list[str]:
    # Lines that set a message status to 'sent' (dict-literal or .update).
    return [
        line.strip()
        for line in text.splitlines()
        if re.search(r"""["']status["']\s*:\s*["']sent["']""", line)
    ]


def test_only_the_approval_path_writes_sent():
    hits: dict[str, list[str]] = {}
    for py in APP.rglob("*.py"):
        found = _sent_writes(py.read_text())
        if found:
            hits[str(py.relative_to(APP))] = found

    # The single sent-writer lives in the master repo's approve_and_send.
    assert set(hits) == {"master/repo.py"}, f"unexpected sent-writers: {hits}"
    assert len(hits["master/repo.py"]) == 1


def test_no_send_calls_outside_the_mailer_and_approval_path():
    # No outbound email send anywhere except mailer.py (PostmarkMailer) and its
    # single caller inside repo.approve_and_send.
    offenders = []
    for py in APP.rglob("*.py"):
        rel = str(py.relative_to(APP))
        if rel in ("master/mailer.py", "master/repo.py"):
            continue
        text = py.read_text().lower()
        if "postmarkapp.com/email" in text or "mailer.send(" in text:
            offenders.append(rel)
    assert offenders == [], f"unexpected send path(s): {offenders}"
