# UI/UX design pass — Terra TC workspace

*2026-08-31, from the frontend at commit `e28052f`. Design document + one prototype
(`/prototypes/today-split/`). No application code was modified.*

---

## Phase 1 — Audit of what exists

### Screens and their jobs

| Screen | Job | UI shape |
|---|---|---|
| `Home.tsx` | The decision queue (P1): triage strip → queue rows with inline approve/dismiss/resolve → deadline horizon + tasks | Two-column list page |
| `DealsBoard.tsx` | Pipeline by stage, filters | Card board |
| `Deal.tsx` + 7 modules | Everything about one deal: dashboard, extraction review, doc checks, timeline, notes, map, messages, Q&A chat | **Correction (implementation pass):** the page *does* have tab organization — `AnimatedTabs` (Overview / Map / Documents / Comms / Log); my original grep missed the component name. The real gaps were **no per-tab badges** (you click a tab to learn whether it needs you) and a **non-adaptive initial tab** — both fixed in P-E as shipped |
| `Inbox.tsx` | Confirm/dismiss inbound email into deals | List + per-item deal-select |
| `Calendar.tsx` | Month grid + work queue; ICS subscribe (P4) | Calendar page |
| `Recommendations.tsx` | Derived attention cards (rail) | Card list, overlaps the queue |
| `Quarter.tsx` | Personal stats — QoQ openly sample data | Sparse; a working session gains ~nothing |
| `CommandPalette.tsx` | ⌘K: deal jump + go-home/deals/theme | Modal palette |

### State flow

`App.tsx` holds a local `View` union (no router) persisted to localStorage; screens
get navigation callbacks by prop (`onOpenDeal`, `onOpenInbox`…). Every navigation is
a **full view swap**: opening a deal from the queue unmounts the queue — scroll
position, filter, and any in-progress draft edit context are gone; "← Deals" round-trips.
Draft edits live in `Deal.tsx` component state (`edits`) — navigate away and they
evaporate. One global stylesheet (`styles.css`, 2,130 lines); no CSS modules, no
component library (a deliberate, good constraint).

### The design system, plainly

There **is** a real token block (`styles.css:1-45`) with light/dark themes, radii,
shadows, and a focus ring — genuinely better than most MVPs. Below it, the system
stops being a system:

- **The token names lie.** `--gold-*` is indigo (`#5b5ef0`), `--navy-*` is slate,
  `--serif` is an alias for the sans stack. The file admits it: *"Legacy names kept
  … so every component inherits the reskin."* Every new contributor (human or AI)
  must learn that gold means indigo.
- **67 distinct `font-size` values.** A type scale exists for exactly h1–h3; body
  sizes cluster at 0.72/0.74/0.78/0.8/0.82/0.85/0.9rem — seven near-identical
  sizes doing one job (measured, not sampled).
- **181 distinct `padding` values.** There is no spacing scale at all.
- **28 raw hex colors** used outside the token block.

Verdict: tokens at the top, ad-hoc styling underneath. It *looks* coherent because
one author kept it in their head — which is exactly the thing a system is supposed
to replace.

### Click/keystroke counts (traced from code, not timed)

| Action | Today | Notes |
|---|---|---|
| Open a deal | 1 click | Queue/board row — **mouse only**; rows are `onClick` divs |
| Check nearest deadlines | 0 | Horizon is on Home (P1) — genuinely good |
| Review an inbound email | 2 clicks best case | Inbox nav → Confirm (suggestion pre-selects the deal); +1 select if suggestion is wrong; +modal on extraction 422 |
| Approve an outbound draft | 2 clicks | Queue: Review → Approve & Send (was ~4 via the deal page before P1) |
| Switch between two active deals | 3+ clicks or ⌘K + retype | No recents, no switcher; queue position lost both ways |
| Anything at all by keyboard | — | **⌘K is the entire keyboard story** (`App.tsx:82`). No list navigation, no action keys |

### Density — wrong in both directions

- **Too sparse:** `Quarter` (sample charts), `Guide`, `Recommendations` (cards
  restating what the queue now shows). A TC's working hours gain nothing from them.
