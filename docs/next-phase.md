# Next phase — product research & design pass

*Generated 2026-08-31 from the codebase at commit `0d26051`. Research pass only; no code was modified.*

> **⚠️ The interview slot in the brief was empty.** The prompt said interview material outranks
> my priors — but none was pasted. Every claim about user behavior below is therefore
> **my inference**, tagged as such, and the whole Phase 2/3 analysis should be treated as a
> hypothesis sheet to check against real TCs, not as validated findings. The final section
> lists exactly which inferences are most load-bearing and how to test them cheaply. If you
> have interview notes, re-run this pass with them pasted — several rankings could flip.

---

## 0. Primary user segment

**Candidates:**

| Segment | Signal in the code |
|---|---|
| **Independent TC running 20–40 deals** | Single-login TC auth (`require_tc`, MFA aal2, `app/common/auth.py`); no team/roles/seats; per-deal email ingestion; cross-deal board/calendar/tasks roll-ups (`/transactions/board`, `/transactions/calendar`, `/transactions/tasks`); "My quarter" self-assessment (`Quarter.tsx` — a *personal* review screen, not a manager's) |
| In-house TC at a brokerage | Almost nothing: no brokerage entity, no multi-TC assignment, no manager view, no compliance-officer role. The audit log + approvals trail would *serve* broker compliance, but nobody in the model represents the broker |
| Solo agent self-coordinating | The buyer's-agent and listing-agent command centers (`invite/agent/`, `invite/listing/`) are real surfaces, but they're invite-link *satellites* of a TC-owned SOR — an agent can't create a deal, ingest email, or run compliance |

**What the product as built is shaped for today:** the independent solo TC. One authenticated
human owns every deal; everyone else (buyer, seller, agents, escrow, vendors) is an invited
party with a scoped, read-mostly workspace. The entire Rule-3 approval architecture assumes
exactly one approving human.

**My bet:** the independent TC — and not just because the code leans that way. My inference:
this segment feels deal-volume pain personally (their income is per-file), buys tools with
their own card, and has no IT gatekeeper. The brokerage segment is a bigger contract but a
longer sale and demands roles/permissions you haven't built.

**What changes under a different choice:** if you pivot to brokerages, proposals #1, #2, #5
survive intact but #7 (close-out packet) jumps to #1, and "team/roles" — on my do-not-build
list for the solo TC — becomes mandatory. If you pivot to solo agents, the two agent command
centers become the *product* rather than satellites, and the TC dashboard becomes the satellite.

---

## Phase 1 — What actually exists

Blunt overall read first: **this is meaningfully thicker than an MVP frame implies.** The
three-part architecture is real (ingestion in `app/ingestion/`, SOR/dashboard in
`app/master/` + `frontend/src/screens/`, compliance in `app/compliance/` with a verified-CA-
ruleset gate and a daily Render cron). The five hard rules are enforced in code, not copy —
e.g. the mailer allowlist (`app/master/mailer.py`), the ZDR/synthetic gate (`app/common/zdr.py`),
`state = 'CA'` as a *check constraint* (`supabase/migrations/20260712000001_sor_core.sql:39`).
The thin spots are real too, and named below.

### 1.1 Screens and what a user can accomplish

**TC app (authenticated, `App.tsx` local view-state, no router):**

| Screen | What you can actually do |
|---|---|
| `Home.tsx` | The daily landing: board roll-up (`/transactions/board`), calendar deadlines, open tasks across deals. Composite of three fetches |
| `DealsBoard.tsx` | Pipeline by stage (`new → cont → closing → closed`), filter All / Closing this week / At risk (`risk_count`), open a deal |
| `Deal.tsx` (+ 7 sub-screens) | The workhorse, 924 lines: `DealDashboard` (facts, parties, tasks, docs), `DealTimeline`, `ExtractionReview` (confirm/hand-enter extracted fields — the timeline gate), `DocumentChecks` (open risk flags vs docs), `DealNotes`, `DealMap`, `PartyOrbit`. Actions: build timeline, add parties/tasks, assign tasks, draft messages (purpose-driven Claude drafts), **Approve & Send** (Rule 3), invite parties (magic links + invite email), resolve risk flags, dismiss reminders, open docs via signed URL, ask the deal assistant (`/ask`), archive/cancel/reactivate |
| `Inbox.tsx` | Ingestion review: pending inbound emails → confirm into a deal (extraction runs; 422 opens manual field entry — extraction refuses to guess), dismiss, manual upload |
| `Calendar.tsx` | Cross-deal deadlines + tasks by date |
| `Recommendations.tsx` | "Context rail": derived cards (risk flags, imminent closings, due-today) with Open / Mark reviewed / Dismiss. Derivation is client-side from board+calendar only |
| `Quarter.tsx` | Personal quarter stats; QoQ honestly marked "sample" (no closed-deal warehouse) |
| `CommandPalette.tsx` | ⌘K deal jump with risk badges |
| `Admin.tsx`, `Guide.tsx`, `Support.tsx`, `Login.tsx` | Housekeeping, onboarding, MFA login |

**Party surfaces (invite-link, no login, `InviteView.tsx` dispatching on archetype/role):**
buyer workspace (3-question loop, contingency tracker, wire-verify deposit step), seller
workspace (deal health, disclosure attestations, net sheet, disbursement verify), buyer's-agent
command center (whole-book pipeline, AI approval queue, deadline radar, clients), listing-agent
command center (offer comparison, DOM signals), plus bespoke escrow/inspector/lender views.
All are projections of the same SOR state via `build_party_workspace`
(`app/master/party_views.py`) and the `/agent|/listing` portfolio endpoints.

### 1.2 Data model — and the latent capability audit

Core: `transactions, properties, parties, documents, payloads, extracted_fields, deadlines,
tasks` (`20260712000001_sor_core.sql`), plus `messages, reminders, approvals` (messaging),
`inbound emails/inbox`, `risk_flags`, `audit_log`, `compliance runs`, `properties.details`
jsonb enrichment.

**Schema/state the UI does not currently expose** — the cheap feature surface you asked for:

| Latent capability | Where it lives | What's missing |
|---|---|---|
| **Cross-deal "needs my decision" counts** | Draft `messages`, due `reminders`, `timeline_gate.unconfirmed_fields`, pending inbox items all exist per-deal | `DealSummary` (`lib/api.ts:76`) carries only task counts + `risk_count`. Drafts awaiting approval, reminders due, unconfirmed fields, and unrouted inbox are invisible from Home/board — you must open each deal to discover them. **This is the single biggest latent gap** |
| Role-relative event feeds for the TC | `event_catalog.py` renders every SOR event per-role for parties/agents | The TC's own deal view shows raw `audit_log`; no digest "what happened since I last looked" |
| `provider_message_id` + `sent_at` | `messages` | No delivery/thread status anywhere; "did escrow ever answer?" is inferable (reminders exist) but not shown as a per-party conversation |
| `approvals` + `audit_log` as a compliance record | Append-only, complete | No export/report; the strongest broker-facing asset is unqueryable |
| `parties.company/email/phone` + invite tiers | Full roster machinery | No cross-deal contact book ("all my escrow officers"); `/agent/clients` exists for agents but nothing equivalent for the TC |
| `extracted_fields.payload_id` provenance | Every field links to its source payload/document | ExtractionReview shows values; "show me the page this came from" isn't wired to the signed-URL viewer |
| Closed-deal history | Rows persist after close | `Quarter.tsx` openly fakes QoQ; nothing warehouses cycle times, on-time close rates |
| `authority.py` write matrix | Declarative §5 matrix, tested | Enforced by construction in routes, but not consulted dynamically — fine today, latent for team roles |
| Deal notes | `localStorage` only (`DealNotes.tsx:7`) | **Not in the SOR at all** — see 1.4 |

### 1.3 Deal lifecycle as built

1. **Inbound**: Postmark webhook (`/webhooks/postmark`) or manual upload → `ingestion` inbox with content-hash dedupe + atomic claim (`inbox_repo.py`).
2. **Review**: TC confirms in `Inbox.tsx` → Claude extraction (ZDR-gated, refuses-to-guess → manual entry) → payload + `extracted_fields` written to a new or matched transaction.
3. **Gate**: deadline-driving fields must be confirmed (`ExtractionReview`, `timeline_gate`) before **build timeline** derives CA deadlines (business-day math + CA holidays, `app/compliance/date_engine.py`).
4. **Run**: daily compliance cron (14:00 UTC, `render.yaml`) + on-demand runs update deadlines/risk flags; tasks assigned to parties surface in their invite workspaces; documents arrive from parties or email.
5. **Communicate**: purpose-driven Claude drafts (`drafting.py` — lender status, disclosure reminder, escrow check-in, offer comparison…) → TC/agent **approve & send** (allowlist-guarded Postmark) → follow-up `reminder` auto-created → due reminders resurface in the deal.
6. **Close**: stage → `closed`, archive. No close-out artifact is produced.

### 1.4 Every point where the user must leave the product

Each is a hole in the SOR claim, in rough order of bleed:

1. **Their real email client.** Ingestion covers mail sent to the per-deal address; everything else (threads on their personal address, replies to sent messages — there is **no reply ingestion**; `provider_message_id` is stored but never matched) lives in Gmail/Outlook. The monitoring agent watches one mailbox slice, not the TC's actual correspondence. *(my inference on severity — verify)*
2. **E-signature vendor** (Docusign/Glide/ZipForms). Signatures are tracked as party attestations at best; the actual signing round-trip is entirely external. Deliberate (document-handling rule), but it's the largest single absence from the record.
3. **Forms**: no C.A.R. form awareness beyond extraction. The RPA is read, never produced.
4. **Calendar**: `Calendar.tsx` is view-only in-app; no .ics feed, so deadlines get retyped into Google Calendar. *(my inference that TCs do this — verify)*
5. **Spreadsheets**: no closed-deal reporting, no export anywhere → any accounting/volume tracking is a Sheet.
6. **Phone**: wire verification is by design out-of-band; the *outcome* is captured (`party.deposit_verified` etc.) — this one is a feature, not a hole.

### 1.5 What the user must hold in their head

- **"Which deal needs me right now?"** — partially answered (risk flags, due-today) but drafts/reminders/unconfirmed/inbox are per-deal discoveries (1.2 row 1).
- **"Did X ever reply?"** — reminders fire per-deal on schedule, but there's no per-party thread view and no reply detection at all.
- **Anything they type into DealNotes** — it's `localStorage`: not synced, not backed up, lost on a browser wipe, invisible to the SOR/assistant. For a "System of Record" this is the most self-undermining detail in the codebase.
- **Doc completeness per deal type** — `DocumentChecks` shows risk flags vs docs, but there's no canonical "CA purchase needs these N documents" checklist with received/outstanding state.
- **Why a deadline is what it is** — the date engine knows (trigger field + business-day rule); the UI shows only the date.

---

## Phase 2 — Friction analysis

*All friction claims below are my inference from the lifecycle + code, absent interview data.*

**(a) Genuinely missing:** reply/thread awareness on sent messages; SOR-backed notes; close-out
export; closed-deal history; .ics feed; doc-type checklist; any TC-side cross-deal approval
queue.

**(b) Exists but buried (UI problems wearing feature-request costumes):**
- The approval flow exists per-deal (draft → edit → approve) but a TC with 25 deals has no queue — the *agent* surfaces got one (`ApprovalQueue` in `invite/agent/`), the paying user didn't.
- Field provenance exists (`payload_id`) but ExtractionReview doesn't link to the source doc.
- Risk flags exist and are counted on the board, but the *reason* and the one-tap next action (draft the chase email) are two screens apart.
- The deal assistant (`/ask`) exists but is invisible on Home — you must already be inside a deal to ask a question whose answer is "which deal?".

**(c) Things users would ask for and not use** *(inferences, all)*: a full CRM layer; in-app chat between parties (they'll stay in text/email); dashboards-for-dashboards (Quarter QoQ charts); native mobile app (the responsive invite surfaces already cover the on-the-go case, which is mostly parties, not the desk-bound TC).

### The organizing object

**The deal is the record; the *decision* is the unit of daily work — and the daily screen
should be a decision queue, not a deal list.**

Argument: every consequential thing in this product funnels to one human's yes: confirm this
extraction, approve this draft, resolve this flag, chase this silence, confirm these fields
so the timeline can build. The SOR generates decisions; the TC's job is clearing them. The
current IA is deal-first (Home → board → open deal → discover work), which scales linearly
with deal count — precisely the thing a 30-deal TC can't afford. `Recommendations.tsx` is a
recognition of this ("the Context Rail") but it derives only from board+calendar, has no
counts for drafts/reminders/unconfirmed/inbox, and isn't the landing screen.

**The one dense daily screen** (most of it is assembly, not new capability):
1. Triage strip: inbox items pending · drafts awaiting approval · reminders due · fields blocking timelines · unresolved risk flags — each a cross-deal count that filters the queue below.
2. The queue itself: one row per decision, sorted by deadline pressure, with the deal as *context* on the row (not the container you must enter). Approve/edit inline where the artifact allows it.
3. Deadline horizon (next 7 CA-business days, cross-deal) — the radar the agent surfaces already have.
4. ⌘K everywhere.

The current `Home.tsx` is roughly ⅓ of this (board + calendar + tasks). It is not it.

---

## Phase 3 — Proposals

Effort scale: **hours** (<1 day) / **days** (1–5) / **weeks** (>1). "SOR-moat" = only credible
because you hold the record; a competitor without ingestion+compliance state can't fake it.

### P1 — The TC decision queue ("Today")
- **Job:** "Show me everything waiting on *me*, across every file, worst first — without opening 25 deals."
- **Who/how often:** the TC, first thing every morning and after every coffee. *(inference)*
- **Beats:** opening deals one-by-one; the legacy alternative is a paper checklist or Dotloop's per-file task lists, which have the same linear-scan problem.
- **Dependencies:** zero new data. Draft messages, reminders, `timeline_gate`, risk flags, inbox counts all exist; the assembly pattern is already written for agents (`_pending_drafts`, `deadline_radar`, `list_full_states` batch loader — now 1s for the whole book).
- **Effort:** days (backend roll-up endpoint + reshaped Home; approval-queue component can be adapted from `invite/agent/AgentCommandCenter.tsx`).
- **Kills it:** if real TCs actually think strictly deal-at-a-time and distrust cross-deal queues. *(the #1 thing to verify)*
- **Moat:** yes — the queue is only as good as the SOR generating it.

### P2 — Reply detection + "gone quiet" chases
- **Job:** "Tell me who never answered, and have the nudge already written."
- **Who/how often:** TC, daily; silence-chasing is core TC labor. *(inference)*
- **Beats:** Gmail flags and memory. Dotloop/SkySlope don't watch threads at all.
- **Dependencies:** reminders + drafter exist; needs inbound **reply matching** — correlate inbound mail to `provider_message_id`/thread (Postmark inbound already flows through the webhook; matching logic is new). No new external service.
- **Effort:** days (matching heuristics + wiring reminders → pre-drafted chase in the P1 queue).
- **Kills it:** replies landing on the TC's personal address, invisible to the per-deal mailbox — if that's the dominant pattern, coverage is too partial to trust. *(verify with real TCs before building)*
- **Moat:** yes — requires owning both send and ingestion.

### P3 — Promote DealNotes into the SOR
- **Job:** "My notes are part of the file, on every device, and Terra can read them."
- **Beats:** the current localStorage (silently losable), or the legal pad next to the keyboard.
- **Dependencies:** one small table + CRUD; fold into `/ask` context (respecting the retention rule — notes are TC-authored, not model I/O).
- **Effort:** hours-to-a-day. The UI already exists.
- **Kills it:** almost nothing; the only risk is scope creep into a "docs product."
- **Moat:** no — but it's a credibility patch on the SOR claim, and the cheapest item here.

### P4 — Deadline .ics feed
- **Job:** "My deadlines appear in the calendar I actually live in."
- **Beats:** retyping into Google Calendar. *(inference that this happens; verify)*
- **Dependencies:** `/transactions/calendar` exists; add a token-authenticated `.ics` endpoint (read-only feed — not a new external service).
- **Effort:** hours.
- **Kills it:** if TCs treat the in-app calendar as sufficient; also a stale-feed risk (calendar apps poll lazily) — set expectations in-UI.
- **Moat:** no. Any competitor ships this; it's table stakes you're missing.

### P5 — Close-out compliance packet
- **Job:** "When the broker/auditor asks, I hand them the file in one click: every doc, every approval, every send, timestamped."
- **Who:** TC at every close; broker-owners love it in the sale. *(inference)*
- **Beats:** assembling a PDF bundle from Dotloop + email exports by hand.
- **Dependencies:** `audit_log` + `approvals` + `messages` + documents list — all present and append-only. Render to a single HTML/PDF summary with signed-URL doc links. Reads documents; doesn't change their handling.
- **Effort:** days.
- **Kills it:** if the broker's required format is rigidly their own checklist, generic packets get ignored.
- **Moat:** yes — the approval/audit trail is uniquely yours.

### P6 — Field provenance one-click ("show me where this came from")
- **Job:** "I don't confirm a number I can't see the source of."
- **Dependencies:** `extracted_fields.payload_id → documents.storage_path → signed-url` — the whole chain exists; ExtractionReview just doesn't link it.
- **Effort:** hours.
- **Kills it:** page-level anchoring (the extractor doesn't store page numbers) — without it this is "open the right PDF," still useful but less magical.
- **Moat:** partially — it deepens trust in extraction, your differentiator.

### P7 — CA document checklist per deal
- **Job:** "What's still outstanding on this file?" as a checklist, not a risk-flag inference.
- **Dependencies:** `doc_type` exists; needs a canonical CA-residential checklist (static, like the buyer surface's CA library) + received-state matching. **I'm guessing at the canonical list — a real TC must author/verify it.**
- **Effort:** days.
- **Kills it:** checklist rigidity — real files diverge (probate, trust sales, tenant-occupied); if every deal needs manual checklist editing, it becomes noise.
- **Moat:** weak-to-moderate; SkySlope/Dotloop have checklist features — yours is only better if auto-checked from ingestion.

### P8 — TC-facing deal digest ("since you last looked")
- **Job:** "I open a deal and the top tells me what changed, in English."
- **Dependencies:** `event_catalog.py` already renders role-relative text for every surface *except* the TC's own deal view; add a TC voice + last-seen marker.
- **Effort:** hours-to-a-day.
- **Kills it:** low ceiling — nice, not decisive.
- **Moat:** yes, trivially (it's the event catalog).

**Rank (leverage ÷ effort):** P1 · P3 · P6 · P4 · P2 · P5 · P8 · P7

### Top 3

1. **P1 — decision queue.** Highest leverage in the codebase: it converts the SOR's existing outputs into the daily habit, makes every other feature more visible (P2's chases, P6's confirms land *in* it), and most of the machinery was already built for the agent surfaces. **Do this first.**
2. **P3 — notes into the SOR.** An afternoon of work that removes the most embarrassing contradiction of the positioning. Do it while P1 is in review.
3. **P2 — reply detection + chases.** The strongest "execution assistant" claim in the list and a real moat — but it's the one whose kill-condition (replies bypassing the per-deal mailbox) is an empirical question. Gate it on the user-learning below.

### Do not build (yet)

- **E-signature / forms authoring** — violates the document-handling constraint in spirit, is a licensing swamp (C.A.R.), and vendors are entrenched. Track signature *status*, don't do signatures.
- **Auto-send anything** ("just send the routine ones") — violates Rule 3. The approval queue makes approving fast; that's the answer.
- **CRM / lead-gen features** — different job, different buyer; dilutes the SOR identity.
- **Multi-state expansion** — hard constraint, and the CA ruleset gate (`load_verified_ruleset`) is your quality story.
- **Team/roles/seats** — mandatory *if* you pick brokerages; dead weight for the solo TC. Decide the segment first.
- **Native mobile app** — responsive invite surfaces already serve the mobile actors (parties, agents between showings). *(inference)*
- **Quarter QoQ analytics build-out** — warehouse closed-deal history first (cheap, passive), charts later, if ever.

### What to learn from real users before committing

1. **Shadow 2–3 independent TCs for a morning.** Watch the first 30 minutes of the day. Do they scan per-deal or keep a cross-deal list (paper? Sheet? Dotloop tasks?)? This validates or kills P1's core premise — and the segment bet itself.
2. **Where do replies actually land?** Ask to see a real deal's correspondence: what fraction flows through a deal-specific address vs their personal inbox? Below ~half, P2's coverage is too partial — learn *whether they'd CC a deal address* as the workaround.
3. **The close-out ritual.** What do they hand the broker today, in what format, and who chases them for it? Sizes P5 honestly.
4. **Ask them to narrate their deadline tracking.** If a Google Calendar or wall chart appears, P4 jumps the queue; if they live in the tool that computed the deadline, it drops.
5. **Show the agent command center to a TC** and ask "would you want this for yourself?" — the fastest possible mockup test for P1, and it already runs.

### Constraint check

All eight proposals: outbound remains human-approved (P1/P2 route *through* the existing
approval flow); no document-handling, money, or retention changes (P5/P6 read existing
records; P3 stores TC-authored text only); CA-only throughout; everything fits ingestion /
SOR / compliance with no new external services (P4's .ics is an endpoint, not a service;
P2 reuses the existing Postmark inbound webhook).
