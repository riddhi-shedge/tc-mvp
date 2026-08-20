# Concurrency & Failure-Handling Findings — TC-MVP backend

Scope: race conditions and dependency-failure handling in ingestion + master + compliance.
Method: code reading only (no live fault injection). Each finding is tagged **CONFIRMED**
(provable from the code/schema as written) or **THEORETICAL** (real code path, but needs a
specific failure/interleaving window to trigger). No source was modified.

Root-cause pattern across almost every finding: **there is no locking or DB-level uniqueness
anywhere** (`grep` for `for update / advisory / unique / Lock` finds only `auth._jwks_lock` and
thread-local clients; the only `unique` in the schema is `properties.transaction_id`). Every
"idempotent" / "compensated" claim is implemented as an application-level read-then-write, which
is safe single-threaded and racy under concurrency. PostgREST gives no cross-table transaction,
so multi-row writes are compensated by hand.

---

## Q1 — Inbox confirm `claim()` / `release()` / `mark_confirmed()`

**Files:** `backend/app/ingestion/inbox_repo.py:225-251` (`_transition`, `claim`, `release`,
`mark_confirmed`); `backend/app/ingestion/routes.py:646-778` (`confirm_inbox_item`).

**1a. `claim()` IS atomic — NOT a TOCTOU. Severity P3 (informational).** — CONFIRMED.
`claim()` calls `_transition(item_id, "pending", {"status": "processing"})`, which issues a single
`UPDATE ingestion_inbox SET status='processing' WHERE id=? AND status='pending' RETURNING *`
(inbox_repo.py:226-234). This is a genuine conditional-update compare-and-swap. Under Postgres
READ COMMITTED two concurrent confirms serialize on the row lock; the loser re-evaluates
`status='pending'` against the already-updated row, matches 0 rows, gets `[]` → `None` → HTTP 409
"already handled" (routes.py:677-678). So two concurrent confirms can **not** both pass.
Note: the earlier `get()` + status checks at routes.py:646-661 are themselves a read-then-check
TOCTOU, but they are harmless because `claim()` is the real gate that follows.

**1b. Crash between `claim()` and `release()`/`mark_confirmed()` → item stuck in `processing`
forever. Severity P2.** — CONFIRMED.
On any *exception*, routes.py:767-769 (`except Exception: inbox.release(item_id); raise`) returns
the item to `pending`, so ordinary failures self-heal. But if the worker dies non-gracefully
(SIGKILL/OOM/deploy/pod eviction) between `claim()` (routes.py:677) and either `release()` or
`mark_confirmed()` (routes.py:771), nothing runs the release. There is **no reaper, TTL, or
stale-claim reclaim**. `list_open()` only returns `pending`+`needs_manual` (inbox_repo.py:198-206),
so the orphaned `processing` item silently disappears from the TC's queue and the document never
reaches a deal. Acceptable-MVP-limitation only if a manual DB fix is considered acceptable ops.

**1c. `mark_confirmed()` after a committed master write.** — CONFIRMED, low impact.
`mark_confirmed()` (routes.py:771) runs *after* the try/except, so a successful master write
followed by a `None` return (item no longer `processing`) raises 409 while the payload is already
in the SOR. In practice unreachable except under crash-recovery/manual tampering because nothing
else can transition a `processing` item. Defensive; P3.

---

## Q2 — `write_payload` compensation (`backend/app/master/repo.py:1037-1330`)

Compensation = **delete the `documents` row** (repo.py:1328), which cascades to `payloads` and
`extracted_fields` (FK `on delete cascade`, migration `20260712000001_sor_core.sql:74,82`). Those
three ARE cleaned up. The problem is everything else the method writes is keyed to
`transaction_id`, not to the document.

**2a. Orphaned risk_flags and parties survive compensation. Severity P2.** — CONFIRMED.
`risk_flags` (repo.py:1116, 1163, 1192, 1229, 1258, 1304) and `parties` (repo.py:1290 via
`create_party`) are keyed by `transaction_id` (`risk_flags`/`parties` cascade from *transaction*,
not from *document* — sor_core.sql:115, and `parties` similarly). If any step *after* the first
flag/party insert throws (e.g. a Supabase blip on a later `.insert()`, the archived-reopen update
at repo.py:1324, or an insert loop that partially completed), the `except` at repo.py:1327 deletes
only the document. The already-inserted risk flags and parties are left orphaned on the deal — a
spurious "counter not accepted" critical flag or a duplicate inspector party can persist even
though the payload that produced it was rolled back.

