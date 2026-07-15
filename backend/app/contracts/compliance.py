"""The compliance/timeline contract — the boundary between part (b) master and
part (c) the compliance service (rules/architecture.md, §6).

The compliance service consumes a DealState (a snapshot of confirmed master
state — the synthetic-state input its tests run against) and produces a
ComplianceResult (deadlines, tasks, risk flags, draft reminders). Parts talk
only through these validated payloads; the service never reads or writes the
master's tables directly.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

# ---- Input: a snapshot of confirmed master state ---------------------------


class DealFieldState(BaseModel):
    """One confirmed extracted field the service may compute from."""

    name: str
    value: str
    confirmed: bool
    deadline_driving: bool


class DealPartyState(BaseModel):
    role: str
    name: str | None = None
    email: str | None = None


class DealDocState(BaseModel):
    doc_type: str | None = None
    status: str


class DealTaskState(BaseModel):
    """An existing task on the deal (to detect 'open tasks near closing')."""

    title: str
    status: str


class DealState(BaseModel):
    """The compliance service's whole world — no master internals leak in."""

    transaction_id: str
    fields: list[DealFieldState] = Field(default_factory=list)
    parties: list[DealPartyState] = Field(default_factory=list)
    documents: list[DealDocState] = Field(default_factory=list)
    tasks: list[DealTaskState] = Field(default_factory=list)

    def confirmed_value(self, name: str) -> str | None:
        for f in self.fields:
            if f.name == name and f.confirmed:
                return f.value
        return None


# ---- Output: what the service computed --------------------------------------


class ComputedDeadline(BaseModel):
    key: str  # stable id, e.g. "inspection_contingency" — used for dependencies
    name: str
    due_date: date
    source_field: str  # which §5 field drove it


class ComputedTask(BaseModel):
    key: str
    title: str
    deadline_key: str | None = None  # ties to a ComputedDeadline
    depends_on_key: str | None = None


class RiskFlag(BaseModel):
    case: str  # one of the seven §6 cases
    severity: str = "warning"
    description: str
    deadline_key: str | None = None


class DraftReminder(BaseModel):
    """A draft outbound message (Rule 3: draft only, needs human approval).
    Never a C.A.R. form (Rule 1)."""

    flag_case: str
    to_role: str | None
    subject: str
    body: str


class ComplianceResult(BaseModel):
    transaction_id: str
    deadlines: list[ComputedDeadline] = Field(default_factory=list)
    tasks: list[ComputedTask] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    draft_reminders: list[DraftReminder] = Field(default_factory=list)
