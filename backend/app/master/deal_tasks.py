"""Deriving action-item tasks from confirmed cost-allocation fields (Table Q).
Pure: no I/O, fully testable.

Currently the home-warranty issuer rule: a "buyer's choice" plan is the buyer's
agent's action item; a warranty that's in play but names no issuer is the listing
(seller's) agent's. A blank/absent field never invents a task.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivedTask:
    key: str  # compute_key — idempotency + survives compliance re-runs
    title: str
    assign_role: str  # party role to assign to (may not exist on the deal yet)


_BUYER_CHOICE = {"buyer's choice", "buyers choice", "buyer choice", "buyer's option"}
# Values of home_warranty_paid_by that mean "no warranty on this deal".
_NO_WARRANTY = {"", "none", "n/a", "na", "no", "waived", "declined"}


def derive_tasks(confirmed: dict[str, str]) -> list[DerivedTask]:
    out: list[DerivedTask] = []
    issued = (confirmed.get("home_warranty_issued_by") or "").strip()
    paid_by = (confirmed.get("home_warranty_paid_by") or "").strip()
    warranty_in_play = paid_by.lower() not in _NO_WARRANTY

    if issued.lower() in _BUYER_CHOICE:
        out.append(
            DerivedTask(
                "home_warranty_choice",
                "Select home-warranty provider (buyer's choice)",
                "buyer_agent",
            )
        )
    elif not issued and warranty_in_play:
        out.append(
            DerivedTask(
                "home_warranty_confirm",
                "Confirm home-warranty provider",
                "listing_agent",
            )
        )
    return out
