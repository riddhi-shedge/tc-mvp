# UI Inventory & Evolution Plan — 2026-09-11

## Part 1 — What exists today (full visual inventory)

### App shell (TC workspace)
Left **sidebar** (collapsible; nav + sign-out) · **topbar** with breadcrumbs ·
full-width `.page` content · **⌘K CommandPalette** · toast system · dark mode via
`[data-theme]` tokens.

### Design system (`styles.css`, ~2,500 lines)
- **Tokens:** indigo accent (`--gold-*` aliases), cream/surface neutrals, status
  green/amber/red, 8-step type scale (`--t-2xs`…`--t-2xl`), 4px spacing scale,
  radii 8/11/16/pill, Inter everywhere, 3 shadow tiers, focus ring.
- **Component families:** cards, badges/chips, `.dl-*` (ledger), `.tz-*`
  (timeline), `.cs-*` (closing stepper), `.ops-*` (lanes), `.bf-*` (broker file),
  `.cx-*` (cancellation), batch rows, doc rows, empty states, spinners.

### Screens (28 components)
| Surface | Layout pattern | Notable |
|---|---|---|
| Login | split auth (brand panel + card) | |
| **Home** | split-pane decision queue: triage chips → DecisionRow list ⇄ DealPeek right panel; Runway (10-business-day columns) | j/k/Enter keyboard |
| **Deals & Inbox** | pipeline board (DealsBoard) + batch-drop card + inbox queue rows + manual upload | |
| **Deal** | header + since-you-last-looked strip + gate banners; cards: Cancellation, ClosingStepper, OpsLanes, BrokerFile (+printable packet), Dashboard, Notes; **chapter-zoom timeline** (chip lanes, +N clusters, NBP popovers, task/doc lanes, collapses to strip on Documents tab); AnimatedTabs: Overview / **Documents (full-width master-detail Ledger**: filter chips, grouped rows + ghost rows, object-page record, story panel, provenance glyphs) / Communication (split inbox, drafts, Approve & Send) / Log | stage-adaptive initial tab, tab badges, deal chat |
| Calendar, Quarter, Recommendations, Admin, Support, Guide | standard card pages | .ics feed |
| PartyOrbit, DealPeek, MissingPanel*, DocumentChecks*, ExtractionReview* | (*retired from Deal, superseded by Ledger — still in repo) | |

### Invite surfaces (separate identities, deliberate)
- **Buyer** `.bw`: pine/sage + Fraunces serif; three-answer strip; TapToDefine.
- **Seller**: same system, seller-framed.
- **Buyer-agent / Listing-agent** `.aw`: dense pro system, violet = AI content,
  cram cards, schedule/earnings views.

### Known debts
Retired components still shipped; ~28 stray hex values outside tokens (P-C
leftover); padding inconsistencies; CA holidays unmarked in Runway; mobile is
serviceable, not designed; icon set stretched thin (reused metaphors).

## Part 2 — Research takeaways (2026 workspace patterns)

1. **Sidebar remains the B2B convention** for deep-hierarchy tools; topbar only
   for what is true everywhere (search, account, notifications, primary create).
   We comply; our topbar is underused (no global create / notifications).
2. **Command palette is table stakes** — accelerator, not replacement. Ours
   exists; coverage should include actions (not just navigation).
3. **Named patterns beat adjectives in AI-UI prompts** — "master-detail split,"
   "stepper," "sticky table header" produce usable output; vibes don't.
4. **Reusable context block** before every generation prompt: target user,
   conventions (tokens/stack), constraints (hard rules), scope.
5. Density with progressive disclosure (Linear/Notion pattern) — already our
   ledger's spine; extend to comms + calendar.

## Part 3 — Reusable prompt library (for future UI generation)

**Context block (paste before any UI prompt):**
> Terra: a CA-residential transaction-coordination workspace. User: one
> professional TC juggling ~10 deals; keyboard-friendly, dense-but-calm.
> Stack: React+TS, single styles.css with tokens (indigo accent, cream
> surfaces, status green/amber/red, Inter, 4px scale). Hard rules: no money
> movement UI, human Approve & Send on all outbound, CA-only. Reuse existing
> families (cards, chips, dl-/tz- rows) before inventing.

**Pattern-named prompts that work (examples):**
- "Redesign X as a **master-detail split**: dense 36px rows left, object-page
  record right, filter chips above, ghost rows for missing items."
- "A **stepper** for the closing chain: six steps, done/next/locked states,
  date per step, inline blocking banner when a clock gates the next step."
- "A **triage board** with three state columns and a slide-over drawer."
- "A **split-pane queue**: roving-focus list left, preview pane right, j/k."

## Part 4 — The plan (prioritized)

**P1 — Consistency pass (1 session).** Delete retired components
(MissingPanel/DocumentChecks/ExtractionReview if truly unused); sweep the 28
stray hexes into tokens; padding normalization; one icon audit.

**P2 — Topbar earns its keep (1 session).** Global "＋ New" (upload/deal/task),
notification bell fed by the digest/attention counts, global search merging into
⌘K. Palette gains actions ("draft weekly updates", "audit sweep").

**P3 — Communication tab modernization (1–2 sessions).** Apply the ledger's
master-detail recipe to comms: thread list + message record pane, draft states
as chips, Approve & Send as the object-page action. It's the last tab still on
the old stacked-cards pattern.

**P4 — Calendar/Quarter upgrade (1 session).** Month grid with deadline pills
(status-colored), CA-holiday shading, drag-to-.ics; Quarter becomes a portfolio
runway reusing `.tz-*`.

**P5 — Mobile pass (1 session).** The TC on their phone at a signing: Home
queue and Deal ledger collapse patterns (accordion = ledger's narrow mode
already specced), thumb-reach actions.

**P6 — Invite-surface polish (opportunistic).** Buyer/seller surfaces are
strong; agent surfaces could adopt the ledger recipe for their doc views.

*Rule of engagement: each P ships whole with before/after screenshots; visual
changes never bundle with behavior changes.*
