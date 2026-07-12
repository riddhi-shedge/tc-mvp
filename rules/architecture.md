# Architecture — three decoupled parts, payloads only

## The three parts

**(a) Ingestion agent** — watches the dedicated deal address (Postmark inbound) and
the manual-upload fallback. Detects document type, readability, and signatures;
extracts fields with confidence scores; emits a validated **Payload**. It does
**not** write the SOR directly.

**(b) Master / System of Record** — the Supabase-backed record: Transactions,
Properties, Parties, Documents, Deadlines, Tasks, Messages, Approvals, Audit Log.
Consumes Payloads (after HITL confirmation) and is the single source of truth.
See `rules/data-model.md`.

**(c) Compliance / timeline service** — interval-run. Reads confirmed fields,
computes Deadlines and Tasks from **human-verified** CA rules, and raises Risk
Flags. Domain rules are researched by `ca-rules-researcher` and **verified by a
human** before they drive anything — the service never guesses them.

## The one communication rule

Parts talk **only through validated Payloads.** A part must never:

- read or write another part's database tables directly,
- import another part's internal modules, or
- share in-memory state with another part.

Cross-component DB access is a **stop-the-line** violation — flag it to
`compliance-auditor` / `code-reviewer`.

## The Payload contract (from §10)

A **Payload** is the interface between (a) ingestion and (b) master — a validated
package describing:

- **which document** was ingested,
- **which transaction** it belongs to (or `"new"`),
- **which party** it relates to,
- **extracted fields** — a list of `{ name, value, confidence, confirmed? }`.

Payloads are validated at the boundary (a Pydantic model on the FastAPI side).
Transaction creation from a `"new"` payload is **HITL**: the TC confirms before the
master commits anything.

## Why decoupled

Errors don't compound across parts; each part is testable in isolation with
synthetic payloads at its boundary; and any one part can be rebuilt without touching
the others.
