# The TC Universe — everything in a CA residential deal, vs. what Terra does today

*Research pass 2026-09-02. Sources: TC checklist guides (Transactly, ListedKit, Paperless
Pipeline, Icenhower, Ashby & Graff), C.A.R. sales-disclosure checklist + forms library,
CA DRE escrow references, CA escrow-process guides (805title, First California Escrow,
Cal-West), plus this repo's own `docs/ca-rules-verification.md` and shipped code.*

---

## Part 1 — The full lifecycle of a residential deal (10 phases)

### Phase 0 · Pre-contract (listing side)
Listing agreement (RLA) signed · seller advisories (SBSA) · agency disclosure (AD) ·
seller completes TDS/SPQ (or ESD if exempt) · NHD ordered · pre-listing inspections
(optional) · MLS entry · marketing · showings · offer collection.

### Phase 1 · Offer & negotiation
Buyer's offer (RPA) + proof of funds + preapproval letter · seller counter (SCO) /
buyer counter (BCO) chains · multiple-offer handling (SMCO) · addenda (ADM, PAA) ·
**Acceptance** = signed + delivered back. Every deadline anchors here.

### Phase 2 · Opening (days 0–3)
Open escrow, get escrow number · EMD wired/delivered (default 3 business days; often 1) ·
escrow issues receipt · TC intro emails to ALL parties w/ critical-dates timeline ·
executed contract package distributed · broker file opened (compliance copy) ·
lender notified, loan application confirmed · prelim title report ordered ·
NHD report ordered · HOA docs ordered (if applicable — statutory delivery duty).

### Phase 3 · Disclosures (days 0–7)
Seller delivers: TDS, SPQ, NHD, lead paint (FLD), water heater/smoke detector (WHSD),
Megan's Law, military ordnance, death-on-property, supplemental local/city disclosures,
AVID (agent visual inspection), AD/possible DA (dual agency), SBSA · buyer signs/returns
each · **statutory rescission clocks**: TDS/NHD delivery gives buyer 3 days (personal) /
5 days (mail) to rescind — separate from contract contingencies, and they do NOT roll.

### Phase 4 · Contingency period (days 0–17, the crunch)
Inspections: general home, termite/pest (WDO), roof, sewer/septic, chimney, pool,
foundation/soil as needed · buyer reviews reports · **Request for Repairs (RR)** →
seller response → repair addenda or credits · appraisal ordered/completed — value vs.
price; FHA/VA amendatory escape clause interacts here · loan underwriting →
conditional approval · insurance quote/binder (fire in wildfire zones can kill deals) ·
buyer reviews prelim title (liens, easements, vesting) + HOA docs · verification of
funds · **Contingency Removal (CR)** forms — CA is active-removal: nothing expires
silently · if buyer stalls: **Notice to Buyer to Perform (NBP)** (2-day cure, earliest
2 days before deadline) · possible price renegotiation after appraisal/inspections (PAA).

### Phase 5 · Mid-escrow operations
Weekly all-party status updates · loan conditions chased · escrow amendments ·
home warranty ordered (per RPA allocation) · HOA transfer fees arranged · utility
transfer reminders · smoke/CO/water-heater compliance verified (WHSD) · termite
Section 1 clearance if negotiated · buyer wire-fraud warnings before any funds move.

### Phase 6 · Closing prep (COE−7 → COE−2)
Loan approved → **loan documents to escrow** · Closing Disclosure (CD) to buyer —
federal 3-business-day review before signing · signing appointments w/ notary ·
buyer's cashier's check/wire for down payment + closing costs · seller signs grant
deed · **final verification of condition / walk-through (VP)** — default COE−5 ·
repairs verified complete w/ receipts · estimated settlement statements reviewed.

### Phase 7 · Sign → Fund → Record (the three-step close)
Docs signed + notarized → returned to lender · lender funds (wires to title) ·
county recorder records grant deed + deed of trust — **recording IS the close** ·
confirmation of recording → keys released per possession terms (on recording, or
seller rent-back per SIP form).

### Phase 8 · Possession & close-out
Keys/garage remotes/mailbox transferred · possession per contract (recordation / +N
days / rent-back) · final settlement statements to both sides · commission disbursed
(broker demand paid) · home warranty confirmation delivered · utilities switched.

### Phase 9 · Post-closing
Complete broker compliance file (every signed doc — brokers audit) · closed-file
packet to client (all docs, settlement statement, warranty info) · recorded deed
arrives by mail · review/testimonial ask · tax-time reminder (settlement statement) ·
archive per DRE retention (3 years) · fall-through handling if deal died: Cancellation
(CC form), deposit release/dispute, re-listing support.

