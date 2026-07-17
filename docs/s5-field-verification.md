# §5 Extraction Field List — Verification Sheet

**Status: VERIFIED — approved as proposed by Riddhi Shedge on 2026-07-13
(recorded sign-off in the tc-mvp build session). The §5 half of the Phase 4
gate is cleared; the approved v2 list is encoded in TC-Build-Requirements.md
§10.**

Prepared 2026-07-13 from sourced research on the current C.A.R. RPA (December
2025 revision). The research cross-checked every row of the draft §5 table in
`TC-Build-Requirements.md` §10. Verify with a current blank RPA-CA in hand if
possible — two items below are explicitly UNVERIFIED at form-level precision.

**How to use:** review each ⚠️/❓ row, apply or reject the proposed action,
tick the sign-off checklist at the bottom, and tell Claude "the §5 list is
verified" (with any edits). Scope note: Phase 4 extracts **what is written on
the signed form**; the *default* day-counts cited here are CA-rule content
that gets its own verification in Phase 5 — they are context, not spec.

## Form-version context (research findings)

- Current form: **RPA Revised 12/25** (Dec 2025), after Jun 2025, Dec 2024 and
  Jun 2024 revisions. ([behappytc.com](https://www.behappytc.com/blog/december-2025-car-forms-release), [tylerlawllp.com](https://www.tylerlawllp.com/blog-posts/new-c-a-r-forms-for-2026-key-updates-realtors-r-must-know-fall-december-2025-releases))
- Jun 2024 added a **standalone insurance contingency**. ([cresinsurance.com](https://www.cresinsurance.com/changes-residential-purchase-agreement-rpa/))
- Dec 2024 moved the **increased deposit** to a separate Increased Deposit
  Addendum (IDA). ([tylerlawllp.com](https://www.tylerlawllp.com/blog-posts/c-a-r-updated-and-new-forms-coming-in-2025))
- Dec 2025 added FinCEN reporting language (¶19 H–I) — escrow-side reporting,
  **no new extraction fields**. ([behappytc.com](https://www.behappytc.com/blog/december-2025-car-forms-release))
- **Rule 2 confirmed:** the RPA contains **no wiring instructions or bank
  account details** — those live in separate escrow instructions; C.A.R.
  bundles a Wire Fraud Advisory instead. ([relaxedagent.com](https://www.relaxedagent.com/real-estate-documents/wire-fraud-advisory), [titleadvantage.com](https://www.titleadvantage.com/mdocs/Wire%20Fraud%20Advisory.pdf))

## Row-by-row verdicts

Legend: ✅ confirmed on form as drafted · ⚠️ discrepancy — action proposed ·
❓ needs your judgment / form-in-hand check

| Draft field | Deadline-driving (draft) | Verdict | Notes + proposed action |
|---|---|---|---|
| Buyer name(s) | No | ✅ | Opening block. |
| Seller name(s) | No | ✅ | Opening block. |
| Property address | No | ✅ | Opening block (address, city, county). |
| APN | No | ✅ | Opening block. |
| Purchase price | No | ✅ | ¶3 finance grid. |
| Initial deposit (amount) | No | ⚠️ | Amount ✅ (¶3). But its **due timing** (default 3 business days after acceptance) is a tracked deadline — the draft captures that as a separate row below; keep both. Never wiring details (confirmed absent from form). |
| Increased deposit | No | ⚠️ | Since Dec 2024 usually on the separate **IDA addendum**, not the RPA body. **Action:** keep the field but mark "may arrive via addendum"; Phase 4 extraction of the RPA alone may legitimately return nothing. |
| Loan amount / financing type | No | ✅ | ¶3 (conventional/FHA/VA…). |
| Down payment | No | ✅ | ¶3. |
| All-cash? | No | ✅ | ¶3 option; affects which contingencies apply. |
| Acceptance date | **Yes** | ⚠️ | Legally operative "Acceptance" = personal receipt of signed acceptance/final counter; the form's **Confirmation of Acceptance** field is optional evidence and may be blank. **Action:** extract the confirmation-of-acceptance date when present but flag it low-confidence; the TC confirms the true acceptance date at the gate. ([esquire-re.com](http://www.esquire-re.com/blog/2016/1/20/what-does-that-term-mean-the-difference-between-acceptance-and-acceptance-and-other-specially-defined-terms)) |
| Close of escrow (COE) | **Yes** | ✅ | ¶3: specific date OR days-after-acceptance — extraction must capture **which form** it takes. |
| EMD due (days after acceptance) | **Yes** | ✅ | Default 3 **business** days (note: the only business-day default; the rest are calendar "Days After" per ¶14). |
| Inspection/investigation contingency (days) | **Yes** | ✅ | Default 17 days. |
| Loan contingency (days) | **Yes** | ✅ | Default 21 days, or waived. |
| Appraisal contingency (days) | **Yes** | ✅ | Default 17 days, separate from loan contingency (removing one ≠ removing the other). |
| **Insurance contingency (days)** | **Yes** | ⚠️ **MISSING from draft** | Standalone contingency since Jun 2024 with its own removal item. **Action: add** — period field (deadline-driving) + "insurance contingency present?" flag. ([cresinsurance.com](https://www.cresinsurance.com/changes-residential-purchase-agreement-rpa/)) |
| Seller-disclosure delivery (days) | **Yes** | ✅ | Default 7 days (¶14). |
| Contingency removal date(s) | **Yes** | ⚠️ **REMOVE from PA-extraction list** | Removals are separate documents (Form CR / CR-B, Rev 6/24) — they are **not on the RPA**. Removal *deadlines* are computed by the Phase 5 service; actual removals arrive as their own ingested docs (active-removal regime; seller recourse is an NBP). **Action:** drop this row from §5; add `contingency_removal` to the ingestion doc-type taxonomy later. ([relaxedagent.com](https://www.relaxedagent.com/real-estate-documents/contingency-removal), [cooperfamilyrealestate.com](https://cooperfamilyrealestate.com/blog/california-contingency-removal-timeline-day-by-day)) |
| Possession date / time | **Yes** | ✅ | ¶2/¶3M; longer seller occupancy via PAA addendum. |
| Verification of funds deadline | Maybe | ⚠️ | Buyer's verification of down payment + closing costs, default **3 Days After Acceptance** — a real tracked deadline. **Action: change "Maybe" → Yes.** |
| Loan contingency present? / Appraisal present? / Inspection present? (flags) | No | ✅ | Keep; add the insurance flag (above). |
| Buyer's agent / brokerage | No | ✅ | Signature/broker section (incl. DRE license numbers). |
| Listing agent / brokerage | No | ✅ | Signature/broker section. |
| Escrow holder / company | No | ✅ | Dedicated Escrow Holder Acknowledgment section (company, escrow number). |
| Title company | No | ❓ | Referenced by role/requirements; **no dedicated name/contact block confirmed**. Likely often blank on the PA — keep as optional, expect low extraction yield. |
| Lender / loan officer | No | ❓ | Research found **no dedicated lender contact block** on the form (UNVERIFIED at ¶-level). The Phase 6 lender follow-up needs this contact — **decide the source**: extracted opportunistically if written in, else entered by the TC. |

## Open questions — only you can answer

- [ ] Confirm against a current blank **RPA 12/25**: is there any lender
      name/contact field? Any title-company field? (Research: UNVERIFIED.)
- [ ] Accept **adding** the insurance contingency (period + flag)?
- [ ] Accept **removing** "contingency removal date(s)" from the PA-extraction
      list (removals arrive as CR/CR-B documents)?
- [ ] Accept **Verification of funds → deadline-driving Yes**?
- [ ] Accept the Acceptance-date handling (extract Confirmation of Acceptance
      when present, low-confidence, TC confirms the operative date)?
- [ ] Increased deposit: agree it may arrive via the IDA addendum (RPA
      extraction may return nothing for it)?
- [ ] Any fields YOUR workflow needs that aren't listed?

## Sign-off

- [x] I verified the list above (with the edits I've noted) against the
      current form / my spec. The §5 field list is APPROVED for encoding.

Verified by: Riddhi Shedge (approved as proposed)  Date: 2026-07-13

Open follow-up carried forward (non-blocking): confirm against a blank
RPA 12/25 whether any lender/title contact field exists — until then, lender
contact is sourced from the TC (Phase 6 asks for it if missing).

*Once signed off, Claude updates TC-Build-Requirements.md §10 to the approved
v2 list, marks §19's blocker cleared, and the §5 half of the Phase 4 gate is
open. Default day-counts (17/21/17/7/3/3) remain provisional until Phase 5's
CA-rules verification.*
