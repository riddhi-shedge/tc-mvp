# Bug Backlog — prioritized, evidence-backed

Reproduce all via `testing/probes/logic_probes.py` (deterministic, no API cost):
`cd backend && PYTHONPATH=. .venv/bin/python ../testing/probes/logic_probes.py`

| ID | Sev | Freq | Conf | Title | Status |
|----|-----|------|------|-------|--------|
| BUG-01 | **P1** | Occasional | High | Re-uploading the PA silently reverts a counter offer's price | ✅ FIXED |
| BUG-02 | **P2** | Occasional | High | Money parser misreads `$1.8M` / `$900k` → false "insufficient loan" critical flag | ✅ FIXED |
| BUG-03 | P3 | Occasional | High | Party dedup misses punctuation variants (`Belana A` vs `Belana A.`) → duplicate parties | ✅ FIXED |
| BUG-04 | **P2** | Occasional | High | Inspection address match breaks on a unit prefix → false "address mismatch" flag | ✅ FIXED |
| BUG-05 | P3 | Rare | Med | European-format date (`13/01/2025`) silently yields no deadline (no flag) | Consider |

**Fix commit:** all of BUG-01…04 fixed with failing→green regression tests
(`test_supersession`, `test_preapproval`, `test_parties`, `test_inspection`) + the
`_effective_fields` rank fix threaded through all 5 call sites (deal view, board,
and the preapproval/prelim/inspection validators). Independently reviewed by the
`code-reviewer` subagent, which caught two `_addr_core` regressions (whole-word
`\b` for unit keywords so "Stevens"/"North" survive; `#`-house-number preserved)
and the incomplete call-site threading — all addressed before commit.

---

## BUG-01 — Re-uploading the PA reverts a counter offer (P1)
**Evidence:** probe HOTSPOT 1 — PA $1.8M → seller counter $1.9M (effective $1.9M ✓) → re-upload PA $1.8M ⇒ effective reverts to **$1.8M**.
**Root cause:** `_effective_fields` resolves by `(confirmed, created_at)` only — no doc-type precedence. A PA written *after* a counter has a newer `created_at`, so it wins. A counter is a *later agreement* that changed the terms; re-uploading the PA must not undo it.
**Fix:** rank resolution by `(confirmed, source-precedence, created_at)` where counter offers + contingency removal outrank the PA. Resolve source doc-type per field via `payload_id → document.doc_type` (read-time join; no schema change — respects no-DDL). Keeps "unconfirmed counter never wins" (confirmed dominates rank).

## BUG-02 — Money parser misreads suffixed amounts (P2)
**Evidence:** `_parse_money("$1.8M") == 1.8`, `_parse_money("$900k") == 900`.
**Impact:** a preapproval letter stating "$1.8M" parses as 1.8 < the PA loan → **false critical** `preapproval_insufficient` flag ("not approved for enough"). Also corrupts any money compare.
**Fix:** parse an attached `k/m/b` suffix (no-space, word-boundary safe so "1,800,000 mortgage" is not multiplied).

## BUG-03 — Party dedup misses punctuation variants (P3)
**Evidence:** `party_key("lender","Belana A")` ≠ `party_key("lender","Belana A.")`.
**Impact:** the same person from two documents → two `lender`/inspector parties.
**Fix:** strip `.`/`,` in `party_key` normalization before compare.

## BUG-04 — Inspection address match breaks on unit prefix (P2)
**Evidence:** `_addr_core("Unit 5, 21989 McClellan Rd") == "unit 5"` (splits on first comma) ≠ `"21989 mcclellan"`.
**Impact:** false `inspection_address_mismatch` warning on any unit/apt-prefixed address.
**Fix:** strip leading unit/apt/suite tokens; pick the comma-segment carrying the house number.

## BUG-05 — European-format date silently drops a deadline (P3, Consider)
**Evidence:** `_parse_date("13/01/2025") is None` (correct — no misparse), but the deal then computes **no** deadline for that field with **no** warning.
**Assessment:** the non-misparse is good; the silent drop is the concern. Consider a "couldn't read this date" flag rather than a silent no-op. Low frequency (US MM/DD is the norm). Needs a product decision before building.