**2b. PA supersede can destroy the deal's only purchase agreement. Severity P1 (narrow window).**
— CONFIRMED code path / THEORETICAL trigger.
For a purchase agreement, repo.py:1143-1146 deletes *all prior* PA documents (cascading their
payloads + §5 fields) **inside** the try block, before it returns. If any step *after* line 1146
throws (the `counter_pending` insert at 1150-1180, the archived-reopen at 1324, or any transient
Supabase error in that span), the `except` compensation deletes the **new** document too. Net
result: the old PA is already gone and the new one is compensated away → the deal is left with **no
purchase agreement and no §5 fields at all**, silently. This is the most damaging single-payload
failure mode.

**2c. Non-atomic tail in the route duplicates on retry. Severity P2.** — CONFIRMED.
`master/routes.py:1278-1281` calls `repo.write_payload(...)`, then `derive_parties_from_fields`,
then `derive_tasks_from_fields` as **three separate, un-compensated** operations. If a `derive_*`
call throws (Supabase outage), the payload is already committed but the endpoint returns 500 →
ingestion's `confirm_inbox_item` sees status ≥ 400 → `release()`s the inbox item → the TC retries →
`write_payload` runs **again**. `documents.external_ref` (= `inbox-{item_id}`) is stable but has
**no unique constraint** (sor_core.sql:64) and there is no dedup-by-external_ref, so the retry
inserts a **second** document/payload/fields/flags/parties. For a PA the supersede-delete (2b)
masks this; for a counter/disclosure/inspection it produces **duplicate documents and duplicate
risk flags** (e.g. the counter "fell-through" critical flag inserted twice).

**2d. Two concurrent payloads for one transaction mutually delete. Severity P2.** — CONFIRMED
possible / THEORETICAL (concurrent PA writes to one deal are rare with a single TC).
Two concurrent PA writes each insert their own document, then each runs the supersede-delete
`documents WHERE doc_type='purchase_agreement' AND id != own` (repo.py:1144-1146). A deletes B's
brand-new document; B deletes A's. Depending on interleave the deal can end with zero PAs, or with
a payload whose fields were cascaded out from under it. No serialization prevents it.

---

## Q3 — `apply_compliance_result` run reconciliation (`repo.py:2076-2225`)

Pattern (repo.py:2103-2209): mint `run_id`, insert the whole new run tagged `compliance_run_id`,
then delete prior compliance rows `WHERE generated_by='compliance' AND compliance_run_id != run_id`.
No lock, no `unique(transaction_id, compute_key)` (schema has none).

**3a. Two concurrent runs on one deal delete each other's rows. Severity P1 if concurrent runs can
occur.** — CONFIRMED possible by code reading.
Run A inserts `run_A` rows; run B inserts `run_B` rows. A's reconciliation delete (repo.py:2203-2209)
removes everything `!= run_A` — i.e. B's just-inserted deadlines/tasks/flags/draft messages — and
B's delete removes everything `!= run_B`, i.e. A's. Interleaving yields a torn timeline (some of
each run), or near-empty, or double-counted deadlines depending on ordering. Can they overlap?
The daily sweep (`scheduler.run_all`, scheduler.py:37-66) is sequential in one process, BUT the
on-demand "Build timeline" endpoint spawns a **separate** `subprocess` compliance run per TC tap
(routes.py:394-401), so a manual build racing the cron sweep, a double-click, or two TCs on the
same deal produces two concurrent `apply_compliance_result` calls. Realistic → treat as P1/P2.

**3b. Lost update: a party's task completion is silently reverted by a concurrent re-run.
Severity P2.** — CONFIRMED.
`apply_compliance_result` reads prior compliance tasks (`status`, `assigned_party_id`) at
repo.py:2093-2101 into `prior_task_state`, carries those values onto the new rows
(repo.py:2130-2144), then deletes the old rows at the end (repo.py:2203-2206). If a receiving-end
party marks a compliance task `done` (via `set_task_status`, repo.py:1755) **after** the read at
2093 but **before** the delete at 2203, the new run recreated that task with the stale `pending`
status and the old `done` row is deleted → the completion is lost. The window is the entire apply
duration. The in-code comment ("preserve completion across re-runs", repo.py:2138) holds only
absent a concurrent change.

---

## Q4 — Dependency-failure handling (Anthropic / Supabase / storage)

**4a. Anthropic errors are handled cleanly — GOOD, acceptable MVP.** — CONFIRMED.
Every extractor call wraps `client.messages.create` in `try/except anthropic.APIStatusError`
(→ `ExtractionFailed("... HTTP {code}")`) and `APIConnectionError` (→ unreachable), and treats
`stop_reason == "refusal"` and unparseable JSON as `ExtractionFailed`
(extractor.py:374-389, 421-433, 463-476, 512-525). In routes, `ExtractionFailed` → HTTP 502 and
`ExtractionBlocked` (ZDR gate) → 503 (routes.py:388-391, 426-429, etc.). Crucially, extraction runs
**inside** the post-claim try (routes.py:697-723), so a 429/500/timeout/refusal raises **before any
SOR write**, the `except` releases the inbox item, and nothing is half-written. The Anthropic client
uses `timeout=120, max_retries=1` (extractor.py:350 etc.) — one SDK retry with backoff, idempotent
because extraction is read-only. So a caller/TC can safely retry.
Minor P3: a 429 is mapped to a generic 502 with no `Retry-After`, so rate-limit vs. server error is
indistinguishable to the caller — no state impact.

