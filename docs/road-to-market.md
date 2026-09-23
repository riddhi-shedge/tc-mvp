# Terra: Road to Market

*Written 2026-09-23. The plan for taking Terra from a working single-user product to a
VC-pitchable, revenue-generating company that a major real estate corporation would want to buy.*

---

## Part 0 · The honest starting point

Before the plan, the truth. Three things determine whether this works, and only one of them
is code.

**1. Acquisitions follow usage, not demos.** Lone Wolf bought zipLogix, W+R Studios, LionDesk,
and Propertybase because those products owned workflows and had paying customers. Compass bought
Anywhere ($1.6B, closed Jan 2026) to consolidate brokerage share. The 2026 M&A pattern in real
estate tech is incumbents buying *data, workflow ownership, and distribution* so they can build
credible AI faster. Nobody acquires a polished demo. They acquire the tool that 500 TCs already
run their files through. So the acquisition goal and the "real TCs use it" goal are the same
goal, in order.

**2. Terra has never been touched by a real transaction coordinator.** This is the single
biggest risk, bigger than any missing feature. Everything built so far came from research and
document analysis, which got remarkably far, but a working TC will find workflow assumptions
that are wrong within an hour. The cheapest, highest-value work on this entire roadmap is
putting Terra in front of 3 to 5 real California TCs. Their feedback ranks every other line
item on this list.

**3. Terra is architecturally a single-user product.** One TC account, backend runs on the
Supabase service-role key (tenant isolation is app-level only), one shared inbound email
address, no signup, no billing, no orgs. That is fine for a demo and fatal for a launch. The
multi-tenant rebuild is the biggest engineering item ahead and it touches auth, email routing,
storage, and every query.

### What Terra genuinely has (the pitch assets that are real)

- **A safety architecture competitors don't have.** Five hard rules enforced in code, not
  policy: money amounts unrepresentable in the system, human-approval-only sends, evidence-
  grounded extraction with an independent identity verifier, append-only audit log enforced at
  the DB level, ZDR gate on any model that sees documents. SkySlope's SmartAudit flags missing
  documents; nothing on the market does evidence-quoted extraction with a verifier clamp. This
  is the differentiated story.
- **Depth on the hardest part.** NBP math (D2/D3), rescission windows per delivery method,
  TRID closing clock with federal holiday calendar, contingency machinery, repair loop,
  cancellation unwind with deposit disposition enums. Competitors do checklists and reminders;
  Terra does the actual date law.
- **End-to-end ingestion.** Email → Postmark → classification → extraction → confirm →
  deadlines, verified live. Universal document reading + deal story synthesis.
- **Engineering hygiene unusual at this stage:** 549 tests, a 12-case eval harness on real
  PDFs, migrations discipline, adversarial audit ritual, verified-ruleset gating.

### The market Terra enters

- TCs charge **$300–500 per file** (2026 national average $350–450); working TCs spend
  **$30–100/month** on software today.
- Competitors: Open To Close ($99–399/mo), SkySlope ($25+/mo, the brokerage compliance
  standard, now shipping AI SmartAudit), ListedKit ($14.99 per contract intake, AI contract
  reading), Trackxi (visual/Kanban + AI extraction), ReBillion, DocJacket. AI intake is now
  table stakes; **AI you can trust with liability is not**, and that is Terra's lane.
- Funding climate: proptech raised $4.5B in H1 2026; seed rounds average ~$6.3M, and 26 US
  proptech pre-seeds in H1 2026 averaged ~$918K. Investors favor recurring-revenue software
  with demonstrable ROI over marketplaces. "AI transaction infrastructure" is explicitly one
  of the strong signals. The money exists for exactly this category.

---

## Part 1 · Gap analysis

Ranked inside each category. ⛔ = blocks pilots. 🔶 = blocks charging money. 🔷 = blocks
scale/acquisition. ▫️ = polish.

### A. Product gaps