---

## Sweep #2 findings (state / idempotency / reconciliation)

### BUG-10 — Duplicate Postmark inbound creates a duplicate inbox item (P2, Must-fix)
**Evidence:** `postmark_inbound_webhook` (routes.py) calls `inbox.add_item` on every
delivery with NO idempotency key — `PostmarkInbound` doesn't even model `MessageID`.
Postmark inbound is at-least-once and retries on slow/errored endpoints, so a
redelivery makes a SECOND identical pending item. The downstream `claim()` guard
only stops re-confirming the SAME item — two items from duplicate deliveries can
each be confirmed → **two deals / two payloads for one email**.
**Fix (no-DDL):** before insert, dedup against an existing un-handled item
(pending/needs_manual/processing) with the same (from_email, subject,
attachment_name, attachment_size, attachment_count); return it idempotently.
**Status:** ✅ FIXED — **content-addressed** dedup (no schema change). The attachment is
stored at `email/{sha256(bytes)}/{filename}`, and the webhook absorbs a redelivery only
when the EXACT stored bytes already have an item (`find_duplicate_by_storage_path`).
Regression tests: `test_duplicate_postmark_delivery_is_idempotent`,
`test_a_distinct_email_is_not_deduped`, `test_dedup_key_is_content_addressed_...`.
**Reviewer-driven rework:** the code-reviewer flagged that my first (natural-key) attempt
could *silently drop* a genuinely different document (no-attachment emails, generic
scanner filenames on the shared inbound address) — worse than the duplicate it prevented.
Content-addressing eliminates that: different bytes → different path → always a new item.
An `info` log fires on every absorb (auditable). Also closes the quick-confirm reopening
(match is not status-scoped). **Residual (documented, MVP-acceptable):** a truly
simultaneous double-delivery TOCTOU race, and same-bytes/different-filename → two items
(errs safe: a recoverable duplicate, never a drop). A `source_message_id` unique index
(needs a migration) would close the race exactly.

### Hotspot #4 — Timeline reconciliation — CLEARED ✅
Re-running compliance with FEWER deadlines DELETES the now-stale deadline/task/flag
(apply_compliance_result lands the new run, then deletes prior-run compliance rows).
Locked in by new `test_rerun_removes_a_deadline_no_longer_computed`.

