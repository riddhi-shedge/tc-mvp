# UX Silent-Failure & Messy-PDF Robustness Findings

Scope: Theme A (#14 silent-success / invisible-state UX) and Theme B (#17 messy-PDF
robustness). Backend `backend/app`, frontend `frontend/src`. Read-only audit; no
source edited. Each finding is tagged CONFIRMED (traced in code) or THEORETICAL
(plausible but depends on runtime/model behavior), with severity P0–P3 and whether
it is a real defect or acceptable MVP behavior.

Severity key: P0 data loss/legal-risk in the common path · P1 real defect likely to
bite · P2 real defect in an edge path · P3 polish / mislabel.

---

## THEME A — Silent-success / invisible-state

### A1. Multiple email attachments → only the first is ingested; the rest are silently dropped — P1, CONFIRMED
`backend/app/ingestion/routes.py:142` — the Postmark webhook takes `body.Attachments[0]`
only. `attachment_count` (line 144) is stored and the Inbox UI shows "(+N more)"
(`frontend/src/screens/Inbox.tsx:187`), but the other attachments are never stored,
never queued, and there is no way to reach them. A single email carrying a PA + counter
+ disclosure yields one inbox item; the other two documents vanish with no error state.
- Repro: POST the postmark webhook with two attachments; only `Attachments[0]` gets a
  `storage_path`; the inbox row shows count 2 but only one document exists.
- Real defect. This is silent data loss of legal documents. The "+N more" label makes
  it worse — it tells the TC more arrived while giving no path to them.

### A2. "Build timeline" shows a success toast even when it builds nothing — P2, CONFIRMED
`build_timeline` returns `{deadlines, tasks, risk_flags}` counts
(`backend/app/master/routes.py:419-424`) whenever the scheduler subprocess exits 0. The
frontend ignores the returned counts and always toasts "Timeline built"
(`frontend/src/screens/Deal.tsx:461-466`, `run(fn, "Timeline built")`). If the
scheduler exits 0 but produces zero deadlines (the exact failure class of the
previously-fixed date-parser bug — an unparseable date that no longer crashes but
yields nothing), the TC sees "Timeline built", the "Ready to build" card stays because
`state.deadlines.length === 0` (Deal.tsx:446), and `DealTimeline` never renders
(Deal.tsx:473). Net: a green success toast with no timeline and no explanation.
- Repro: force the scheduler to return 0 with an unbuildable-but-gate-passing field set;
  observe success toast + unchanged screen.
- Real defect (invisible no-op). Fix direction: have the frontend react to the returned
  `deadlines` count (0 ⇒ warn, not success).

### A3. "Confirm all" bulk-confirms low-confidence fields without the TC ever seeing them — P2, CONFIRMED
Low-confidence (`< 0.7`) fields are surfaced in the amber "Review & verify" panel, but
that list excludes anything already confirmed: `needsReview = fields.filter(f =>
f.confidence < CONF_THRESHOLD && !f.confirmed)` (`frontend/src/screens/ExtractionReview.tsx:124`).
The top-of-card "Confirm all (N)" button (ExtractionReview.tsx:235-239 →
`onConfirmAll`, Deal.tsx:557-565) and the gate card's "Confirm N deadline fields"
button (Deal.tsx:422-440) both POST every unconfirmed `field_id` to
`/fields/confirm` with no confidence gate on the backend
(`backend/app/master/routes.py:317-333`). So a TC can one-tap-confirm a low-confidence
extracted value — including a deadline-driving date that then drives the whole computed
timeline — without ever opening the verify panel. The confidence ring counts confirmed
fields as "verified" (ExtractionReview.tsx:122-135), conflating "human-checked" with
"model-confident".
- Repro: extraction returns a field at confidence 0.5; click "Confirm all"; field is now
  `confirmed=true`, dropped from `needsReview`, and shown as verified.
- Real defect for a HITL system whose whole premise is "never silently guess". At minimum
  "Confirm all" should exclude low-confidence fields or force them through verify.

### A4. Zero-field PA extraction creates an empty deal with a placeholder address and no "couldn't read this" state — P2, CONFIRMED (path) / THEORETICAL (trigger)
`_extract_pa_fields` returns `result.fields` with no guard against an empty list
(`backend/app/ingestion/routes.py:633`). A PA that passes precheck (≥200 text chars),
reads as `purchase_agreement`, and shows signature indicators, but from which the model
maps zero §5 fields (or every value is blank and filtered out in
`parse_extraction_output`, `extractor.py:587-605`), returns `fields = []`. Confirm then
computes `address = "(address pending confirmation)"` (routes.py:725-728), and on a
`new` decision calls `master.create_transaction(... property_address=<placeholder>)` and
writes an empty payload (routes.py:730-752). Result: a real deal is created, the UI
navigates to it (`Inbox.tsx:87 onOpenDeal`), and `ExtractionReview` shows the generic
empty state "No extracted fields yet" (ExtractionReview.tsx:101-107) — never a "we
couldn't read this document" message. There is no zero-field short-circuit to manual
entry the way there is for precheck failures.
- Repro: stub the extractor to return `doc_looks_like=purchase_agreement`,
  `signature_detected=true`, `fields=[]`; confirm as new ⇒ empty deal, placeholder
  address, no error.
