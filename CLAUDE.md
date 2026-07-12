# tc-mvp — Agent Instructions

> Read at the top of every session. Kept tight on purpose — detail lives in `rules/`.

## What this is

tc-mvp is a **system of record (SOR)** for California residential real-estate
transactions that replaces the transaction coordinator's (TC's) mental switchboard.
It ingests a signed purchase agreement from a **scoped, dedicated deal address**,
extracts the deal's fields, builds a deadline timeline from **human-verified** CA
rules, and drafts outbound follow-ups that **a human approves before sending**.
Every party, document, deadline, task, message, and approval lives here, in an
append-only audited record — this is the deal's single source of truth.

## The five hard rules (verbatim — never violate)

1. **Only ever ingest the customer's own signed contract. Never generate, host, or pre-fill blank C.A.R. (California Association of Realtors) forms.** Why: reading a signed copy is permitted; reproducing blank copyrighted forms is not.
2. **Never touch money movement or wiring instructions.** Why: wire fraud is the top loss vector in real estate closings; automating it is unacceptable risk.
3. **A human approves every outbound message. No auto-send, ever.** Why: a wrong message to an outside party is the thing practitioners most fear.
4. **California residential only to start.** Why: each state's forms and deadline rules differ; we get one right first.
5. **Any AI model that sees the documents runs in a no-train / no-retain configuration.** Why: the files contain Social Security numbers and bank details; that data must never be retained or trained on.

If a change touches any of these, **stop and route it to the `compliance-auditor`
subagent** before proceeding. Detail in `rules/security.md`.

## Architecture — three decoupled parts

The system is three parts that communicate **only through validated Payloads**. No
part reads or writes another part's database, and no part imports another part's code.

- **(a) Ingestion agent** — watches the dedicated deal address (Postmark inbound) and the manual-upload fallback; detects doc type / readability / signatures; extracts fields with confidence scores; emits a Payload. Never writes the SOR directly.
- **(b) Master (SOR)** — the Supabase-backed record. Consumes Payloads *after HITL confirmation* and is the single source of truth.
- **(c) Compliance / timeline service** — interval-run; computes Deadlines/Tasks from human-verified CA rules and raises Risk Flags. Never guesses the rules.

Detail in `rules/architecture.md`. Schema in `rules/data-model.md`.

## Stack

- **Frontend:** React + TypeScript
- **Backend:** Python / FastAPI
- **Data / auth / storage:** Supabase (Postgres, auth + MFA, encrypted document storage, row-level security)
- **LLM:** Anthropic API (Claude) — **no-train / no-retain**
- **Email:** Postmark (inbound parse = MVP trigger; outbound send)

## TDD mandate

Tests first, derived from the phase's "done when." Every component testable in
isolation with synthetic payloads. **Synthetic state only — never real NPI.**
Detail in `rules/testing.md`.

## Rules directory

- `rules/security.md` — the five hard rules in detail; the NPI / synthetic-only gate; dedicated-inbox-only ingestion
- `rules/architecture.md` — decoupling, the payload contract, no cross-component DB access
- `rules/testing.md` — TDD; each component testable in isolation; synthetic state only
- `rules/data-model.md` — the §10 schema (single source of truth)
- `rules/code-style.md` — conventions

## Self-annealing

When you repeat a mistake, **propose a new rule for `rules/`.**