### Hotspot #3 — Counter-chain termination — CLEARED (no infinite loop)
`evaluate_counter_flags` raises an ADVISORY `counter_chain` warning ("upload the
further counter") — there is no code loop; the TC drives each upload. Not a defect.

## P2 multi-agent probe findings (adversarial / RLS / concurrency)
Full detail in `ADVERSARIAL_FINDINGS.md`, `RLS_FINDINGS.md`, `CONCURRENCY_FINDINGS.md`.

### Fixed this batch
- **BUG-11 (P1, concurrency #1) — PA-wipe on a failed re-write** ✅ FIXED. `write_payload`
  deleted the prior PA *inside* the compensated try; a later failure then deleted the new
  doc too → deal with ZERO purchase agreements + no §5 fields. Moved the supersede to AFTER
  the try succeeds ("land the new, then remove the old", like `apply_compliance_result`): a
  mid-write failure now leaves the old PA intact; a failed delete leaves two PAs (recoverable,
  precedence-resolved) — never zero. Test: `test_reupload_leaves_exactly_one_purchase_agreement`.
- **BUG-12 (P2, adversarial #4) — lender_contact_email/phone not on the §5 whitelist** ✅ FIXED.
  The extractor creates these from a preapproval's loan officer, but they were off-whitelist →
  the whole payload 422'd (silent feature break). Added both (mirroring buyer/listing agent
  email+phone). Test: `test_lender_contact_email_and_phone_are_accepted`.

### Confirmed, queued (need careful design / own reviewed commit)
- **BUG-13 (P1, concurrency #2) — concurrent compliance runs delete each other's rows.**
  `apply_compliance_result` inserts run_id then deletes `!= run_id`; two overlapping runs
  (cron sweep vs. the "Build timeline" tap) mutually delete → torn/empty timeline. No lock.
  Fix options: a `pg_advisory_xact_lock` on the transaction_id, or serialize runs per deal.
- **BUG-14 (P2, adversarial #3) — wiring/PII smuggled into a whitelisted field VALUE.**
  The payload route checks the money regex on `f.name` only, not `f.value` (a naive value
  scan would false-reject "Wells Fargo **Bank**" / an APN / a phone). Needs a TARGETED value
  guard (SSN pattern + routing/IBAN/SWIFT/ABA-label-near-digits) with false-positive tests.
  Low exfil risk (no auto-send; TC-review; at-rest only) but a Rule-5 hardening.
- **BUG-15 (P2, RLS F2) — tier confusion:** `require_party` ignores tier, so a read-only
  `collaborator` can WRITE via `POST /party/documents` (scoped to their own deal → integrity
  gap, not cross-tenant leak). Add a tier gate on party write routes.
- **BUG-16 (P2, concurrency #4/#5) — orphans + retry-dup:** compensation deletes only the
  document, leaving spurious risk_flags/parties; and the route's write_payload + derive_parties
  + derive_tasks are un-compensated, so a retry re-inserts (no unique on `documents.external_ref`).
- **BUG-17 (P2, concurrency #3) — stuck 'processing':** a non-graceful crash between `claim()`
  and `release()` leaves an inbox item stuck in `processing` forever (drops from `list_open`).
  Needs a reaper / timeout to reclaim. (claim() itself is a correct atomic CAS — no TOCTOU.)
- **BUG-18 (P2, concurrency #6) — lost update on task completion** across a compliance re-run
  (reads prior status, deletes, re-inserts as pending — a party's "done" in that window is lost).

### Cleared / accepted
- **Doc-type + signature spoofing (adversarial #2, P1-theoretical):** the §4 guard trusts the
  model's self-reported `doc_looks_like`/`signature_indicators`; PDF-content injection targets
  those. **Backstop:** the TC picks the doc-type in the HITL confirm, so this is bounded, not
  a silent bypass. Needs a live-model run to prove (→ P3 injection eval). Consider a corroborating
  deterministic check.
- **§5 whitelist enforcement — VERIFIED SOLID** (3 layers: enum-constrained output, post-filter,
  master 422). No money/wiring/SSN field NAME can reach the SOR.
- **No-auto-send — VERIFIED SOLID.** No mailer in the extract/confirm path; drafts are `status=draft`;
  the only send is the human-authenticated `approve_and_send` behind a fail-closed allowlisted mailer.
- **Cross-party/cross-deal isolation — VERIFIED enforced in app code** (party_id/transaction_id from
  the signed admin-set JWT, never client input; repo double-scopes). No P0/P1 IDOR.
- **RLS F1/F3/F4, Anthropic/Supabase/storage failure handling:** RLS proven only by 22 skipped
  DB-integration tests (CI gap); invite tokens lack revocation (P3); shared compliance token is
  URL-enumerable (P3); dependency failures raise clean 5xx before any SOR write (handled well).

## Reviewer follow-ups (low severity — triaged, not yet built)
- **BUG-06 (Accept):** `_parse_money` treats `-$1,800,000` / `($1,800,000)` as positive. Domain amounts are non-negative; accept.
- **BUG-07 (Consider):** `.5M` (leading-dot, no integer) mis-scales to 5,000,000. Rare OCR shape; low priority.
- **BUG-08 (Consider):** `_effective_fields` ties (same confirmed+rank+`created_at`, e.g. a single bulk insert where Postgres `now()` is txn-scoped) resolve by unspecified DB row order — no `ORDER BY`. Pre-existing; add an explicit tiebreak (e.g. `id`) if it ever bites.
- **BUG-09 (Won't-fix):** `party_key` now collapses `"Smith, John"` and `"Smith John"`. Names don't arrive comma-inverted in this system; accept.

## Passed probes (no bug)
- Unconfirmed counter correctly does NOT supersede.
- Date parser rejects `13/01/2025`, `March 2025`, `TBD` (→ None) rather than misparsing.
- Detector rejects `encounter_notes.pdf` as a counter (no false substring match).