- Real defect (edge). Non-PA doc types legitimately attach field-less, but a PA yielding
  nothing should route to the manual-fields fallback, not silently create a hollow deal.

### A5. "My Quarter" presents all-time board figures as this-quarter performance, with a stale hardcoded quarter label — P3, CONFIRMED
`frontend/src/screens/Quarter.tsx:47` computes `closed = deals.filter(d.stage ===
"closed")` with no date filtering, then presents it under "Your quarter" / "Deals
closed" as live quarter data (Quarter.tsx:84-99). The period label is hardcoded
"Q3 2025" (line 72) — stale (today is 2026). So a TC reads all-time closed count/volume
as quarterly. The synthetic pieces (month split, 93% on-time ring, breakdown table) are
correctly chip-labelled "sample", but the headline live figures are mislabelled as
period-scoped.
- Real defect but low impact (self-view only). Fix: filter by close date and derive the
  period label.

### A6. Admin console KPI row is synthetic but not chip-labelled — P3, CONFIRMED
`frontend/src/screens/Admin.tsx` is globally tagged "REMOTE ADMIN · PROTOTYPE"
(line 50) and most cards carry a `chip-sample`, but the top KPI tiles — "Active deals
(org) 31", "Org close rate 91%", "AI recs approved 86%" (Admin.tsx:91-96) — are
hardcoded with no per-tile sample marker, and real captured session errors are merged
into the otherwise-synthetic error feed (Admin.tsx:39-42) so real and fake `TERRA-xxxx`
rows sit together. Low risk because the whole screen is prototype-tagged, but the
unmarked hard numbers can be screenshot out of context.
- Acceptable-ish MVP behavior given the prototype banner; flagged for completeness.

---

## THEME B — Messy-PDF robustness (webhook/upload → precheck → extract → confirm)

Key structural finding first, then the per-input trace.

### B1. Pre-check runs for purchase agreements ONLY; counter / contingency-removal / preapproval / preliminary / inspection go straight to the model with no readability gate — P2, CONFIRMED
`precheck_pdf` is called exclusively in `_extract_pa_fields`
(`backend/app/ingestion/routes.py:606-610`). The other extracting doc-type helpers —
`_extract_counter` (routes.py:359), `_extract_contingency_removal_fields` (399),
`_extract_preapproval` (450), `_extract_preliminary` (499), `_extract_inspection` (531)
— only run `decrypt_pdf` then call the model directly. (POF/disclosure/other skip
extraction entirely, per `test_non_pa_documents_skip_extraction`.) Consequences for the
non-PA extracting types:
- An image-only **scan with no text layer** is NOT caught (inspection & preliminary/title
  reports are very commonly scans) — it reaches the model, which may return empty or
  hallucinated data; a missing inspector party is created silently, no `needs_manual`.
- A **non-PDF renamed .pdf** for these types is base64'd and sent to the model as
  `application/pdf`; the API 400s → `ExtractionFailed` → HTTP 502 (routes.py:388-391 etc.)
  rather than a clean manual-entry state.
- No **page/size cap** protects these calls either (see B6).
- Real defect. The §4 "never guess / route to manual" guarantee is only wired for PAs.

### B2. 0-byte / empty attachment — handled gracefully, CONFIRMED (acceptable)
Webhook: `check_readability` returns "attachment is empty" for `size <= 0`
(`backend/app/ingestion/detector.py:94-95`), so the item is created `needs_manual`
(routes.py:198-199) and confirm is blocked with a 409 pointing at manual-upload
(routes.py:649-657). Manual-upload path can't send empty content (`content_base64`
has `min_length=1`, routes.py:209) and the UI disables upload for a 0-byte file
(`Inbox.tsx:125,364`). Acceptable MVP behavior. Minor gap: the webhook trusts
Postmark's `ContentLength` (metadata), not the actual decoded byte length — a
mislabelled size could slip a tiny/empty body through to confirm-time precheck, which
then catches it as "not a readable PDF" (still graceful).

### B3. Non-PDF renamed .pdf — graceful for PAs, degraded for other types — CONFIRMED
`check_readability` passes anything ending `.pdf` (detector.py:92). For a PA, confirm →
`decrypt_pdf` can't parse it and returns the bytes unchanged (precheck.py:35-36) →
`precheck_pdf` raises inside pypdf and returns "the file is not a readable PDF" /
"could not be parsed as a PDF" (precheck.py:72-75) → structured 422 → manual entry.
Graceful. For non-PA extracting types, see B1 (reaches the model, 502). No crash either
way.

### B4. Password-protected / encrypted PDF — handled gracefully; `decrypt_pdf` is safe on a bad password — CONFIRMED (acceptable)
`decrypt_pdf` wraps `reader.decrypt("")` in `try/except (PyPdfError,
NotImplementedError)` and returns `None` for a real user password
(`backend/app/ingestion/precheck.py:39-43`); an unparseable file returns the original
bytes (35-36). Owner-password-only PDFs (empty user password, common in
zipForm/DocuSign) are unlocked and re-serialized (44-52). A true user-password PDF →
`None` → structured 422 "password-protected — upload an unlocked copy" on every
extracting path (routes.py:600-604, 379-384, 418-423, 468-473, 516-521). `precheck_pdf`
mirrors this (precheck.py:62-69). No crash; safe. Acceptable. (One theoretical: the
`PdfWriter` re-serialize on line 45-50 has no page/size cap — a huge encrypted PDF is
fully rewritten in memory; see B6.)

