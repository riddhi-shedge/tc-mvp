# Test Plan — Terra TC Tool (adversarial testing & hardening)

Scope: the California residential Transaction-Coordinator system (FastAPI backend +
React/TS frontend + Supabase + Claude document extraction). This plan records the
product contract a "bug" is judged against, the seams under attack, and the scenario
matrix. Findings live in `BUG_BACKLOG.md`, `ADVERSARIAL_FINDINGS.md`,
`RLS_FINDINGS.md`, `CONCURRENCY_FINDINGS.md`; reproducers in `probes/`.

## 1. Product contract (Confirmed vs Assumed)

| Item | Status | Notes |
|------|--------|-------|
| User = a Transaction Coordinator (operator) | Confirmed | Scoped secondary: agents, lender, escrow, title, inspectors, buyer/seller via invite tokens |
| Core loop: doc arrives → detect → extract (Claude, per-field confidence) → **TC confirms (HITL)** → deal + CA timeline → follow-on docs refine/cross-check → drafts need **Approve & Send** | Confirmed | The §11 slice; every step audited |
| Only write path to the SOR is a validated `Payload` | Confirmed | rules/architecture.md |
| Five hard rules (no blank C.A.R. forms · no money/wiring data · no auto-send · CA residential only · ZDR on any model that sees docs) | Confirmed | Inviolable — never traded for a fix |
| Supersession = latest confirmed wins, **now with doc-type precedence** | Confirmed (fixed BUG-01) | counter/CR outrank the PA regardless of upload order |
| Date parsing covers the real formats | Assumed→mostly Confirmed | US MM/DD assumed; EU-format silently drops (BUG-05, accepted) |
| Extraction reliable on messy/scanned PDFs | **Assumed** | P3 AI-eval + messy-PDF probe (#17) |
| RLS actually isolates parties for backend-mediated requests | **Assumed — under probe** | backend uses service-role key (bypasses RLS) → must be app-enforced (RLS probe) |
| Prompt-injection in PDF content can't break the whitelist / doc-type / no-send | **Assumed — under probe** | adversarial probe (#6) |
| Timeline rebuild reconciles (removes stale deadlines) | Confirmed (locked) | test_rerun_removes_a_deadline_no_longer_computed |
| Webhook idempotent to Postmark redelivery | Confirmed (fixed BUG-10) | content-addressed dedup |

## 2. Architecture seams under attack
Three decoupled parts, payloads only: (a) ingestion (detect + extract + HITL confirm),
(b) master/SOR (Supabase; supersession, audit, RLS), (c) compliance/timeline (verified
CA rules; API-only). Highest-leverage seams: the `Payload` contract; `_effective_fields`
resolution; `write_payload` flag eval; the extractor model calls; the timeline gate +
date parser; the confirm `claim()`; RLS + invite tokens; the Postmark webhook.

## 3. Scenario matrix (category → status)

| Category | Representative scenarios | Status |
|----------|--------------------------|--------|
| Functional / sequential | full multi-doc deal; counter→CR→preapproval→prelim→inspections in varied orders | existing 400+ tests; happy path green |
| Supersession / state | re-upload PA after counter; unconfirmed counter; CR then all-cash; provenance | **swept** (BUG-01 fixed + tests) |
| Parsing / boundary | money k/m/b; ambiguous/EU dates; unit-prefix addresses; APN separators | **swept** (BUG-02/03/04 fixed; BUG-05 triaged) |
| Reconciliation | re-run with fewer deadlines removes stale ones | **verified + locked** |
| Idempotency / repetition | duplicate webhook; double-confirm | **swept** (BUG-10 fixed; claim() under concurrency probe) |
| Adversarial / injection / privacy | PDF-content injection vs §5 whitelist; doc-type spoof; money/wiring smuggling; no-auto-send | **P2 probe running (#6)** |
| Authz / multi-tenant | cross-party/cross-deal IDOR; invite-token replay/expiry; service-role vs RLS | **P2 probe running (#11)** |
| Concurrency / reliability | claim() TOCTOU; concurrent payloads/compliance runs; Anthropic/Supabase/storage failures | **P2 probe running (#10)** |
| AI reliability | extraction accuracy vs ground truth; consistency; calibration; routing/cost | **P3 (next)** |
| Messy inputs | 0-byte / non-PDF / password / scanned / multi-doc / huge PDFs; zero-field extraction | **P3 / probe #17 (next)** |
| UX / silent success | build-that-does-nothing; invisible state; prototype-data confusion | partially swept; #14 next |

## 4. Environment constraints (honest)
- CAN: all logic via the fake extractor + InMemoryRepo; the running API locally; frontend
  build/typecheck; bounded real-model evals; failure injection via fakes.
- CANNOT (without setup): true production concurrency/load (simulate only); real Postmark
  inbound (simulate the webhook); live RLS on the hosted project unless the skipped
  DB-integration suite is run with env. Real client-doc extraction is forbidden (ZDR).
- Cost gate: real Anthropic calls cost money — batched/capped; fakes by default.

## 5. Definition of done
Every confirmed bug has a reproducer + a failing→green regression test; findings triaged
Must-fix / Should-fix / Consider / Accept / Won't-fix; the five hard rules re-checked by
`compliance-auditor` on any change touching ingestion/extraction/sending/RLS/audit; full
suite + ruff + frontend build green; `EXECUTIVE_SUMMARY.md` states the readiness verdict
and what to change next, including what could not be tested and how to test it later.
