# Data model / schema — the SOR (§10, single source of truth)

This is the authoritative schema. When code and this file disagree, **this file
wins** — update the code, or propose a change here first.

## Entities

- **Transaction** — one home sale; has one Property, many Parties, many Documents, many Deadlines, many Tasks, many Messages, many Payloads, an Audit Log. Identified by a transaction ID.
- **Property** — the home (address, included/excluded items, possession).
- **Party / Contact** — a person or company on the deal, each with a role that sets its permission tier. A transaction has many inspection parties (general, termite/pest, roof, sewer) and may have a Contractor for post-inspection repairs.
- **Document** — an uploaded/ingested file, access-controlled by side/role; may carry a pending state until confirmed.
- **Payload** — a validated package handed from the ingestion agent to the master (which document, which transaction, which party, extracted fields, confidence). The interface between part (a) and part (b).
- **Extracted Field** — one value read from a document, with a confidence score and a `confirmed?` flag.
- **Deadline** — a dated obligation computed from confirmed fields.
- **Task** — a thing to do, tied to a Deadline, with status and dependencies; a Task can belong to a receiving-end party (an inspector marks their own done).
- **Message** — an email drafted/sent to a Party, with `draft / approved / sent` state.
- **Reminder** — a scheduled nudge tied to a Deadline or Task.
- **Risk Flag** — a warning raised by the compliance service against a Task/Deadline.
- **Approval** — the record that a human approved a Message (or a pending inbound item) before it committed.
- **Audit Log** — append-only history of who did what and when.

## Relationships (one sentence)

A Transaction has a Property and many Parties (including several inspection parties
and an optional contractor); ingested Documents arrive as Payloads that become
Extracted Fields (scored, confirmed); confirmed fields create Deadlines → Tasks,
Reminders, and Risk Flags; Tasks generate Messages that require an Approval to send;
everything writes to the Audit Log.

## Permission tiers (§8) that gate access

Four tiers set what a Party's role can do:

- **Operator** — runs the deal; full access (the Transaction Coordinator).
- **Collaborator** *(built later)* — views own deals or oversees compliance; no operating controls (agent, broker/compliance).
- **Receiving-end** — between "email-only" and "has a login"; gets reminders and can mark their own task done; sees nothing else (inspectors, contractor, appraiser, insurance, home-warranty).
- **Email participant** — plain email exchange, no login (buyer/seller, lender/title).

MVP is **email-first with no outside logins.** Escrow's full visibility is a **V1
login** (the first outside portal), not MVP. Row-level security in Supabase enforces
these tiers in the database, not just the UI.
