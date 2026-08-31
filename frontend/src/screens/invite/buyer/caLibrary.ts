// Curated, plain-language explanations of standard California real-estate terms and
// contingencies. Hand-written, consistent, and non-advisory — orientation, not legal
// advice. No model calls, so nothing here touches PII or the ZDR gate.

import { ContingencyKind } from "./types";

type Term = { key: string; aliases: string[]; definition: string };

export const TERMS: Term[] = [
  { key: "escrow", aliases: ["escrow", "close of escrow", "coe"], definition:
    "A neutral third party that holds the money and documents, releasing them only once both sides have met the deal's terms. Close of escrow is the day the home becomes yours." },
  { key: "contingency", aliases: ["contingency", "contingencies", "contingency period"], definition:
    "A condition that must be met — or actively removed — for the sale to move forward. In California, contingencies are your protection and don't lapse on their own." },
  { key: "contingency removal", aliases: ["contingency removal", "remove contingency", "removal"], definition:
    "Signing off that a protection (like inspection or loan) is satisfied. In California this is an active step you take with your team — it doesn't happen automatically." },
  { key: "appraisal", aliases: ["appraisal", "appraise", "appraised"], definition:
    "A licensed appraiser's estimate of the home's value, ordered by your lender to make sure the loan matches what the home is worth." },
  { key: "underwriting", aliases: ["underwriting", "underwriter"], definition:
    "Your lender's final review of your finances and the home before they commit to funding your loan." },
  { key: "earnest money", aliases: ["earnest money", "emd", "earnest-money deposit", "deposit"], definition:
    "Your good-faith deposit, held in escrow, that shows the seller you're serious. It's credited toward your purchase at closing." },
  { key: "tds", aliases: ["tds", "transfer disclosure statement"], definition:
    "Transfer Disclosure Statement — the seller's required statement about the home's known condition and defects." },
  { key: "spq", aliases: ["spq", "seller property questionnaire"], definition:
    "Seller Property Questionnaire — a more detailed set of the seller's answers about the home, beyond the TDS." },
  { key: "nhd", aliases: ["nhd", "natural hazard disclosure"], definition:
    "Natural Hazard Disclosure — a report on whether the home sits in a flood, fire, earthquake, or other hazard zone." },
  { key: "preapproval", aliases: ["preapproval", "pre-approval", "pre approval"], definition:
    "Your lender's written estimate of how much they're willing to lend you, based on a review of your finances." },
  { key: "proof of funds", aliases: ["proof of funds", "pof"], definition:
    "Documentation showing you have the cash available for your down payment and closing costs." },
  { key: "home warranty", aliases: ["home warranty", "warranty"], definition:
    "A one-year service plan that covers repairs to major systems and appliances after you move in — on this deal the seller is paying for yours." },
  { key: "walkthrough", aliases: ["final walkthrough", "walkthrough", "walk-through"], definition:
    "Your last look at the home right before closing, to confirm it's in the agreed condition and any promised repairs are done." },
  { key: "proration", aliases: ["proration", "prorated", "prorate"], definition:
    "Splitting ongoing costs like property tax fairly between buyer and seller based on the closing date — you pay for the days you owned the home." },
  { key: "payoff", aliases: ["payoff", "mortgage payoff", "loan payoff"], definition:
    "The remaining balance on your existing mortgage, which is paid off from the sale proceeds at closing." },
  { key: "net proceeds", aliases: ["net proceeds", "proceeds", "net sheet"], definition:
    "What you actually walk away with: the sale price minus your loan payoff, commissions, closing costs, and any credits." },
  { key: "commission", aliases: ["commission", "agent commission"], definition:
    "The fee paid to the agents from the sale, typically a percentage of the sale price, deducted from your proceeds at closing." },
  { key: "concession", aliases: ["concession", "credit", "seller credit"], definition:
    "Money you agree to give the buyer — often toward repairs or closing costs — which reduces your net proceeds." },
  { key: "disbursement", aliases: ["disbursement", "disbursement account"], definition:
    "The account escrow sends your proceeds to at closing. Always confirm the details by phone — escrow never changes them by email." },
  { key: "mello-roos", aliases: ["mello-roos", "mello roos", "special assessment"], definition:
    "Extra local taxes on some California homes that fund infrastructure like roads and schools — they must be disclosed to the buyer." },
];

