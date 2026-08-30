"""California-local dates for deadline logic.

The product is California-only (Rule 4): every contractual deadline is a
calendar day in Pacific time. Deployed servers run UTC, where date.today()
flips to *tomorrow* at 4–5pm PT — early enough to flag a deadline "missed"
while a CA agent is still at their desk, and to seed stub timelines a day
late. All deadline math therefore asks for the CA calendar day, never the
server's.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    _CA: timezone | object = ZoneInfo("America/Los_Angeles")
except Exception:  # tzdata absent in a slim image — approximate with PST
    _CA = timezone(timedelta(hours=-8))


def ca_today() -> date:
    """Today's calendar date in California (America/Los_Angeles)."""
    return datetime.now(_CA).date()  # type: ignore[arg-type]
