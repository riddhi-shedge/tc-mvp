# C.A.R. Forms — IP Brief for Counsel

**What this is:** a factual/technical description of how the Transaction
Coordinator (TC) tool interacts with California Association of REALTORS® (C.A.R.)
standard forms, plus the specific questions we need a qualified attorney to
answer. **This document is NOT legal advice and takes no position on
infringement** — it exists so counsel can analyze the questions efficiently
without reverse-engineering the codebase.

Prepared 2026-07-19.

---

## 1. What the product is

An AI-assisted transaction coordinator for California residential real-estate
deals. A real-estate agent (a C.A.R. member) forwards a **signed Residential
Purchase Agreement (RPA)** and related documents to the tool. The tool:
- extracts key facts from the document (dates, prices, day-counts, party names);
- computes contract deadlines from those facts using California deadline rules;
- surfaces tasks/reminders and drafts routine follow-up emails for a human to
  approve and send.

It is an operational aid for the agent/coordinator, not a form-generation or
form-distribution product.

## 2. Exactly how the tool touches C.A.R. form content

| Step | What happens | Does it reproduce the form's *expressive text*? |
|---|---|---|
| **Ingestion** | The agent emails a **filled-in RPA PDF** (their own executed transaction copy). The file is stored in a **private, access-controlled bucket** (not public, not redistributed). | Stores the agent's own document; the tool does not publish or share it. |
| **Extraction** | Claude reads the PDF and returns a fixed **whitelist of factual field values** (e.g. buyer/seller names, property address, APN, purchase price, deposit amount, acceptance date, close-of-escrow, and the numeric contingency periods). Only these facts are persisted. | **No.** The stored output is factual field values, not the form's prose. |
| **Deadline computation** | The tool applies **California deadline rules** (e.g. "loan contingency = 17 days after Acceptance"; day-counting/holiday-roll mechanics) to the extracted facts. These rule *values* were read by a human from the current RPA to configure the engine. | **No** form text is stored; the encoded rules are numeric periods and counting logic (see §4). |
| **Drafting** | Claude generates **original** short emails (e.g. a lender status check). | **No.** Output is the tool's own text. |
| **Output to users** | Screens show extracted facts, computed dates, tasks, and draft emails. | **No** C.A.R. form prose is displayed or regenerated. |

Two internal rules are enforced in code today:
- **The tool never generates or fills a C.A.R. form** (e.g. it does not produce a
  Contingency Removal or Notice-to-Perform form) — deadline math only.
- Internal documentation **paraphrases** form language and does not copy form
  prose verbatim; a blank reference RPA used during development to read the
  deadline values was **not** committed to the repository.

## 3. What the product deliberately does NOT do

- Does not distribute blank or filled C.A.R. forms to third parties.
- Does not reproduce the form's expressive text in any user-facing output.
- Does not generate C.A.R. forms or fillable equivalents.
- Does not scrape or resell C.A.R.'s form library.

## 4. The nature of the "rules" we encoded

The deadline rules the engine uses are things like: contingency periods (a number
of days), whether counting is in calendar vs. business days, and how a deadline
that lands on a weekend/holiday rolls forward. These were read from the current
RPA and from California statutes (e.g. Civil Code §§ 11, 1102.3, 1103.3;
Government Code § 6700). **We treat these as uncopyrightable facts / functional
procedures**, but confirming that characterization is one of the questions below.

## 5. Questions for counsel

**Copyright**
1. Is having an AI **read a filled-in C.A.R. RPA to extract factual field values**
   (names, dates, prices, day-counts) an infringement, or non-infringing
   fact-extraction / fair use? Does the answer change because a machine, not a
   person, does the reading?
2. Are the **deadline rules / default day-counts** read from the form protectable
   expression, or uncopyrightable facts, systems, or procedures (cf. *Baker v.
   Selden*, merger doctrine)? Does encoding them in our own software raise any
   issue?
3. Does **storing the agent's own executed RPA** (their transaction copy) in our
   system implicate C.A.R.'s copyright, or is that the agent's/parties' document
   to route as they see fit?

**Licensing / terms of use**
4. C.A.R. forms are licensed to members (e.g. via zipForm®/Lone Wolf and C.A.R.
   end-user terms). Do those terms **restrict a member from sending their
   completed forms to a third-party service** like ours, or restrict us from
   processing them? Do we need our users to represent they have the right to
   submit them?
5. Do we need a **license, data agreement, or permission from C.A.R.** to build a
   tool that reads and interoperates with their forms at this scale?

**Trademark**
6. How may we **refer to** "C.A.R.", "California Residential Purchase Agreement,"
   or "RPA" when describing compatibility (nominative fair use), and what
   disclaimers (e.g. "not affiliated with or endorsed by C.A.R.") should we use?

## 6. Adjacent issues (related but DISTINCT from C.A.R. IP — flag for scoping)

These are separate work items; counsel may or may not cover them in the same
engagement, but they interact with launch:
- **Unlicensed practice of law (UPL):** the tool computes contract deadlines and
  prompts actions. Where is the line between an operational reminder tool and
  legal advice, and what disclaimers/human-in-the-loop controls keep us on the
  right side? (Every deadline is presented as informational; a human approves
  every outbound message.)
- **Privacy / NPI custody:** the documents contain personal and financial
  information. CCPA/CPRA obligations, data retention/disposal, breach-notice
  duties, and vendor data-processing terms (Anthropic ZDR, Supabase) are being
  handled as a separate track.

## 7. Materials we can provide counsel

- This brief and a walkthrough of the data flow.
- The fixed list of extracted fields (facts) and where each is stored.
- Confirmation of storage controls (private bucket, access rules) and retention.
- The encoded rule set and its provenance record
  (`docs/ca-rules-verification.md`), showing the values are facts read from the
  current form and CA statutes, human-verified.
- Sample screens showing that no C.A.R. form prose is reproduced in output.

*Note: bringing an actual C.A.R. form to the attorney is fine for their review;
this brief and the repository intentionally do not reproduce form text.*
