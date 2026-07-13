"""Part (b) — Master / System of Record.

Consumes Payloads (after HITL confirmation) and is the single source of truth for
Transactions, Properties, Parties, Documents, Deadlines, Tasks, Messages,
Approvals, and the Audit Log. Backed by Supabase. See rules/data-model.md.
"""
