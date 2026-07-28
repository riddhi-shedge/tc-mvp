"""Cross-document inconsistency detection (proposal §2.8 / §2.14).

When a newly uploaded purchase agreement carries a value that conflicts with a
field the TC already confirmed (e.g. an amended contract with a different close
date), we raise a risk flag for the TC to reconcile — a wrong date silently
overwriting a confirmed one can cost a client their deposit. Pure comparison; the
caller persists the flags.
"""

from __future__ import annotations

import re

_AMOUNT_FIELDS = {
    "purchase_price",
    "initial_deposit_amount",
    "increased_deposit_amount",
    "loan_amount",
    "down_payment",
}
_DATE_FIELDS = {"close_of_escrow", "acceptance_date", "possession_date"}
_DAYS_FIELDS = {
    "inspection_contingency_days",
    "loan_contingency_days",
    "appraisal_contingency_days",
    "emd_due_days",
    "insurance_contingency_days",
    "disclosure_delivery_days",
    "verification_of_funds_days",
}
# Fields where a silent change actually matters (drives money or a deadline).
MATERIAL_FIELDS = _AMOUNT_FIELDS | _DATE_FIELDS | _DAYS_FIELDS | {"property_address"}
# Money/date conflicts are the dangerous ones → critical; the rest → warning.
CRITICAL_FIELDS = _AMOUNT_FIELDS | _DATE_FIELDS


def _canonical(name: str, value: str) -> str:
    """Normalize so cosmetic differences ($450,000 vs 450000.00) don't false-flag."""
    if name in _AMOUNT_FIELDS:
        digits = re.sub(r"[^0-9.]", "", value)
        try:
            return f"{float(digits):.2f}"
        except ValueError:
            return value.strip().lower()
    if name in _DAYS_FIELDS:
        m = re.match(r"\s*(\d+)", value)
        return m.group(1) if m else value.strip().lower()
    if name in _DATE_FIELDS:
        return value.strip()[:10]
    return re.sub(r"[^a-z0-9]", "", value.lower())


def find_field_conflicts(
    existing_confirmed: dict[str, str], incoming: dict[str, str]
) -> list[tuple[str, str, str]]:
    """Return (name, old_value, new_value) for every MATERIAL field present in
    both maps whose canonical values differ."""
    conflicts: list[tuple[str, str, str]] = []
    for name in MATERIAL_FIELDS:
        old = existing_confirmed.get(name)
        new = incoming.get(name)
        if old is None or new is None:
            continue
        if _canonical(name, old) != _canonical(name, new):
            conflicts.append((name, old, new))
    return conflicts
