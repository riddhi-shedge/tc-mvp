# California Deadline Rules — Verification Sheet (Phase 5 BLOCKER)

**Status: ✅ VERIFIED against the current C.A.R. RPA revision 6/26 (June 2026),
by Riddhi Shedge on 2026-07-18, reading values directly off the form. This
CLEARS the Phase 5 day-count blocker.** The premise question is resolved — the
current revision is **6/26** (C.A.R. gave the June 2026 release its own code).
Per-item verified values are in the "Verified value" columns; the canonical
encode-ready ruleset is immediately below; sign-off is at the bottom.

## Verified ruleset (RPA 6/26) — canonical, encode this

**Anchor:** all "Days After" deadlines count from **Acceptance** = the offer
signed AND that acceptance received back by the other party or their agent
(standard definition, accepted). Day 1 = the **day after** Acceptance.

**Day-counting:** calendar days; weekends/CA-Gov-Code holidays in the middle
count; if the **final** day is a weekend/CA legal holiday it **rolls to the next
working day** — EXCEPT the three hard deadlines below, which never roll.

**Holidays:** California Government Code holidays (state, not federal).

| Deadline | Value | Counting | Rolls? |
|---|---|---|---|
| Initial deposit | 3 | **business days** | (business-days math) |
| Inspection contingency | 17 | calendar Days after Acceptance | yes |
| Loan contingency | 21 | calendar Days after Acceptance | yes |
| Appraisal contingency | 17 | calendar Days after Acceptance | yes |
| Insurance contingency | 17 | calendar Days after Acceptance | yes |
| Seller disclosure delivery | 7 | calendar Days after Acceptance | **NO — hard** |
| Verification of funds | 3 | calendar Days after Acceptance | yes |
| Close of Escrow | (per contract) | Days after Acceptance | yes |
| Possession | COE + N | **calendar days** | **NO** |
| Acceptance (anchor) | — | — | **NO — never moves** |

**Notices/closing:** NBP delivered no earlier than **2 Days before** its target
deadline; recipient gets **2 Days** to perform. Demand to Close Escrow delivered
no earlier than **3 Days before** COE; gives **≥3 Days** to close.

**Statutory rescission clocks (primary law, separate from the RPA):** TDS
(Civ. §1102.3) and NHD (Civ. §1103.3(c)) — both **3 days** if personal delivery,
**5 days** if by mail or electronic record.

**Mechanic for the risk framework (not a date):** 6/26 loan contingency cannot be
used if the buyer is unable to obtain insurance (loan↔insurance interaction).

Prepared 2026-07-14 by `ca-rules-researcher`. **Critical limitation:** the
current-revision (12/25) C.A.R. RPA and the NBP/CR forms are member-gated on
car.org; the researcher could **not read the literal form text** and
triangulated from secondary sources, several describing **older revisions
(12/18–6/24)**. As a result almost every default day-count is UNVERIFIED and I
(Claude) **cannot verify them for you** — this requires a human with the actual
current forms in hand. Per Rule 1, form text is paraphrased, never quoted.

## How to use this sheet

For each row: check the claim against the **literal current 12/25 RPA** (and
the current NBP/CR forms), then either confirm it or write the correct value in
the "Verified value" column. Every ❓/⚠️ row must be resolved. Then sign off.
**Until you do, Phase 5 does not start** — wrong date math silently corrupts
every downstream task (§18 risk register).

Legend: ✅ well-corroborated (still verify) · ⚠️ conflicting sources · ❓ could
not confirm against the current form (UNVERIFIED)

---

## Second-pass research update (2026-07-17)

A focused second research pass ran to narrow the unverified set from accessible
authoritative sources. It still could **not** read the gated 12/25 forms, so
**this does not clear the blocker** — but it resolved the two statutory clocks
from **primary law**, corrected two errors in the first draft, and shrank the
list of items that truly require the literal form. Full detail below; the A–F
tables are annotated where this pass changed them.