---

## Part 2 — The document multiverse (by family)

**Contract set:** RPA · SCO/BCO/MCO counter chain · ADM/PAA addenda · ETA (extension) ·
COP (sale-of-other-home contingency) · CR (contingency removal) · NBP/NSP (notices to
perform) · RDN (receipt of notices) · RR (request for repairs) · CC (cancellation) ·
SIP/RLAS (seller in possession / rent-back) · TCS (transaction cover sheet).

**Agency & advisories:** AD · DA (dual) · SBSA · BIA (buyer inspection advisory) ·
FHDA (fair housing) · WFA (wire fraud advisory) · PRBS (broker relationships).

**Seller disclosures:** TDS · SPQ · ESD (exempt) · AVID · FLD (lead) · WHSD ·
NHD report · Megan's Law notice · death/material facts · local/city disclosures ·
insurance claims history (CLUE).

**Reports:** general home inspection · termite/WDO (+ Section 1/2 clearance) · roof ·
sewer · chimney · pool · mold · soil/geo · preliminary title report · HOA package
(CC&Rs, bylaws, financials, minutes, litigation) · appraisal.

**Financing:** preapproval letter · proof of funds · loan estimate · FHA/VA amendatory
clause · loan conditions list · final loan approval · Closing Disclosure (CD) ·
promissory note + deed of trust (at signing).

**Escrow & title:** escrow instructions (joint, in RPA) · amended instructions · escrow
receipt for EMD · demands (payoff, broker commission) · estimated + final settlement
statements · grant deed · title insurance policies (owner's + lender's) · recording
confirmation.

**Ops artifacts:** TC intro emails · critical-dates timeline · weekly status updates ·
repair receipts · home-warranty invoice/confirmation · utility/possession memos ·
commission disbursement (CDA).

---

## Part 3 — Party interaction matrix (who the TC talks to, about what)

| Counterparty | The TC's threads with them |
|---|---|
| Buyer | intro, disclosure signing chases, wire-fraud warning, deposit verification, walk-through scheduling, key handoff, closing packet |
| Seller | intro, TDS/SPQ completion chase, repair coordination, sign-off scheduling, move-out/possession |
| Buyer's agent | contingency status, CR/NBP coordination, repair negotiation ferrying, appraisal news, loan status relay |
| Listing agent | disclosure delivery, repair responses, counter chain, walk-through access, MLS status changes |
| Escrow officer | open escrow, EMD receipt, instruction amendments, demands, settlement statements, recording confirmation |
| Title | prelim ordering/review, vesting confirmation, policy issuance |
| Lender/LO | application confirmed, appraisal ordered, conditions list, CD timing, doc drawing, funding confirmation |
| Inspectors | scheduling, access, report delivery, re-inspection after repairs |
| HOA/mgmt co | doc package order, transfer fees, clearance |
| Home warranty | order, invoice, confirmation |
| NHD company | report order/delivery |
| Broker/compliance | file completeness, commission demand, audit responses |

---

## Part 4 — What Terra does today (capability inventory)

Ingestion: email + single + **batch/folder upload**, content classification + free-text
labeling, exact-duplicate + version detection, HITL confirm, deal creation from batch.
Extraction: typed §5 paths (RPA, counters w/ supersession + identity protection, CR,
preapproval, prelim, inspections) + **universal read (facts) for everything else**.
SOR: fields w/ confidence + confirm/verify + provenance, effective-field supersession,
parties w/ roles/tiers, permanent invite links, deal notes, audit log w/ event catalog.
Compliance: verified CA ruleset (RPA 6/26), business-day/holiday rolls, deadlines,
rule-generated tasks, risk flags (counter chain, preapproval mismatch, prelim checks,
inspection checks, EMD/disclosure lateness, doc inconsistency), on-demand rebuild.
Comms: purpose-driven Claude drafts, Approve & Send only, reply detection, chase drafts,
reminders. Surfaces: TC home w/ decision queue + runway, deal page (chapter-zoom
timeline w/ lanes, document ledger w/ facts + story synthesis, comms, log), buyer/
seller workspaces, buyer-agent + listing-agent command centers, calendar .ics feed.

---

## Part 5 — Gap analysis (what's missing, ranked)

