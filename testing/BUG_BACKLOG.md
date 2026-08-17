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

## Reviewer follow-ups (low severity — triaged, not yet built)
- **BUG-06 (Accept):** `_parse_money` treats `-$1,800,000` / `($1,800,000)` as positive. Domain amounts are non-negative; accept.
- **BUG-07 (Consider):** `.5M` (leading-dot, no integer) mis-scales to 5,000,000. Rare OCR shape; low priority.
- **BUG-08 (Consider):** `_effective_fields` ties (same confirmed+rank+`created_at`, e.g. a single bulk insert where Postgres `now()` is txn-scoped) resolve by unspecified DB row order — no `ORDER BY`. Pre-existing; add an explicit tiebreak (e.g. `id`) if it ever bites.
- **BUG-09 (Won't-fix):** `party_key` now collapses `"Smith, John"` and `"Smith John"`. Names don't arrive comma-inverted in this system; accept.

## Passed probes (no bug)
- Unconfirmed counter correctly does NOT supersede.
- Date parser rejects `13/01/2025`, `March 2025`, `TBD` (→ None) rather than misparsing.
- Detector rejects `encounter_notes.pdf` as a counter (no false substring match).