| # | Gap | Why it matters |
|---|-----|----------------|
| A1 ⛔ | **Multi-tenancy**: orgs, multiple TC users, roles, real signup/invite, per-tenant data isolation (RLS instead of app-level trust on the service-role key), per-tenant or per-deal inbound email addresses | Cannot onboard a second customer without it. The service-role pattern means one bug = cross-tenant data leak. |
| A2 ⛔ | **Account basics**: password reset, email change, session management, TC-facing notification emails (deadline digests to the TC's real inbox), removal of `SEND_ALLOWLIST` per tenant | A pilot TC locked out of her account on day 2 is a lost pilot. |
| A3 🔶 | **E-signature / forms ecosystem awareness**: TCs live in zipForm/Lone Wolf Transactions, DocuSign, Glide/Compass. Terra needs at minimum "detect signed-ness from these outputs" (has it) plus export/import that respects that workflow, ideally a DocuSign Connect or zipForm integration | The #1 "does it fit my day" question every TC will ask. |
| A4 🔶 | **Billing**: Stripe, per-file pricing (market anchor: ListedKit charges $14.99/intake; a TC making $400/file will pay $15–25/file for real time savings), trial logic | Revenue is the traction metric everything else depends on. |
| A5 🔷 | Broker compliance export (SkySlope/Dotloop-shaped packet) — the Broker File exists; it needs to export in the format brokerages actually accept | TCs must still satisfy their broker's system; Terra should feed it, not fight it. |
| A6 🔷 | Multi-offer intake, listing-side pre-contract (known deferred gaps from tc-universe.md Part 5) | Listing-side TCs are half the market. |
| A7 🔷 | Calendar feed polish, mobile layouts (UI plan P4–P6), per-clause citation click-through | Demo wow + daily usability. |
| A8 ▫️ | CA-only is fine. **Do not build other states yet.** CA is ~1 in 8 US transactions and the wedge story VCs like. | Focus is a feature. |

### B. Trust, security, legal gaps

| # | Gap | Why it matters |
|---|-----|----------------|
| B1 ⛔ | **Anthropic ZDR actually confirmed** + DPA in place; flip `ZDR_CONFIRMED` only then. Until that day, no real client documents may touch the deployed instance (current `SYNTHETIC_ONLY=true` posture is correct) | Real TDS/PA docs contain SSNs-adjacent PII. This is the legal gate on pilots with real files. |
| B2 ⛔ | **Privacy policy + Terms of Service**, CCPA compliance statement (California consumers!), data retention/deletion story | Required before any non-synthetic data from a third party. Template + startup lawyer review, cheap. |
| B3 🔶 | Production hardening: rate limiting, Sentry (or similar) error monitoring, uptime monitoring, DB backups verified/restore-tested, Render paid tier (no cold starts in demos or pilots), API key restrictions (Maps/RentCast), daily compliance cron | The deploy-runbook should-fix list, now mandatory. |
| B4 🔶 | Security review of the party-token invite model (long-lived capability URLs), MFA enforcement policy, secrets rotation runbook, dependency audit | First thing a brokerage security questionnaire asks about. |
| B5 🔷 | **SOC 2 Type I** (~$5–20K, 4–8 weeks with Vanta/Drata-style automation), then Type II within 12–18 months. Trigger: first brokerage-level deal in pipeline, not before | Enterprise buyers treat it as a minimum; solo-TC customers won't ask. Don't spend this money pre-revenue. |
| B6 🔷 | E&O / professional liability posture + explicit "Terra is software, the TC is the professional" positioning reviewed by a real estate attorney (DRE licensed-activity boundaries; RESPA awareness in pricing design) | The "can AI do TC work" question will come from every sophisticated buyer and acquirer. Having a lawyer-reviewed answer is a moat. |

### C. Company gaps (none of this exists yet)

| # | Gap | Notes |
|---|-----|-------|
| C1 🔶 | **Delaware C-corp** formation (Stripe Atlas or Clerky, ~$500), IP assignment into the company, founder stock + 83(b) election within 30 days of issuance | Must exist before any revenue, pilot agreement, or SAFE. Investors only fund Delaware C-corps. |
| C2 🔶 | Business bank account, basic bookkeeping, Terra name/trademark search (there are other "Terra"s in proptech; check collision) | |
| C3 🔷 | Pitch assets: 10–12 slide deck, 3-minute recorded demo video (the Render free-tier cold start must never appear in a live pitch), one-pager, financial model (per-file pricing × TC file volumes), data room folder | Built in Phase 3 below, after pilot data exists to put in them. |
| C4 🔷 | Accelerator applications: **YC** (proptech is an active YC category), Neo, a16z speedrun; student-founder programs given UCLA affiliation | For a solo student founder, an accelerator de-risks the raise more than anything else and is the single most realistic path to a serious seed. |

### D. Validation gaps (the ones that matter most)

| # | Gap | Notes |
|---|-----|-------|
| D1 ⛔ | **Zero real TC has used Terra.** Recruit 3–5 CA TCs for structured interviews + watch-them-use-it sessions (offer $100 gift cards; find them via CAR TC groups, Facebook "Transaction Coordinators" groups, LinkedIn) | This was research-list item #5. It is now the top item on the entire roadmap. |
| D2 ⛔ | No golden demo deal: a scripted, synthetic, start-to-finish transaction (offer → counters → contingencies → NBP → repairs → closing chain → broker packet) that resets on demand for pitches | A live pitch cannot depend on whatever data is in the DB that day. |
| D3 🔶 | No usage metrics: time-to-file, extraction acceptance rate, deadlines caught, hours saved per file. Instrument these; they are the pitch numbers | "Terra cut intake from 45 min to 6 min across 214 files" is the whole deck. |
| D4 🔶 | No design-partner pilots: 2–3 TCs running real (or shadowed) files with a signed pilot agreement | Converts D1's interviews into traction. |

---

## Part 2 · The timeline

Sequenced so validation gates spending: talk to TCs before the multi-tenant rebuild, pilot
before SOC 2, revenue before the raise, traction before acquisition talk. Assumes roughly
full-time effort; stretch 1.5× if part-time around school.

### Phase 0 — Demo-perfect (now → 2 weeks)
*Goal: any moment, any audience, Terra demos flawlessly in 10 minutes.*

- [ ] Build the **golden demo deal**: seed script that creates a complete synthetic CA
      transaction with documents at every stage; one command to reset
- [ ] Write and rehearse a 10-minute demo script (hook: email arrives → extracted with quoted
      evidence → human confirms → deadline machinery lights up → approve-and-send)
- [ ] Record a 3-minute demo video as the fallback for cold starts, bad wifi, and cold emails
- [ ] Render paid tier for the backend (kill the 50-second cold start) or a pre-demo warm-up ritual
- [ ] Fix anything ugly found while rehearsing; run one final audit sweep
- [ ] Register the domain (terra-something.com) and point the frontend at it

### Phase 1 — Validation sprint (weeks 2–6, overlaps Phase 0)
*Goal: 5 real CA TCs have seen Terra; you know the top 5 things they need.*

- [ ] Write the interview script (their current stack, per-file economics, where deals go
      wrong, then watch them react to Terra on the golden deal)
- [ ] Recruit 5 CA TCs (CAR community, TC Facebook groups, LinkedIn, local brokerages;
      offer $100/session)
- [ ] Run the sessions; record with permission
- [ ] Synthesize into `docs/tc-interviews.md`: what they'd pay, what's missing, what's wrong
- [ ] **Re-rank Part 1's gap list against their answers before starting Phase 2 engineering**
- [ ] Ask each: "would you run 2 real files through this next month if I sit with you?" —
      those yeses are Phase 3's pilot cohort

### Phase 2 — Real-product engineering (months 1.5–4)
*Goal: a second customer can sign up and Terra survives them.*

- [ ] **Multi-tenancy** (the big one): orgs + users tables, Supabase RLS policies (retire
      app-level-only isolation), signup/invite flow, per-tenant inbound email routing
      (Postmark per-tenant addresses or plus-addressing), per-tenant SEND controls, migration
      of demo data
- [ ] Account lifecycle: password reset, sessions, MFA enrollment for new users
- [ ] TC notification emails (daily digest + urgent deadline alerts to the TC's own inbox)
- [ ] Production hardening batch: rate limiting, Sentry, uptime monitor, backup restore test,
      API key restrictions, daily compliance cron, `APP_ENV=production` posture verified
- [ ] **ZDR confirmation with Anthropic + DPA signed** → flip `ZDR_CONFIRMED`, retire
      `SYNTHETIC_ONLY` for pilot tenants
- [ ] Privacy policy + ToS + CCPA page (template, then one lawyer review)
- [ ] Instrument the D3 metrics (time-to-file, acceptance rate, deadlines surfaced)
- [ ] Whatever Phase 1 said matters more than any of the above (expect: e-signature-adjacent
      workflow fit, broker packet export format)

### Phase 3 — Design partners & first revenue (months 3–6, overlaps Phase 2)
*Goal: 3 pilot TCs, real files, one of them paying anything at all.*

- [ ] **Form the Delaware C-corp** (Stripe Atlas/Clerky), assign IP, 83(b) within 30 days,
      bank account
- [ ] One-page pilot agreement (free for 90 days, feedback obligations, data terms)
- [ ] Onboard 2–3 pilots from the Phase 1 yeses; white-glove them (you are the onboarding flow)
- [ ] Weekly pilot check-ins; fix their blockers within days, log everything
- [ ] Stripe billing + per-file pricing (start ~$20/file or ~$79/mo unlimited; test both)
- [ ] Convert at least one pilot to paid, at any price. First dollar of revenue is a milestone
      VCs explicitly look for
- [ ] Collect the numbers: files processed, minutes saved, extraction acceptance %, testimonial
      quotes

### Phase 4 — Raise-ready & pitching (months 5–8)
*Goal: an accelerator offer or a pre-seed round.*

- [ ] Apply to **YC** (and Neo, a16z speedrun; UCLA startup programs as warm-up). Application
      demo video comes from Phase 0/3 assets
- [ ] Build the deck (10–12 slides): problem (TC liability + drudgery), demo, safety
      architecture as moat, pilot metrics, CA wedge → national, per-file business model,
      team, ask
- [ ] Financial model: CA ≈ 1 in 8 US transactions; TC fee $350–450/file; Terra takes
      $15–25/file; bottoms-up from pilot usage
- [ ] Data room: incorporation docs, cap table, pilot agreements, metrics dashboard,
      security overview
- [ ] Practice the pitch 20 times; pitch UCLA-adjacent angels and proptech pre-seed funds
      (11 funds invest exclusively at pre-seed; pre-seed proptech rounds averaged ~$918K
      in H1 2026, so a $500K–1M pre-seed on 3 paying pilots is the realistic ask)
- [ ] Decision point: accelerator vs. direct pre-seed vs. revenue-funded. Any of the three
      works; pick whichever offer is strongest

### Phase 5 — Grow into acquirability (months 8–24)
*Goal: the traction that makes Lone Wolf / SkySlope / Compass / a title company call you.*

- [ ] Scale CA: 25 → 100 → 500 TC seats; hire nothing until support drowns you
- [ ] SOC 2 Type I when the first brokerage deal enters the pipeline; Type II clock starts
      immediately after
- [ ] Brokerage/team tier (this is where SkySlope-style compliance export and admin views pay off)
- [ ] Integrations that create switching costs: DocuSign Connect, zipForm/Lone Wolf, MLS data
- [ ] Second state only after CA feels saturated (the verified-ruleset architecture was built
      for this: one `VERIFIED_RULESET` per state)
- [ ] Build acquirer relationships *as partnerships first*: integration conversations with
      Lone Wolf, SkySlope (Fidelity National Financial), Dotloop, First American / title
      companies. Acquirers buy companies they already integrate with. Never open with
      "want to buy us?"
- [ ] Raise a seed (~$3–6M is the 2026 proptech norm) only if the growth math demands it;
      an acquisition can happen from a profitable non-raised position too, and that position
      is stronger

### What to explicitly NOT do

- Don't build other states before CA works commercially.
- Don't pursue SOC 2, patents, or enterprise features before a paying pilot exists.
- Don't take investor meetings before Phase 3 data exists; you get one first impression.
- Don't weaken the five hard rules for a feature request. They are the moat and the pitch.
- Don't hire. Solo + Claude got Terra this far; revenue decides when that changes.

---

## Part 3 · The one-line version of the whole plan

**Weeks 0–2:** make the demo perfect. **Weeks 2–6:** put it in front of 5 real TCs.
**Months 2–4:** multi-tenant + ZDR + legal basics. **Months 3–6:** 3 pilots, first revenue,
incorporate. **Months 5–8:** YC application + pre-seed pitch with pilot numbers.
**Months 8–24:** grow CA seats, integrate with the incumbents, and let the acquisition
conversation start on their side.

---

## Sources

Market/competitors: [ListedKit TC software comparison](https://www.listedkit.com/best-tc-software) ·
[ReBillion AI TC tools 2026](https://rebillion.ai/blog/2026/02/28/ai-transaction-coordinator-tools/) ·
[DocJacket comparison](https://www.docjacket.com/blog/best-transaction-coordinator-software) ·
[Fastio TC software guide](https://fast.io/resources/real-estate-transaction-coordinator-software/) ·
[CloudCoord TC cost](https://cloudcoordinator.io/transaction-coordinator-cost) ·
[Paperless Pipeline TC fees](https://www.paperlesspipeline.com/blog/how-to-determine-your-transaction-coordinator-fee-everything-tcs-need-to-know) ·
[AgentUp TC pricing 2026](https://www.agentup.com/blog/real-estate-transaction-coordinator-pricing) ·
[CRES on TC fees & RESPA](https://www.cresinsurance.com/transaction-coordinator-fees-and-respa-violations/)

Funding climate: [Crunchbase proptech sector snapshot](https://news.crunchbase.com/venture/proptech-funding-holds-exits-ipo-ai-green-steel-2026/) ·
[Commercial Observer on 2026 proptech seed rounds](https://commercialobserver.com/2026/08/proptech-seed-rounds-2026-amounts/) ·
[CRETI early-stage proptech capital](https://creti.org/insights/whos-investing-in-proptech-inside-the-early-stage-capital-shaping-the-market-in-2026) ·
[Qubit proptech VC directory](https://qubit.capital/blog/proptech-vc-directory) ·
[YC proptech companies](https://www.ycombinator.com/companies/industry/proptech) ·
[MarketScale AI proptech wave](https://www.marketscale.com/industries/engineering-and-construction/ai-and-automation-fuel-a-new-wave-of-real-estate-and-property-tech-investment)

M&A landscape: [Compass–Anywhere 8-K](https://www.sec.gov/Archives/edgar/data/1398987/000119312525210057/d26146dex991.htm) ·
[Lone Wolf acquisition history](https://www.lwolf.com/about) ·
[HousingWire on Lone Wolf + Propertybase](https://www.housingwire.com/articles/lone-wolf-builds-tech-empire-with-propertybase/) ·
[Real Estate News: Lone Wolf AI push](https://www.realestatenews.com/2026/07/28/lone-wolf-investing-in-ai-with-recruitment-retention-tools)

SOC 2: [Rippling SOC 2 for startups](https://www.rippling.com/blog/soc-2-for-startups) ·
[Workstreet SOC 2 guide](https://www.workstreet.com/blog/soc-2-for-startups) ·
[Lorikeet on enterprise SOC 2 expectations](https://lorikeetsecurity.com/blog/soc2-for-saas-companies) ·
[Promise Legal SOC 2 roadmap](https://promise.legal/guides/soc2-roadmap)