- **Too dense, no hierarchy:** `Deal.tsx` — seven full modules on one scroll. The
  answer to "what's the loan contingency date" and "what did the inspector upload"
  and "chat with the AI" all live at different scroll depths of the same page,
  competing at equal visual weight.
- **About right:** the queue (P1) and Inbox — list-shaped, actionable, scannable.

### What the user must hold in their head

- **Where they were** — every deal-open destroys queue context; coming back means
  re-finding your row.
- **Draft edits in progress** — component state only; navigation loses them.
- **Which deals they touch most** — no recents anywhere; ⌘K requires retyping.
- **What's inside the seven Deal modules** — no per-module summary badges, so you
  scroll to know whether Document Checks has anything to say.

### Accessibility & responsive

- Keyboard: `:focus-visible` styling exists for `button`/`.tab`/`.doc-card` (3
  selectors); **zero `tabIndex` management anywhere**; the primary interaction
  surface — queue rows, board cards, calendar cells, inbox rows — is clickable
  `<div>`s, unreachable and unactivatable by keyboard. 16 `aria-*` uses across the
  TC app, 4 `role=`. Screen-reader users cannot run this product; keyboard-heavy
  power users can't either, which for this audience is the same bug twice.
- Contrast: indigo-on-white and the status tints pass at their sizes (spot-checked
  values, not exhaustively measured). Dark theme is deliberate and complete.
- Laptop at real size: usable; the queue and board fit 13″ fine. The Deal page's
  problem is length, not width.

---

## Phase 2 — Pattern research

Epistemic labels used throughout: **[docs]** = reasoning from the company's own
published design writing; **[used]** = from the product's actual shipped interface
as I know it; **[general]** = general knowledge of the pattern class; **[inferring]**
= I have not meaningfully used or read primary material — treat as hypothesis.

- **Linear** [docs + general]: the reference for dense-but-readable. Their public
  writing emphasizes keyboard-first as identity, sub-100 ms perceived actions, and
  restraint in color (status is communicated by small icons + a controlled accent,
  not row-tinting). The structural pattern that maps here: **list + peek** — a
  selected row opens a side panel with full context; the list never unmounts.
  Rows ~36 px, weight-based hierarchy (same size, bolder key text).
- **Superhuman** [general]: triage as the core loop — `j/k` to move, single-key
  verbs (archive, reply), and the insight that **speed of the repeated action is
  the product**. Their approval-adjacent pattern: an instant action plus a brief
  undo window feels faster *and* safer than a confirm dialog.
- **Front** [general]: shared-inbox + right-hand context panel about the
  conversation's contact/account — the "conversation left, entity context right"
  split maps directly onto "decision left, deal context right."
- **Notion databases / Height** [general]: one dataset, many projections (table,
  board, calendar) with view-level filters — the argument for the queue, board,
  and calendar being *views of one list*, not three screens with three fetches.
- **Retool** [general]: proof that operational UIs tolerate much higher density
  than consumer aesthetics suggest, *if* alignment and type discipline hold.
- **Dotloop / SkySlope / Open To Close** [inferring — I have not used them]: by
  reputation and market materials, file-centric checklist tools: navigate into a
  transaction, work a compliance checklist, navigate out. Little evidence of
  keyboard-first or cross-file triage surfaces. If that inference holds, cross-deal
  triage + keyboard speed is exactly the flank they're weak on — but verify with a
  TC who uses one before leaning on this competitively.
- **AI-approval UX** [general]: the emerging consensus in copilot-style tools is:
  show the artifact in full, show *why*, make approval one gesture, and batch
  low-risk items — the gate stays, the friction concentrates on reading, not
  clicking. (Your Rule 3 already matches this philosophically; the UI just makes
  approval a two-click, two-screen-state affair.)

---

## Phase 3 — Proposals

**The single organizing object: the decision.** The deal is the *record*; the
timeline is the *engine*; but the TC's day is a stream of decisions the SOR
generates (approve, confirm, resolve, chase, file). `docs/next-phase.md` made this
argument for information architecture; this pass extends it to interaction: **the
workspace should be shaped like an inbox whose rows are decisions, with the deal
as the context panel — never a separate destination for routine work.** Deals,
board, and calendar remain projections you can jump to; you *live* in the queue.

