"""The ZDR / synthetic-only gate (Rule 5) — shared infrastructure.

Any part that sends deal content to a model (ingestion extraction, master
drafting) checks this gate first. It lives in app/common/ so no part imports
another part's internals (rules/architecture.md).

Until Anthropic zero-data-retention is confirmed active, only synthetic data may
touch the API. Flipping SYNTHETIC_ONLY=false without ZDR_CONFIRMED=true
hard-stops every model call.
"""

from __future__ import annotations

import os


class ZdrNotConfirmed(Exception):
    """A model call was attempted with real data before ZDR is confirmed."""


def check_zdr_gate() -> None:
    zdr = os.environ.get("ZDR_CONFIRMED", "false").lower() == "true"
    synthetic_only = os.environ.get("SYNTHETIC_ONLY", "true").lower() == "true"
    if not zdr and not synthetic_only:
        raise ZdrNotConfirmed(
            "Model calls are disabled: SYNTHETIC_ONLY=false but Anthropic "
            "zero-data-retention is not confirmed (ZDR_CONFIRMED!=true). No real "
            "client data may be processed until ZDR is active (§3, Rule 5)."
        )