### Critical (core TC work Terra can't represent)
1. **Repair-negotiation loop** — no RR/repair-response/repair-addendum flow, no repair
   list tracking, no re-inspection or receipt verification. Phase-4 heart, absent.
2. **NBP/NSP machinery** — flags say "overdue" but Terra can't track a Notice to
   Perform: earliest-send date (D2), 2-day cure clock (D3), or resulting cancel right.
3. **Statutory rescission clocks** — TDS/NHD 3-day (5 mail) buyer rescission windows
   are computed nowhere (deliberately noted in ca-rules as separate; never built).
4. **Closing-week choreography** — no CD-received/3-day federal clock, no sign→fund→
   record state machine, no recording confirmation event, no key-release step.
5. **Disclosure packet tracking at form level** — "disclosure" is one type; a TC
   tracks TDS vs SPQ vs FLD vs AVID vs WHSD **individually**, each signed-by-both.
   (Universal read now names them — but the checklist can't require them item-wise.)

### Major (expected, absent or thin)
6. **Broker compliance file** — no completeness checklist per brokerage, no CDA,
   no closed-file packet export (parked as P5; still the #1 post-close deliverable).
7. **HOA lane** — ordering, delivery deadline, buyer review, transfer fees. Nothing.
8. **Home warranty / NHD / utilities ops tasks** — allocation fields exist; ordering
   workflows don't.
9. **Cancellation/fall-through flow** — CC form, deposit release, dispute states.
   Deals can be canceled but the unwind isn't modeled.
10. **Extension (ETA) flow** — date changes happen only via re-extraction; no
    first-class "extend COE" action with re-computation + all-party notice.
11. **Weekly status update cadence** — drafts exist per-party ad hoc; no scheduled
    all-party update ritual (the TC's most visible weekly output).
12. **Appraisal as an event** — ordered/completed/value vs. price; FHA amendatory
    interaction surfaced only via story synthesis, not tracked state.
13. **Rent-back / SIP possession variants** — possession is one field; SIP terms,
    deposits and insurance aren't modeled.

### Moderate (breadth/polish)
14. Listing-side pre-contract phase (RLA→MLS→offers) — Terra starts at the PA.
15. Multiple-offer management (offer comparison exists as sample for listing agents;
    no real offer-intake pipeline).
16. Wire-fraud advisory tracking (buyer workspace warns; no WFA form-tracking).
17. Sale-of-other-home contingency (COP) — not a tracked contingency type.
18. Per-value provenance (click field → highlighted clause in PDF; page anchors).
19. Signature completeness checking per document (who has/hasn't signed — extraction
    reads executed-vs-not but not per-party).
20. Commission math / CDA generation (money-adjacent: display-only, never movement).

---

## Part 6 — Implementation brainstorm (how, in Terra's architecture)

**Wave 1 — the missing loops (fits existing machinery):**
- *Form-level disclosure checklist*: extend DocType (or a subtype on `disclosure`
  via universal-read doc_kind) + EXPECTED ghost rows per form (TDS, SPQ, NHD, FLD,
  AVID, WHSD); signature status from extraction feeds "delivered vs. fully signed."
- *Repair loop*: new doc types `request_for_repairs`, `repair_response`; a
  `repairs` entity (item, who, resolved, receipt doc); risk flag when RR open past
  contingency; NEVER_BY_MACHINE already reserves repair.resolve for humans.
- *NBP tracker*: action on a blown deadline → creates NBP record w/ D2/D3 clocks in
  compliance; drafts the notice (Approve & Send); cure-expiry raises critical flag.
- *Rescission clocks*: compliance computes TDS/NHD +3/+5 no-roll windows from
  delivery-date fields; shown on timeline as a distinct statutory band.

**Wave 2 — closing week:** a `closing` state machine on the deal (docs-ordered →
CD-delivered (+3 bd federal clock) → signed → funded → recorded → keys) driven by
TC confirmations + escrow emails through ingestion; walk-through task auto-links.

**Wave 3 — ops lanes:** HOA/warranty/NHD/utility order-track-confirm mini-lanes as
rule-generated task chains with party-scoped chase drafts; weekly status ritual =
scheduled draft batch (cron exists) to all parties, still Approve & Send.

**Wave 4 — file & close-out:** broker compliance checklist per doc family +
closed-file packet export (P5) + cancellation unwind flow (CC, deposit states).

*Everything above stays inside the five hard rules: no money movement (commission/
CDA = display only), CA-only, ZDR, no auto-send, §5 whitelist untouched — new
deadline types enter compliance only via verified rules, like the existing ones.*
