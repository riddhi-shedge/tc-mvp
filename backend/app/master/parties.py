"""Deriving Party records from the confirmed purchase-agreement fields, plus the
canonical role → permission-tier vocabulary (§8). Pure: no I/O, fully testable.

Parties are created only from HUMAN-CONFIRMED name/agent/company fields — the
same "never silently guess" rule as the timeline: a name the TC hasn't confirmed
never becomes a contact record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Role → default permission tier (§8). The TC (operator) is not a party. Agents
# and email-only participants can be messaged but hold no live DB credential in
# the MVP; receiving-end vendors get a scoped task token (Phase 7 RLS).
ROLE_TIERS: dict[str, str] = {
    "buyer": "email_participant",
    "seller": "email_participant",
    "buyer_agent": "email_participant",
    "listing_agent": "email_participant",
    "lender": "email_participant",
    "loan_officer": "email_participant",
    "escrow": "email_participant",
    "title": "email_participant",
    "home_warranty": "email_participant",
    "insurance": "email_participant",
    "appraiser": "receiving_end",
    "contractor": "receiving_end",
    "inspector_general": "receiving_end",
    "inspector_termite": "receiving_end",
    "inspector_roof": "receiving_end",
    "inspector_sewer": "receiving_end",
}


def tier_for(role: str) -> str:
    return ROLE_TIERS.get(role, "email_participant")


@dataclass(frozen=True)
class DerivedParty:
    role: str
    name: str
    company: str | None


# Split a multi-name field into people: "A, B", "A and B", "A & B", "A; B".
_SPLIT = re.compile(r"\s*(?:,| and | & |;|/)\s*", re.IGNORECASE)


def _people(value: str) -> list[str]:
    return [p.strip() for p in _SPLIT.split(value.strip()) if p.strip()]


def _agent(value: str) -> tuple[str, str | None]:
    """'Jane Doe, XYZ Realty' -> ('Jane Doe', 'XYZ Realty'). Brokerage is the
    remainder after the first comma (the §5 field is 'agent and brokerage')."""
    head, _, tail = value.strip().partition(",")
    return head.strip(), (tail.strip() or None)


def derive_parties(confirmed: dict[str, str]) -> list[DerivedParty]:
    """The Party records implied by the confirmed §5 fields. Buyers/sellers split
    to one record per person; agents split name/brokerage; escrow/title are the
    company itself."""
    out: list[DerivedParty] = []
    for person in _people(confirmed.get("buyer_names", "")):
        out.append(DerivedParty("buyer", person, None))
    for person in _people(confirmed.get("seller_names", "")):
        out.append(DerivedParty("seller", person, None))
    for field, role in (
        ("buyer_agent", "buyer_agent"),
        ("listing_agent", "listing_agent"),
        ("lender_contact", "lender"),
    ):
        value = (confirmed.get(field) or "").strip()
        if value:
            name, company = _agent(value)
            out.append(DerivedParty(role, name, company))
    for field, role in (("escrow_holder", "escrow"), ("title_company", "title")):
        value = (confirmed.get(field) or "").strip()
        if value:
            out.append(DerivedParty(role, value, value))
    return out


def party_key(role: str, name: str) -> tuple[str, str]:
    """Idempotency key so re-confirming (or attaching a 2nd doc) never duplicates
    a party: role + case/space-normalized name."""
    return (role, re.sub(r"\s+", " ", name).strip().lower())
