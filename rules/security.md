# Security — the five hard rules & the NPI gate

These are load-bearing. A violation is not a bug to fix later; it is a
**stop-the-line event.** When a change touches any of these, halt and route it to
the `compliance-auditor` subagent before proceeding.

## The five hard rules (verbatim)

1. **Only ever ingest the customer's own signed contract. Never generate, host, or pre-fill blank C.A.R. (California Association of Realtors) forms.** Why: reading a signed copy is permitted; reproducing blank copyrighted forms is not.
2. **Never touch money movement or wiring instructions.** Why: wire fraud is the top loss vector in real estate closings; automating it is unacceptable risk.
3. **A human approves every outbound message. No auto-send, ever.** Why: a wrong message to an outside party is the thing practitioners most fear.
4. **California residential only to start.** Why: each state's forms and deadline rules differ; we get one right first.
5. **Any AI model that sees the documents runs in a no-train / no-retain configuration.** Why: the files contain Social Security numbers and bank details; that data must never be retained or trained on.

## What each rule means in code

### Rule 1 — signed contract only; never blank C.A.R. forms
- **Permitted:** reading, parsing, and extracting from a signed copy the customer supplies.
- **Forbidden:** any code path that outputs a blank or pre-filled C.A.R. form, or the contingency-removal document. No copyrighted form templates in the repo, fixtures, or generated output.
- Auditor flag: **any blank-form generation.**

### Rule 2 — never touch money / wiring
- **Forbidden:** parsing, storing, displaying, transmitting, or acting on wiring instructions or payment details; no feature that initiates, schedules, or confirms a transfer.
- If a document contains wiring info, **do not extract those fields.**
- Auditor flag: **any money/wiring touch.**

### Rule 3 — human approves every send; no auto-send
- Every `Message` moves `draft → approved → sent`. The transition to `sent` requires a recorded human `Approval`.
- There must be **no** code path — scheduler, retry, webhook, or otherwise — that sends without a prior `Approval` row.
- Auditor flag: **any auto-send path.**

### Rule 4 — California residential only
- No multi-state forms, deadline rules, or branching. CA residential only.

### Rule 5 — no-train / no-retain for any model that sees documents
- The Anthropic API key used for extraction must operate under a **confirmed Zero Data Retention agreement** before any real NPI is sent. Verify at Console → Privacy Controls → Data retention. Until confirmed: **synthetic data only.**
- No document content, extracted field, SSN, or bank detail in logs, error messages, test fixtures, or a subagent's context.
- Auditor flag: **any real-NPI leak.**

## The NPI / synthetic-data-only gate

Until Anthropic ZDR is confirmed active — **and forever, for how data is handled** —
no real client email, document, SSN, or bank detail enters the API, test fixtures,
logs, or a subagent's context. All development and tests run on **synthetic emails
and synthetic documents only.**

## Ingestion boundary — dedicated inbox only

- The **only** ingestion entry points in the MVP are: (1) the scoped, dedicated deal address (Postmark inbound parse), and (2) manual upload as a fallback.
- **No personal-mailbox OAuth scanning in the MVP.** Any code path that reaches into a personal inbox is out of scope. Auditor flag: **any ingestion path that isn't the scoped dedicated inbox.**
- Transaction creation from ingestion is **HITL**: nothing commits to the SOR until the TC confirms.
