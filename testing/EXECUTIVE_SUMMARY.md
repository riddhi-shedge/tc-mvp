# Executive Summary — Adversarial Testing & Hardening of the Terra TC Tool

_A California residential Transaction-Coordinator system (FastAPI + React/TS + Supabase +
Claude document extraction). This summarizes a focused hardening pass: automated logic
sweeps + a multi-agent security/reliability probe, with fixes shipped as they were found._

## Readiness verdict

**Meaningfully hardened; core guarantees verified; extraction quality strong on synthetic
evals; the main residual is applying two shipped migrations and broadening coverage.** The
extraction→confirm→SOR→timeline pipeline is sound and its safety controls are real (not just
prompt-level). No cross-tenant data leak and no auto-send path exist. Live-model evals show
15/15 extraction accuracy, semantically consistent runs, and 6/6 injection defenses holding
on the synthetic corpus. The two concurrency P1s (BUG-13, BUG-17) are now FIXED but ship with
DB migrations (`20260820000010/11`) that must be applied to the hosted DB before deploy.

## What was done
- **P1 — automated logic sweep** (deterministic, no API cost): a probe harness
  (`probes/logic_probes.py`) against `InMemoryRepo` + the pure functions.
- **P2 — multi-agent probes**: three parallel adversarial/security agents (prompt-injection,
  authorization/RLS, concurrency/reliability), each verified against the code and reproduced.
- **Every fix** landed with a failing→green regression test; the two SOR-integrity changes
  and both webhook-dedup attempts went through an independent `code-reviewer` pass whose
  findings were folded back in. **426 backend tests pass; ruff clean.** 11 commits shipped.

## Bugs found & FIXED (14 — including 4 P1s)
| ID | Sev | What | 
|----|-----|------|
| BUG-01 | **P1** | Re-uploading the PA silently reverted a counter's price → doc-type precedence in supersession |
| BUG-11 | **P1** | A failed PA re-write could leave a deal with ZERO purchase agreements → supersede moved out of the compensated try + guarded |
| BUG-13 | **P1** | Concurrent compliance runs deleted each other's rows (torn timeline) → per-deal fenced mutex + stale reclaim |
| BUG-19 | **P1** | A multi-document email silently dropped all attachments but the first → one queued item per attachment |
| BUG-17 | P2 | A crashed confirm stranded an inbox item in `processing` → `claimed_at` + self-healing reaper |
| BUG-24 | P2 | No size ceiling before the model call → >25 MB routes to needs_manual (cost/DoS) |
| BUG-02 | P2 | `$1.8M`/`$900k` misparsed → false "insufficient loan" critical flag |
| BUG-04 | P2 | Unit-prefixed address → false "address mismatch" flag |
| BUG-10 | P2 | Duplicate Postmark delivery → duplicate deal → content-addressed idempotency (data-loss-safe) |
| BUG-12 | P2 | `lender_contact_email/phone` off-whitelist → preapproval payloads 422'd |
| BUG-14 | P2 | Wiring/SSN could be smuggled into a field VALUE → targeted Rule-2 value guard |
| BUG-03 | P3 | Party dedup missed punctuation variants → duplicate parties |
| #4 / #3 | — | Timeline reconciliation & counter-chain termination verified correct + locked with tests |

## Verified SOLID (the important negatives)
- **§5 field whitelist** is enforced in three layers (enum-constrained output → post-filter →
  master 422). No money/wiring/SSN field *name* reaches the SOR — and now no such *value* either.
- **No auto-send.** No mailer in the extract/confirm path; drafts are `status=draft`; the only
  send is the human-authenticated `approve_and_send` behind a fail-closed, allowlisted mailer.
- **Cross-party / cross-deal isolation** is enforced in app code (party_id/transaction_id come
  from the signed admin-set JWT, never client input; the repo double-scopes). No IDOR found —
  important because the backend uses the service-role key that *bypasses* Postgres RLS.
- **Dependency failures** (Anthropic 429/500/timeout/refusal, storage 503) raise clean 5xx
  *before* any SOR write; the confirmation gate blocks the scheduler from building on unconfirmed state.