### B5. Image-only scan, no text layer (`synthetic_scan_no_text.pdf`) — caught for PAs, NOT for non-PA types — CONFIRMED
For a PA, `precheck_pdf` sums extractable chars and, below `_MIN_TEXT_CHARS = 200`,
returns "no usable text layer found (likely an image-only scan) — manual field entry
required" (`backend/app/ingestion/precheck.py:13-14,85-88`); covered by
`test_precheck.py::test_image_only_scan_reports_no_text_layer` and
`test_confirm_extraction.py::test_bad_scan_routes_everything_to_manual`. For inspection
/ preliminary / counter / preapproval / CR there is no precheck (B1), so a scanned copy
of those — which is the common real-world case for inspection reports — silently reaches
the model. Real gap.

### B6. No page-count or byte-size cap before the model call — cost / DoS / memory risk — P2, CONFIRMED
`precheck_pdf` enforces a *minimum* PA page count (`PA_MIN_PAGES`, default 2,
precheck.py:17-18,80-84) but never a *maximum*, and there is no byte-size limit anywhere
in the path: `store_attachment` b64-decodes the whole attachment into memory with no cap
(`backend/app/ingestion/inbox_repo.py:126-141`), `precheck_pdf` extracts text from every
page (precheck.py:71), `decrypt_pdf` may re-serialize the entire document
(precheck.py:44-52), and `extractor.extract` base64-encodes the full PDF into the
request body (`backend/app/ingestion/extractor.py:365-367`) with no guard. A
hundreds-of-pages or very large PDF is therefore fully loaded, hashed, text-extracted,
possibly rewritten, and shipped to the model. The Anthropic PDF limit (~100 pages / 32MB)
means the API will eventually 400 → `ExtractionFailed` → 502, but only after the
expensive local work and upload — a cheap DoS/cost vector and a memory-pressure risk on
the webhook worker. Real defect. Fix direction: cap pages and bytes in `precheck_pdf` /
`store_attachment` and short-circuit to `needs_manual`.

### B7. Truncated / partial PDF (`synthetic_pa_truncated.pdf`) — handled for the tested case — CONFIRMED (acceptable)
The committed fixture truncates to under the PA minimum, so `precheck_pdf` returns a
"possible missing pages" reason (`test_precheck.py::test_truncated_pa_reports_missing_pages`,
`test_confirm_extraction.py::test_truncated_pa_reports_missing_pages`) → 422 manual.
Acceptable. Theoretical residual: a PA truncated *after* page 2 but before the end still
parses with ≥2 pages and ≥200 chars, passes precheck, and the model extracts from an
incomplete document with no "partial" signal. Low likelihood; not a crash.

### B8. Two documents concatenated into one PDF — silent wrong extraction — P2, THEORETICAL
Nothing detects a multi-document PDF. Precheck passes (pages + text present); the model
returns a single `doc_looks_like` and one field set (extractor.py:263-338). A PA
concatenated with its counter offer would extract a blended/wrong set of terms
(e.g. PA price kept when the counter superseded it), `signature_detected` passes, and it
confirms into the SOR with no flag. No crash; the risk is silent data corruption. Cannot
be confirmed without a model run, hence THEORETICAL.

---

## Quick verdict table

| ID | Sev | Status | Theme | Real defect? |
|----|-----|--------|-------|--------------|
| A1 | P1 | CONFIRMED | dropped attachments | Yes — silent legal-doc loss |
| A2 | P2 | CONFIRMED | build no-op | Yes — success toast on empty build |
| A3 | P2 | CONFIRMED | confidence/verify | Yes — bulk-confirm bypasses review |
| A4 | P2 | CONFIRMED path | zero-field PA | Yes — hollow deal, no "unreadable" state |
| A5 | P3 | CONFIRMED | quarter mislabel | Minor — all-time shown as quarter |
| A6 | P3 | CONFIRMED | admin sample data | Acceptable (prototype-tagged) |
| B1 | P2 | CONFIRMED | precheck is PA-only | Yes — non-PA types ungated |
| B2 | — | CONFIRMED | 0-byte | Acceptable (graceful) |
| B3 | — | CONFIRMED | non-PDF | Graceful for PA; 502 for others (B1) |
| B4 | — | CONFIRMED | encrypted | Acceptable; decrypt safe |
| B5 | P2 | CONFIRMED | scan no-text | Caught for PA only (see B1) |
| B6 | P2 | CONFIRMED | no page/size cap | Yes — cost/DoS/memory |
| B7 | — | CONFIRMED | truncated | Acceptable (graceful) |
| B8 | P2 | THEORETICAL | concatenated docs | Likely — silent wrong extraction |
</content>
</invoke>