**4b. Supabase failures are NOT wrapped, and compensation is not durable under the outage that
triggers it. Severity P2.** — CONFIRMED.
Outside `store_attachment`/`download_attachment` (which wrap upload/download in
`StorageUnavailable`, inbox_repo.py:122-137, 192-196), **no** Supabase `.execute()` in `repo.py` or
`inbox_repo.py` is wrapped. A mid-sequence DB failure in `write_payload` raises a raw exception
caught by the bare `except Exception:` at repo.py:1327, which then issues **another Supabase call**
(the compensating `documents.delete`) — during a real Supabase outage that delete **also fails**, so
compensation is silently ineffective, the partial rows persist, and a 500 propagates to ingestion →
release → retry → duplicates (see 2c). The same flaw applies to `apply_compliance_result`'s
compensation delete (repo.py:2194-2197) and to `create_transaction`/`create_stub_timeline`. The
compensation model assumes the DB is up at exactly the moment it just failed.

**4c. Storage 503 handled well — GOOD.** — CONFIRMED.
`StorageUnavailable` → HTTP 503 on the webhook (so Postmark redelivers, routes.py:162-166) and on
every confirm-time download (routes.py:341-344, 375-378, etc.). Uploads are content-addressed with
`upsert=true` (inbox_repo.py:127-133) and duplicate deliveries are absorbed by
`find_duplicate_by_storage_path` (routes.py:174-185), so redelivery is idempotent.

**Idempotency summary:** extraction retry = idempotent; **payload write = NOT idempotent** (dup
documents/flags, 2c); **compliance apply = idempotent only single-threaded** (torn/dup under
concurrency, 3a).

---

## Q5 — Compliance scheduler running mid-confirm

**Files:** `scheduler.py`, `compliance/service.py:47-62`, gate at `repo.py:2080-2089`.

**5a. The §11 confirmation gate protects the scheduler from half-written state — GOOD, not a
defect.** — CONFIRMED.
`apply_compliance_result` re-reads the deal's fields and raises `DeadlineFieldsUnconfirmed` (→ HTTP
409) if any deadline-driving §5 field is missing or unconfirmed (repo.py:2080-2089; mapped at
routes.py:1026-1033). Fresh extraction lands fields as `confirmed=False` (extractor output is
unconfirmed until the TC confirms), so a deal that is mid-confirm/half-written has unconfirmed
deadline-driving fields and the compliance run is **blocked** rather than building a timeline off
partial data. Same gate guards `create_stub_timeline` (repo.py:1409-1411) and the on-demand build
(routes.py:383-392).

**5b. Residual read/apply skew. Severity P3.** — THEORETICAL, self-correcting.
`run_for_transaction` reads deal state over HTTP at one instant (service.py:57) and applies later
(service.py:61). `write_payload` inserts the `payloads` row (repo.py:1055) *before* the bulk
`extracted_fields` insert (repo.py:1069), so a compliance read landing in that gap could see a
payload with zero/partial fields and mis-evaluate the gate for one run. It self-corrects on the next
sweep, and the fields insert is all-or-nothing per payload, so the exposure is a single stale run,
not corruption.

---

## Severity roll-up

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 2b | PA supersede + compensation can delete the deal's only PA and all §5 fields | P1 | CONFIRMED path / THEORETICAL trigger |
| 3a | Concurrent compliance runs delete each other's rows (no lock/unique) | P1 | CONFIRMED possible |
| 1b | Crash between claim and release → item stuck `processing` forever, no reaper | P2 | CONFIRMED |
| 2a | Orphaned risk_flags/parties survive document-only compensation | P2 | CONFIRMED |
| 2c | Non-atomic route tail → duplicate docs/flags on retry (no external_ref uniqueness) | P2 | CONFIRMED |
| 2d | Two concurrent PA writes mutually delete | P2 | CONFIRMED possible |
| 3b | Lost update: party's task `done` reverted by concurrent re-run | P2 | CONFIRMED |
| 4b | Supabase not wrapped; compensation not durable under the outage it handles | P2 | CONFIRMED |
| 1a | `claim()` is atomic CAS — not a TOCTOU (the good news) | P3 | CONFIRMED (not a defect) |
| 4a/5a | Anthropic errors + §11 gate handled cleanly | P3 | CONFIRMED (not a defect) |
| 1c/4a-minor/5b | Defensive/edge residuals | P3 | mixed |