/** Find a plain-language definition for a term (case/spacing-insensitive). */
export function defineTerm(text: string): string | null {
  const t = text.trim().toLowerCase();
  const hit = TERMS.find((term) => term.aliases.some((a) => a === t))
    ?? TERMS.find((term) => term.aliases.some((a) => t.includes(a) || a.includes(t)));
  return hit?.definition ?? null;
}

/** What each contingency protects, and the stakes of removing it. Non-advisory. */
export const CONTINGENCY_COPY: Record<ContingencyKind, { explanation: string; stakes: string }> = {
  inspection: {
    explanation: "Your window to inspect the home and, if something serious turns up, renegotiate or walk away without losing your deposit.",
    stakes: "Once it's removed, you're accepting the home's condition as-is — you generally can't recover your deposit over issues found later.",
  },
  loan: {
    explanation: "Protects you while your lender finalizes your mortgage. If financing falls through before it's removed, you can typically cancel and keep your deposit.",
    stakes: "After removal, if your loan later falls apart, your deposit may be at risk.",
  },
  appraisal: {
    explanation: "Protects you if the home appraises for less than the price — you can renegotiate or walk without losing your deposit.",
    stakes: "Once removed, covering any gap between a low appraisal and the price becomes your responsibility.",
  },
  other: {
    explanation: "A condition that must be satisfied or actively removed before the sale can close.",
    stakes: "Removing a contingency gives up the protection it provided — make sure you're comfortable with your team first.",
  },
};

// Standard CA disclosures → a one-line "what it is / what to look for" summary.
export const DISCLOSURE_SUMMARY: Record<string, string> = {
  disclosure: "The seller's required statements about the home's condition — read for anything about repairs, water, or past problems.",
  preliminary_report: "The title company's report on who owns the home and any liens or easements attached to it.",
};

/** Seller-side: what each CA disclosure is/why it's required, and the stakes of
 *  getting it wrong. Keyed by disclosure kind; non-advisory ("when in doubt, disclose"). */
export const DISCLOSURE_COPY: Record<string, { explanation: string; stakes: string }> = {
  tds: {
    explanation: "California requires you to disclose the home's known condition and any defects in a Transfer Disclosure Statement — the core record of what you told the buyer about the property.",
    stakes: "Leaving out a known problem can create liability that survives the sale. When in doubt, disclose.",
  },
  spq: {
    explanation: "The Seller Property Questionnaire goes deeper than the TDS, asking about repairs, disputes, alterations, and history you're aware of.",
    stakes: "Incomplete or inaccurate answers are a common source of after-sale claims — err toward telling the buyer more.",
  },
  nhd: {
    explanation: "The Natural Hazard Disclosure reports whether the home sits in a flood, fire, earthquake, or other designated hazard zone. It's usually prepared by a third-party service.",
    stakes: "Failing to deliver it can delay closing and expose you to liability if a hazard later affects the buyer.",
  },
  lead_paint: {
    explanation: "Homes built before 1978 require a federal lead-based paint disclosure and information pamphlet, since older paint may contain lead.",
    stakes: "This is a federal requirement — skipping it carries penalties independent of California law.",
  },
  mello_roos: {
    explanation: "If the home is in a Mello-Roos or special-assessment district, you must disclose the extra taxes that fund local infrastructure.",
    stakes: "Undisclosed special assessments surprise buyers with higher tax bills and can unwind a sale.",
  },
  other: {
    explanation: "An additional disclosure that applies to this property.",
    stakes: "Disclose fully and accurately — when in doubt, tell the buyer.",
  },
};