**Resolved from primary statute (high confidence — read directly on leginfo):**
- **F1 — TDS rescission, Civ. Code §1102.3:** buyer may terminate in writing
  within **3 days after personal delivery**, or **5 days after** delivery by mail
  or by electronic record. Confirmed against current statute text.
- **F3 — NHD rescission: the first draft's citation was WRONG.** The rescission
  right is **not** in Govt. Code §8589.3 (that only creates the disclosure duty)
  nor Civ. §1103.2 (form content). It is **Civ. Code §1103.3(c)**, and it uses the
  **same day counts as F1** (3 personal / 5 mail / 5 electronic). Good for the
  engine: one rescission-window rule, two triggers. Fix the citation in F3.

**Corrections to the first draft:**
- **A7 was WRONG** ("found no backward-from-COE deadline"). A backward-counting
  rule **does** exist: the **Demand to Close Escrow (DCE)** — deliverable no
  earlier than **3 Days prior to scheduled COE**, giving ≥3 Days to close
  (3 independent sources; one cites ¶14G, which the 12/25 renumber may have
  moved). This should likely be modeled in the date engine — human to confirm the
  paragraph ref + that "3 Days prior" is unchanged.
- **A5 now resolved (moderate):** the 7-day disclosure-delivery window **does**
  roll on its final day like other Days-After deadlines (concrete rolling example
  found); no source says it's a hard non-rolling deadline.
- **D3 likely reconciled:** "24 hours vs 2 Days" is probably floor-vs-default —
  24 hours reads as the legal/contractual **minimum** the NBP must allow, while
  the printed **default** filling the blank is **2 Days**. Moderate confidence;
  human should check whether the form's blank is pre-filled "2 Days."
- **A6 narrowed:** CA's general statutory "legal holiday" definition is Gov. Code
  §6700 (CA state holidays, ≠ federal list). Unconfirmed whether the RPA's
  Definitions paragraph actually cross-references §6700 vs. leaving the term
  undefined — needs the literal form.

**PREMISE QUESTION — resolve this FIRST (new, affects the whole sheet):** the
Dec 2025 release is "12/25" (only FinCEN + electrical-inspection changes, no
day-count impact). But a **June 2026 C.A.R. forms release** reportedly made
**substantive RPA changes** (seller-credit handling, an appraisal-gap option, new
inspection cost-allocation options, a loan-vs-insurance-contingency interaction),
and two association sources say the **revision label still reads "12/25."** Check
the literal footer/date stamp on the form you actually have — verifying against a
form one cycle behind would corrupt everything. Confirm which RPA you're holding
before resolving the rows below.

**Shortest list that genuinely needs the human + the literal current form:**
1. **C1** — initial deposit: "**3 business days**" (an exception to calendar-day
   counting) or "3 Days"? Highest priority — changes the math for this field.
2. **C5** — insurance-contingency default day count, or confirm there is **no**
   default (blank must be filled).
3. **C7** — verification of down payment/closing costs: **3 Days vs 7 Days**
   (direct source conflict — do NOT treat 3 as settled).
4. **D3** — confirm the printed NBP cure default (2 Days?) vs. the 24-hour floor.
5. **A4** — is Acceptance itself extended if it lands on a weekend/holiday?
6. **A6** — does "legal holiday" cross-reference Gov. Code §6700?
7. **A7** — confirm the DCE paragraph ref and that "3 Days prior" is current.
8. **E2** — does possession (COE + N Days) roll like other Days-After deadlines?
9. The **revision-label** premise question above.

**Still-conflicting (look closely):** C7 (3 vs 7 Days); D3 (24h vs 2 Days);
the revision label (substantive June-2026 changes vs. an unchanged "12/25" stamp).

**Well-corroborated across this pass (still verify the paragraph refs against
12/25):** A1–A3 (calendar days, final-day-only roll incl. COE), B1–B2 (acceptance
trigger), C2/C4 (inspection/appraisal 17 Days), C3 (loan 21 Days — best-dated
sources cite 12/22, none confirm 12/25), C6 (disclosure 7 Days), D1/D2/D4 (active
removal; NBP earliest = 2 Days prior; seller must NBP before cancelling).