**The one screen a TC lives in all day** (this is Proposal 1 + 2 + 5 composed):
three regions. Left, the existing nav rail (unchanged, collapsed by default).
Center, the decision queue — triage chips on top, then rows at ~40 px: kind icon,
deal address in medium weight, one-line title, urgency pill right-aligned in
tabular numerals. One row is always *selected* (keyboard cursor), not just
hovered. Right, a **context panel** bound to the selected row's deal: address +
stage + price header, a horizontal 10-business-day **deadline runway**, the
"since you last looked" digest, the parties strip, and — when the selected row is
a draft — the full message with recipient, reasoning, and an edit-in-place body,
so Rule-3 review happens where your eyes already are. `j/k` moves, `Enter`
approves/acts, `o` opens the full deal page (which remains, for deep work), `⌘K`
jumps. The queue never unmounts; approving advances the cursor to the next row —
the Superhuman loop wearing Linear's clothes, applied to transaction coordination.

### P-A · Split-pane Today: queue + deal context panel — **build first**
- **Problem (Phase 1):** every deal-open is a full view swap that destroys queue
  position; routine review forces navigate → scroll a 924-line page → navigate back.
- **What changes:** Home becomes list-left / context-right (described above). The
  Deal page survives for deep work; ~80 % of touches stop needing it.
- **Pattern:** Linear's list+peek [docs+general], Front's context panel [general].
- **Cost:** rework of `Home.tsx` layout + a new `DealPeek` component that reuses
  existing pieces (digest, horizon, parties, draft review). Days. The
  `/transactions/attention` payload already carries most of it; the peek wants one
  cheap `GET /transactions/{id}` on selection.
- **Risk:** on a 13″ screen three regions can crowd — the panel must collapse
  below ~1100 px (prototype demonstrates the breakpoint). Second risk: the peek
  slowly re-grows into the whole Deal page; it must stay a summary with `o` as the
  escape hatch.

### P-B · Keyboard triage layer
- **Problem:** zero keyboard operability; power users repeat the same 5 actions
  hundreds of times a week with a mouse.
- **What changes:** roving `tabIndex` + cursor selection on queue/inbox/board
  lists; `j/k` move, `Enter` primary action, `e` approve, `d` dismiss, `o` open
  deal, `g h/c/i` go-to; palette gains action verbs ("approve all low-risk…" as
  a *navigation* to a filtered queue, never an auto-send). A one-line shortcut
  hint bar at the queue's foot.
- **Pattern:** Superhuman/Linear [general/docs]. **This also fixes the a11y hole**
  — the same work that makes divs focusable makes them screen-reader operable.
- **Cost:** a `useListCursor` hook + converting row divs to focusable elements.
  1–2 days. Breaks nothing visual.
- **Risk:** shortcut collisions with browser/OS; mitigate with single letters only
  when a list has focus, never global except ⌘K.

### P-C · Token honesty + scale normalization
- **Problem:** gold-means-indigo, 67 font sizes, 181 paddings, 28 stray hexes.
- **What changes:** a mechanical pass — semantic names (`--accent`, `--surface-*`,
  `--status-{ok,warn,danger}-{fg,bg}`), one type scale (11/12/12.5/13/14/16/20 px),
  a 4 px spacing scale, tokens for the strays; old names kept as deprecated
  aliases for one release. No visual redesign — normalize toward the most-used
  value in each cluster so screens shift by a pixel, not a look.
- **Pattern:** Linear's restraint [docs]; every design system ever.
- **Cost:** half a day of careful find-replace + visual diff. **Do it before A/B**
  so new components are born onto the scale.
- **Risk:** low; a wrong collapse shows up instantly in visual review.

### P-D · Deadline runway (time as space)
- **Problem:** deadlines render as *lists of dates* everywhere; under time
  pressure a TC needs *distance*, not date strings.
- **What changes:** a horizontal strip — next 10 CA business days as columns,
  today leftmost and widest, weekend/holiday gaps compressed to slivers — with
  deadline chips stacked in their day column, colored by urgency, deal-tagged.
  Lives at the top of the context panel (per-deal) and full-width on Calendar
  (cross-book). Clicking a chip selects that deal's queue rows.
