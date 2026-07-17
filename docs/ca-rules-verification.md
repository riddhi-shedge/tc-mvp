# California Deadline Rules — Verification Sheet (Phase 5 BLOCKER)

**Status: RESEARCH DRAFT — NOT VERIFIED. This does NOT clear the Phase 5
blocker. Nothing here may be encoded into date math until you verify it against
the literal current form (§11, §18).**

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

## A. Day-counting mechanics

| # | Claim (from research) | Confidence | Verified value / notes |
|---|---|---|---|
| A1 | "Days" = calendar days; "Days After" excludes the trigger day; period ends 11:59 PM on the final day | ✅ (3 sources) | |
| A2 | Only the **final** day rolls; intermediate weekends/holidays count normally | ✅ | |
| A3 | The final-day roll (Sat/Sun/legal holiday → next day) applies broadly **including Close of Escrow** | ✅ but verify scope | |
| A4 | Acceptance itself does NOT get the weekend/holiday extension | ❓ (1 source only) | |
| A5 | Disclosure-delivery (7-day) window: does it roll, or is it a hard calendar deadline? | ❓ conflicting | |
| A6 | "Legal holiday" = California state holidays vs federal — **which?** | ❓ unconfirmed | |
| A7 | Any deadline computed BACKWARD from COE (e.g. "X days before COE")? Research found none | ❓ verify none exist | |

## B. Trigger date

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| B1 | "Acceptance" = written acceptance personally received by the other party or their authorized agent | ✅ | |
| B2 | Day-counting for "Days After Acceptance" starts the day AFTER acceptance | ✅ | |

## C. Default periods (blank not filled) — ALL UNVERIFIED against 12/25

| # | Field | Researched default | Verified default (against 12/25 form) |
|---|---|---|---|
| C1 | Initial deposit due | 3 days — **⚠️ "business days" vs "Days" unclear** | |
| C2 | Investigation/inspection contingency | 17 Days | |
| C3 | Loan contingency | 21 Days — ⚠️ brief noted some sources say 17; researcher found none confirming 17 | |
| C4 | Appraisal contingency | 17 Days | |
| C5 | Insurance contingency (added 6/24) | ❓ **no source gave a default** | |
| C6 | Seller disclosure delivery | 7 Days (from a 12/18 source) | |
| C7 | Verification of down payment/closing costs | 3 Days (from a 12/22 source) | |

**Note:** paragraph numbers the research cited (3H, 3L(4), 8D, 12D) are from
12/22–6/24 and may be renumbered in 12/25. The Dec 2025 release reportedly
reordered several sections. Do not rely on paragraph refs without checking.

## D. Active removal / NBP mechanics (load-bearing for risk flags)

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| D1 | CA contingencies are ACTIVELY removed — survive their deadline until removed in writing (form CR/CR-B) | ✅ | |
| D2 | An NBP may not be delivered earlier than **2 Days prior** to the deadline | ✅ (verify) | |
| D3 | NBP cure window after delivery: **24 hours vs 2 Days — ⚠️ sources conflict** (load-bearing for "loan contingency approaching") | ⚠️ | |
| D4 | Seller cannot cancel without first issuing an NBP (or a Demand to Close for COE) | ✅ | |

## E. COE / possession

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| E1 | COE "N Days After Acceptance" uses the §A Days-After rule and rolls on the final day | ✅ (for COE) | |
| E2 | Possession "at COE + N Days" rolls the same way | ❓ inferred by analogy, not sourced | |

## F. Statutory overlays (separate from RPA blanks)

| # | Claim | Confidence | Verified value / notes |
|---|---|---|---|
| F1 | TDS late-delivery rescission (Civ. Code §1102.3): 3 days if personal delivery, 5 days if by mail or electronic record; buyer may terminate in writing | ✅ statute cited | |
| F2 | Model this as a SEPARATE rescission-risk clock, not the RPA's 7-day contractual delivery deadline | ✅ (design note) | |
| F3 | NHD separate statutory rescission window (Govt Code §8589.3 / Pub. Res. Code) | ❓ needs dedicated research if encoded | |

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

- [ ] I verified the rules above against the current C.A.R. RPA (12/25) and NBP/CR
      forms. The values in the "Verified value" columns are authoritative and may
      be encoded into the Phase 5 date-math engine.

Verified by: ____________  Date: ____________

*Until this is signed, Phase 5 (compliance/timeline service) stays blocked
(§12 dependency gate; §18 "Wrong CA deadline rules → human-verify the
researcher's output"). Claude will not encode any of these numbers unverified.*