*Caveat carried from the sources: the best-dated secondary sources that name a
revision cite **12/22–6/24**, not 12/25 — cross-source agreement is high but is
not a substitute for reading the current form.*

---

## A. Day-counting mechanics

| # | Claim (from research) | Confidence | Verified value / notes |
|---|---|---|---|
| A1 | "Days" = calendar days; "Days After" excludes the trigger day; period ends 11:59 PM on the final day | ✅ (3 sources) | ✅ VERIFIED 6/26: calendar days; day 1 = the day after Acceptance |
| A2 | Only the **final** day rolls; intermediate weekends/holidays count normally | ✅ | ✅ VERIFIED 6/26: middle weekends/holidays still count |
| A3 | The final-day roll (Sat/Sun/legal holiday → next day) applies broadly **including Close of Escrow** | ✅ but verify scope | ✅ VERIFIED 6/26: final day rolls to the next working day, incl. Close of Escrow |
| A4 | Acceptance itself does NOT get the weekend/holiday extension | ❓ (1 source only) | ✅ VERIFIED 6/26: **EXCEPTION — the Acceptance date does NOT move** |
| A5 | Disclosure-delivery (7-day) window: does it roll, or is it a hard calendar deadline? | ❓ conflicting | ✅ VERIFIED 6/26: **EXCEPTION — does NOT roll; a hard 7-calendar-day deadline** (corrects the research guess) |
| A6 | "Legal holiday" = California state holidays vs federal — **which?** | ❓ unconfirmed | ✅ VERIFIED 6/26: **California Government Code** holidays (state, e.g. §6700) — NOT federal |
| A7 | Any deadline computed BACKWARD from COE (e.g. "X days before COE")? Research found none | ❓ verify none exist | ✅ VERIFIED 6/26: **Demand to Close Escrow exists** — deliver no earlier than **3 Days prior** to COE, giving **≥3 Days** to close. Model it. |

## B. Trigger date

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| B1 | "Acceptance" = written acceptance personally received by the other party or their authorized agent | ✅ | ✅ VERIFIED 6/26: accepted as the standard definition (signed AND received back by the other party/their agent) — anchor for all Days-After deadlines |
| B2 | Day-counting for "Days After Acceptance" starts the day AFTER acceptance | ✅ | ✅ VERIFIED 6/26: day 1 = the day after Acceptance (per A1) |

## C. Default periods (blank not filled) — ALL UNVERIFIED against 12/25

| # | Field | Researched default | Verified default (against 12/25 form) |
|---|---|---|---|
| C1 | Initial deposit due | 3 days — **⚠️ "business days" vs "Days" unclear** | ✅ **VERIFIED 6/26: 3 business days** — an EXCEPTION to the calendar-day rule (business-days counting skips all weekends/holidays, not just the final day) |
| C2 | Investigation/inspection contingency | 17 Days | ✅ VERIFIED 6/26: 17 Days |
| C3 | Loan contingency | 21 Days — ⚠️ brief noted some sources say 17; researcher found none confirming 17 | ✅ VERIFIED 6/26: 21 Days (see 6/26 loan-vs-insurance interaction note below) |
| C4 | Appraisal contingency | 17 Days | ✅ VERIFIED 6/26: 17 Days (the 6/26 appraisal-gap option is separate, not a period change) |
| C5 | Insurance contingency (added 6/24) | ❓ **no source gave a default** | ✅ **VERIFIED 6/26: 17 Days** (same as the inspection period) |
| C6 | Seller disclosure delivery | 7 Days (from a 12/18 source) | ✅ VERIFIED 6/26: 7 Days |
| C7 | Verification of down payment/closing costs | 3 Days (from a 12/22 source) | ✅ **VERIFIED 6/26: 3 Days** (conflict resolved — 3, not 7) |

**Note:** paragraph numbers the research cited (3H, 3L(4), 8D, 12D) are from
12/22–6/24 and may be renumbered in 12/25. The Dec 2025 release reportedly
reordered several sections. Do not rely on paragraph refs without checking.

