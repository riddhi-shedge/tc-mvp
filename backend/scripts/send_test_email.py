"""Guarded Postmark test-send — validate the outbound path before real deals.

Sends a synthetic test message through the SAME guarded PostmarkMailer used in
production. It only delivers when SEND_ENABLED=true AND the recipient is on
SEND_ALLOWLIST AND Postmark is configured (server token + a verified From). Each
guard that blocks the send prints exactly why, so you can bring the config up one
step at a time. Nothing about a real deal is ever sent — the body is clearly a
synthetic test.

Usage (from backend/, with your .env sourced):
    python -m scripts.send_test_email you@allowlisted.example
"""

from __future__ import annotations

import sys

from app.master.mailer import (
    PostmarkMailer,
    RecipientNotAllowed,
    SendDisabled,
    SendFailed,
)

_SUBJECT = "TC test email (synthetic) — please ignore"
_BODY = (
    "This is a synthetic test message from the Transaction Coordinator outbound "
    "path. If you received it, guarded Postmark sending is working. No real "
    "transaction data is included."
)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].strip():
        print("usage: python -m scripts.send_test_email <recipient@allowlisted>")
        return 2
    recipient = argv[1].strip()

    try:
        result = PostmarkMailer().send(to=recipient, subject=_SUBJECT, body=_BODY)
    except SendDisabled as exc:
        print(f"BLOCKED (sending disabled): {exc}")
        print("  → Set SEND_ENABLED=true, and POSTMARK_SERVER_TOKEN / POSTMARK_FROM_EMAIL.")
        return 1
    except RecipientNotAllowed as exc:
        print(f"BLOCKED (recipient not allow-listed): {exc}")
        print(f"  → Add {recipient!r} to SEND_ALLOWLIST (comma-separated addresses).")
        return 1
    except SendFailed as exc:
        print(f"FAILED at the provider: {exc}")
        print(
            "  → Check the server token; that POSTMARK_FROM_EMAIL is a VERIFIED Postmark "
            "Sender Signature (or DKIM-verified domain); and that the account/server is "
            "approved for sending."
        )
        return 1

    print(f"SENT ✓  provider_message_id={result.provider_message_id}")
    print(f"  → Delivered to {recipient} via Postmark. The guarded outbound path works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