## Open — needs an OWNER DECISION
1. **BUG-13 (P1) — concurrent compliance runs delete each other's rows.** Two overlapping
   `apply_compliance_result` runs (a cron sweep vs. a manual "Build timeline" tap) mutually
   delete → a torn/near-empty timeline. **Clean fix needs a DB migration** (a `pg_advisory_xact_lock`
   RPC keyed on the transaction, or a `unique(transaction_id, compute_key)` + upsert). Decision:
   approve the migration, or (interim, no migration) ensure the cron never overlaps a manual run.
   _Reachability note: if the cron sweep isn't deployed, the only trigger is the one-at-a-time
   manual tap, making this latent rather than active — worth confirming._
2. **BUG-15 (product call) — should a read-only `collaborator` be able to `POST /party/documents`?**
   Reclassified from a bug: receiving-end vendors must upload reports, and TC HITL gates any
   party upload. Only restrict if the spec means collaborators are strictly read-only.

## Queued P2 (real, mostly need a migration or a small design)
- **BUG-16** compensation deletes only the document → orphan flags/parties; and the write path's
  `write_payload + derive_parties + derive_tasks` are un-compensated → a retry re-inserts (no
  `unique` on `documents.external_ref`). _Fix: unique constraint (migration) + idempotent tail._
- **BUG-17** a crash between `claim()` and `release()` strands an inbox item in `processing`
  forever. _Fix: a reaper/timeout (likely needs a `claimed_at` column)._ (claim() itself is a
  correct atomic CAS — no TOCTOU.)
- **BUG-18** a compliance re-run can revert a party's just-marked-`done` task (read→delete→re-insert
  window). _Fix: carry status via upsert keyed on compute_key rather than delete+recreate._

## AI evals — DONE (bounded live-model, synthetic) — see `AI_EVALUATION.md`
- **Accuracy 15/15** on the synthetic signed PA; **semantically consistent** across runs (only
  cosmetic "17 days" vs "17" variation, normalized downstream); **6/6 injection defenses held**
  (a PA carrying "ignore instructions / leak wiring / flip all_cash / reclassify" was resisted,
  and the structural whitelist + `_WIRING_VALUE` guards would block anything that slipped).
- Still to broaden: ground-truth corpus for the OTHER doc types (counters/CR/preapproval/prelim/
  inspections), confidence calibration, and more injection payload variants (single stochastic run).

## Not yet tested — and how to test later
- **Messy-PDF robustness (#17):** 0-byte / non-PDF / password / scanned / multi-doc / huge files.
- **Live RLS:** proven today only by 22 skipped DB-integration tests (a CI gap — the RLS policies
  aren't exercised because the backend bypasses them). Run that suite against a Supabase test env.
- **True concurrency/load:** simulated only here; needs a real multi-worker load test.
- **Regex/heuristic limits:** the BUG-14 value guard and BUG-02 money parser are heuristics
  (won't catch every wiring format / "1.8 million" written out) — a dedicated compliance audit
  of `_WIRING_VALUE` is a recommended follow-up.

## Robustness pass (C probe) — DONE — see `UX_ROBUSTNESS_FINDINGS.md`
Fixed the P1 (BUG-19 multi-attachment loss) + BUG-24 (size cap). Open, triaged: precheck runs
for PAs only (BUG-23), a zero-field PA makes a hollow deal (BUG-22), a success toast on an empty
timeline build (BUG-20, frontend), "Confirm all" can bypass low-confidence review (BUG-21,
frontend), concatenated-doc mis-extract (BUG-25), prototype-data labels (BUG-26). Gracefully
handled already: 0-byte / encrypted / truncated / non-PDF all route to needs_manual.

## Sprint recommendation
- **NOW:** apply the two shipped migrations (`20260820000010/11`) to the hosted DB before the
  next deploy; decide BUG-15 (collaborator upload — product call).
- **NEXT:** run the precheck for ALL doc types (BUG-23) + the zero-field guard (BUG-22); the
  frontend honesty fixes (BUG-20/21); BUG-16/18 crash-safety (unique `external_ref` + task upsert).
- **LATER:** wire the skipped RLS DB-integration suite into CI against a test project; a real
  load test; broaden the AI-eval ground-truth corpus to the other doc types + calibration;
  invite-token revocation (RLS-F3) and a per-transaction compliance token (RLS-F4).
- **DON'T BUILD YET:** a bespoke PII/wiring ML classifier — the targeted regex + HITL + no-send
  cover the realistic risk; revisit only if real documents show novel smuggling.