## D. Active removal / NBP mechanics (load-bearing for risk flags)

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| D1 | CA contingencies are ACTIVELY removed — survive their deadline until removed in writing (form CR/CR-B) | ✅ | |
| D2 | An NBP may not be delivered earlier than **2 Days prior** to the deadline | ✅ (verify) | ✅ VERIFIED 6/26: yes — no earlier than 2 Days prior |
| D3 | NBP cure window after delivery: **24 hours vs 2 Days — ⚠️ sources conflict** (load-bearing for "loan contingency approaching") | ⚠️ | ✅ VERIFIED 6/26: **2 Days** (printed default; resolves the 24h-vs-2-Day conflict) | |
| D4 | Seller cannot cancel without first issuing an NBP (or a Demand to Close for COE) | ✅ | |

## E. COE / possession

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| E1 | COE "N Days After Acceptance" uses the §A Days-After rule and rolls on the final day | ✅ (for COE) | ✅ VERIFIED 6/26: COE rolls on the final day (per A3) |
| E2 | Possession "at COE + N Days" rolls the same way | ❓ inferred by analogy, not sourced | ✅ VERIFIED 6/26: **does NOT roll — possession counted in plain calendar days** |

## F. Statutory overlays (separate from RPA blanks)

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| F1 | TDS late-delivery rescission (Civ. Code §1102.3): 3 days if personal delivery, 5 days if by mail or electronic record; buyer may terminate in writing | ✅ statute cited | 2nd pass: confirmed against current §1102.3 statute text (primary source) |
| F2 | Model this as a SEPARATE rescission-risk clock, not the RPA's 7-day contractual delivery deadline | ✅ (design note) | |
| F3 | NHD separate statutory rescission window | ✅ **2nd pass RESOLVED from primary law** | **Citation corrected: it's Civ. Code §1103.3(c) (NOT Govt §8589.3, which is only the disclosure duty). Same counts as F1: 3 personal / 5 mail / 5 electronic** |

## G. §6 risk-flag thresholds — RULE vs CONVENTION (your product decisions)

The research confirms **none of these thresholds are RPA rules** — they are
product decisions for you to set. Only the underlying deadlines are rules.

| Flag | Underlying rule | Your chosen trigger (product decision) |
|---|---|---|
| Inspection not scheduled | inspection contingency deadline (C2) | e.g. flag if unscheduled N days before? |
| Appraisal not ordered | appraisal deadline (C4) | |
| Loan contingency approaching | loan deadline (C3); NBP earliest = 2 days prior (D2) | N days before? |
| Earnest money not confirmed | deposit due (C1) | |
| Disclosures unsigned | TDS rescission clock (F1) | |
| Missing escrow contact | none (pure convention) | |
| Closing near with open tasks | COE (E1) | define "near" = N days? |

## Open questions — only a human with the current forms can answer

- [ ] Do you have access to the literal **12/25 RPA** and current **NBP**
      form text? (If yes, resolve every ❓/⚠️ above. If no, Phase 5 cannot
      proceed on verified rules.)
- [ ] Confirm the six C1–C7 default periods against the current form.
- [ ] Resolve the NBP cure window (D3): 24 hours or 2 Days?
- [ ] "Legal holiday" definition (A6): CA state or federal?
- [ ] Choose the §G risk-flag thresholds (product decisions).

## Sign-off

- [x] I verified the rules above against the current C.A.R. RPA (**revision 6/26**)
      and its NBP/DCE provisions, reading values directly off the form. The values
      in the "Verified value" columns (and the canonical ruleset near the top) are
      authoritative and may be encoded into the Phase 5 date-math engine.

Verified by: **Riddhi Shedge**   Date: **2026-07-18**   Form revision: **RPA 6/26**

*✅ Signed 2026-07-18 — the §12 dependency gate / §18 "human-verify the CA rules"
blocker is CLEARED for the day-count ruleset (RPA 6/26). The canonical ruleset
above may now be encoded into the Phase 5 date-math engine.*
