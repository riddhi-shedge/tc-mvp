"""§5 write-authority matrix — who may ORIGINATE each canonical write.

The cross-surface contract makes authority a property of the *write*, not the
surface: everything else is a read-only projection for that role. This module is
the single source of truth for that matrix, plus the two "never by machine"
invariants (accepting an offer, resolving a repair request) that must be enforced
identically everywhere. Pure/declarative so every surface and the SOR agree.
"""

from __future__ import annotations

# Canonical write -> roles allowed to originate it. Agents act ON BEHALF OF a
# principal but cannot manufacture a principal's decision (see NEVER_BY_MACHINE).
AUTHORITY: dict[str, frozenset[str]] = {
    "offer.author": frozenset({"buyer_agent"}),
    "offer.accept": frozenset({"seller"}),                       # recorded seller authorization
    "disclosure.complete": frozenset({"seller"}),
    "disclosure.deliver": frozenset({"listing_agent"}),          # logged send
    "disclosure.acknowledge": frozenset({"buyer", "buyer_agent"}),
    "contingency.remove": frozenset({"buyer", "buyer_agent"}),
    "repair.resolve": frozenset({"seller"}),                     # recorded seller authorization
    "money.verify_out_of_band": frozenset({"buyer", "seller"}),  # the paying/receiving principal
    # App-level refinements of the row above — §5 says "the paying/RECEIVING
    # principal": the EMD payer is the buyer; the proceeds receiver is the seller.
    "money.verify_deposit": frozenset({"buyer"}),
    "money.verify_disbursement": frozenset({"seller"}),
    "approval.approve_send": frozenset({"buyer_agent", "listing_agent"}),
    "outbound.message": frozenset({"buyer_agent", "listing_agent"}),  # rule #3, via ApprovalItem
    "deadline.write": frozenset({"system"}),                     # compliance service only
    "health.write": frozenset({"system"}),                       # derived from events
    "task.done": frozenset(),                                    # dynamic: the task's ownerRole
}

# Writes that may NEVER be performed by the AI or the system — they require a
# recorded principal authorization (contract §5, §6.3).
NEVER_BY_MACHINE: frozenset[str] = frozenset({"offer.accept", "repair.resolve"})

# Writes that convey a principal's decision; any outbound draft conveying one MUST
# carry `reflectsPrincipalDecisionId` linking the authorization it represents.
PRINCIPAL_DECISION_WRITES: frozenset[str] = NEVER_BY_MACHINE

_MACHINE_ROLES = frozenset({"system", "ai"})


class UnauthorizedWrite(Exception):
    """A role attempted a write the authority matrix forbids."""


def can_originate(write: str, role: str, *, owner_role: str | None = None) -> bool:
    """True iff `role` may originate `write`. `task.done` is owner-scoped: only the
    task's ownerRole may complete it. A machine role can never do a NEVER_BY_MACHINE
    write, even if a mis-set matrix would otherwise allow it."""
    if write in NEVER_BY_MACHINE and role in _MACHINE_ROLES:
        return False
    if write == "task.done":
        return owner_role is not None and role == owner_role
    allowed = AUTHORITY.get(write)
    if allowed is None:
        return False
    return role in allowed


def require_originate(write: str, role: str, *, owner_role: str | None = None) -> None:
    if not can_originate(write, role, owner_role=owner_role):
        raise UnauthorizedWrite(f"{role} may not originate {write}")


# Draft purposes that CONVEY a principal's decision (accepting an offer,
# resolving a repair request). None exist as flows yet; the guard makes the
# §6.3 invariant executable the day one does.
DECISION_PURPOSES: frozenset[str] = frozenset({"offer_response", "repair_response"})


def validate_draft_purpose(purpose: str, reflects_decision_id: str | None) -> None:
    """§6.3: a draft conveying a principal's decision MUST link the recorded
    authorization it represents. Raises for decision-carrying purposes without one."""
    if purpose in DECISION_PURPOSES and not reflects_decision_id:
        raise UnauthorizedWrite(
            f"draft purpose '{purpose}' conveys a principal decision and requires "
            "reflectsPrincipalDecisionId (a recorded authorization)"
        )


def requires_principal_decision(write: str) -> bool:
    """Whether a draft conveying this write must link a recorded principal decision
    via `reflectsPrincipalDecisionId`."""
    return write in PRINCIPAL_DECISION_WRITES
