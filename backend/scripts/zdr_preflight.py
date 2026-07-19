"""ZDR / synthetic-only preflight — is it safe to process REAL client data?

Reports the current posture using the SAME gate (check_zdr_gate) the model
callers (extraction, drafting) use, so this can never disagree with what the
system will actually do. Exit code:
  0  coherent config — either safely synthetic-only, or real-data WITH ZDR.
  1  BLOCKED/incoherent — SYNTHETIC_ONLY=false but ZDR not confirmed.

Usage (from backend/, with your .env sourced):
    python -m scripts.zdr_preflight
"""

from __future__ import annotations

import os
import sys

from app.common.zdr import ZdrNotConfirmed, check_zdr_gate


def main(argv: list[str]) -> int:
    synthetic_only = os.environ.get("SYNTHETIC_ONLY", "true").lower() == "true"
    zdr = os.environ.get("ZDR_CONFIRMED", "false").lower() == "true"
    print(f"SYNTHETIC_ONLY={synthetic_only}   ZDR_CONFIRMED={zdr}")

    try:
        check_zdr_gate()
    except ZdrNotConfirmed as exc:
        print(f"BLOCKED: {exc}")
        print(
            "  → Keep SYNTHETIC_ONLY=true for dev, OR confirm Zero Data Retention "
            "with Anthropic and set ZDR_CONFIRMED=true before disabling synthetic-only."
        )
        return 1

    if synthetic_only:
        print("MODE: synthetic-only. Model calls are allowed, but ONLY synthetic data")
        print("      may be in the system — the gate trusts this flag; it can't detect")
        print("      real data. Do NOT feed real client data while this is true.")
        print(
            "  → To process REAL data: confirm ZDR with Anthropic, then set both "
            "ZDR_CONFIRMED=true and SYNTHETIC_ONLY=false."
        )
    else:
        print("MODE: REAL-DATA enabled, ZDR confirmed. Real client data may be processed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