- **Pattern:** timeline/cycle views (Height, Linear cycles) [general]; closest to
  a Gantt header without the Gantt.
- **Cost:** one pure component over data that already ships (`horizon` +
  `deadlines`). 1–2 days.
- **Risk:** clutter at 30 deals × several deadlines — cap chips per column with a
  "+3" overflow, and it must *never* become interactive-looking beyond click-to-
  filter (deadlines are SOR-owned facts).

### P-E · Deal page: progressive disclosure
- **Problem:** seven modules, one scroll, equal weight; the page answers every
  question at the cost of answering none quickly.
- **What changes:** sticky in-page section nav with per-module count badges
  (Docs ✓/✗, fields to confirm, open flags); modules collapsed by default except
  the two the deal's *stage* makes primary (extraction+timeline early; messages+
  checks mid; docs+closing late — the same phase-adaptive idea the party surfaces
  already use). Notes/map/orbit collapse to headers.
- **Pattern:** progressive disclosure in dense tools [general]; your own
  `sections_for()` architecture on the invite surfaces.
- **Cost:** restructuring `Deal.tsx`'s render (the modules are already components).
  2–3 days. Risk of breaking the deep-link-less flow is low since there's no URL
  state to preserve — itself a finding.
- **Risk:** hiding a module a particular TC checks constantly; mitigate with
  badges + remembered open/closed state per module.

### P-F · One dataset, three views (board/calendar/queue unification)
- **Problem:** Home, Board, and Calendar are three screens with three separate
  fetch stacks over the same book; filters don't travel (at-risk on the board ≠
  at-risk chip on Home).
- **What changes:** a single book store (fetch once, share) + a view switcher
  (Queue · Board · Calendar) with persistent filters. Recommendations retires
  into the queue (its cards are queue rows with less actionability).
- **Pattern:** Notion/Height database views [general].
- **Cost:** the largest item — state refactor touching four screens. ~1 week.
- **Risk:** highest regression surface; do last, after A settles what the primary
  view even is.

### Ranked
**C → A → B → D → E → F.** C is half a day and makes everything after cheaper —
but it's invisible, so if "first" means *first visible change*: **A is the one
change I'd make** — it's the structural fix the audit points at from three
directions (context destruction, mouse-only speed ceiling, Deal-page overload),
and B and D compose into it naturally. The prototype below is A with B and D
embedded, because the three are one screen in practice.

---

## Phase 4 — Prototype

`/prototypes/today-split/index.html` — self-contained static HTML/CSS/JS, no
dependencies, no imports from the app, realistic mock data shaped like the real
payloads (`/transactions/attention` + deal state; McClellan-flavored CA deals).

What it demonstrates:
- The three-region screen: triage chips · decision queue · deal context panel
- Queue cursor: `j/k` (or arrows) moves selection, panel follows; `Enter`/`e`
  approves the selected draft (with advance-to-next), `d` dismisses, `o` "opens"
  the deal (stub), `⌘K` palette stub, `?` shortcut overlay
- Rule-3 approval in the panel: full recipient, the co-pilot's *why*, editable
  body, one-keystroke approve — the gate as a fast read, not a click ritual
- The deadline runway: 10 CA business days as columns, urgency-colored chips,
  weekend compression
- The ≤1100 px behavior (panel collapses; queue stays)
- P-C's token discipline applied: semantic tokens, one type scale, 4 px spacing —
  the prototype is also a preview of the normalized system

Evaluate it for: whether the panel answers "can I act without opening the deal?"
for drafts/reminders/gates/risks, and whether 40 px rows × ~20 visible decisions
reads as calm or as a wall. Both are exactly the judgments a real TC should make
before this ships.

---

## Constraint check
Approval gate: preserved and made faster (full content + recipient still shown
before send; nothing auto-sends — the undo-window variant is *not* included
because it changes send semantics; flagged as a decision if wanted). CA-only:
runway compresses on CA legal holidays. No new dependencies anywhere (prototype
is vanilla; proposals use existing stack). Three-part architecture untouched —
everything here consumes existing SOR endpoints.
