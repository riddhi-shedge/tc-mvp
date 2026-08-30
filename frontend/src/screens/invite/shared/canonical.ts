// Cross-surface canonical data & event contract — the single source of truth all
// four workspaces (buyer, seller, buyer's agent, listing agent) project from.
//
// There is ONE transaction. Each surface renders a role-specific *view* of it; the
// same fact is never stored differently. Surface view-models (DealSummary,
// SaleSummary, ListingSummary, …) are thin aliases over these entities — see the
// §3 reconciliation map at the bottom. This file is the frontend mirror of the
// backend's event_catalog.py + authority.py; keep them in lockstep.

// ─── §2.1 Deal & Property ───────────────────────────────────────────────────
export type DealPhase =
  | "pre_market"      // listing side only, before a buyer exists
  | "offer"           // offers in / accepted, pre-escrow
  | "escrow_open"
  | "contingencies"   // buyer's contingency period
  | "closing"
  | "closed";

export interface Deal {
  id: string;
  propertyId: string;
  phase: DealPhase;
  california: true;                  // scope invariant (§6.4)
  listPriceCents: number | null;
  contractPriceCents: number | null;
  openedEscrowAt: string | null;
  estimatedCloseDate: string | null;
  closedAt: string | null;
  daysOnMarket: number | null;
}
export interface Property { id: string; addressLine: string; photos: { url: string; kind: "listing" | "inspection" | "user" }[] }

// ─── §2.2 Parties ───────────────────────────────────────────────────────────
export type PartyRole =
  | "buyer" | "seller" | "buyer_agent" | "listing_agent"
  | "escrow" | "title" | "lender" | "inspector" | "other";
export interface Party {
  id: string; dealId: string; role: PartyRole; name: string;
  phone: string | null;              // verified; source for out-of-band wire checks (§6.1)
  email: string | null; isPrincipal: boolean;
}

// ─── §2.3 Contingencies ─────────────────────────────────────────────────────
export type ContingencyKind = "inspection" | "loan" | "appraisal" | "other";
export type ContingencyState = "active" | "in_progress" | "ordered" | "removed";
export interface Contingency {
  id: string; dealId: string; kind: ContingencyKind; state: ContingencyState;
  removalDate: string | null; explanation: string; stakes: string;
}

// ─── §2.4 Disclosures ───────────────────────────────────────────────────────
export type DisclosureKind = "tds" | "spq" | "nhd" | "lead_paint" | "mello_roos" | "other";
export type DisclosureState = "draft" | "completed" | "delivered" | "acknowledged";
export interface Disclosure {
  id: string; dealId: string; kind: DisclosureKind; title: string;
  state: DisclosureState; deliveryDeadline: string | null; fileUrl: string | null;
}

// ─── §2.5 Offers ────────────────────────────────────────────────────────────
export type Financing = "cash" | "conventional" | "fha" | "va" | "other";
export type OfferState = "received" | "presented" | "accepted" | "countered" | "declined";
export interface Offer {
  id: string; dealId: string; buyerPartyId: string | null; buyerAgentPartyId: string;
  priceCents: number; financing: Financing; downPaymentPct: number | null;
  contingenciesSummary: string; closeDays: number;
  strength: "strong" | "moderate" | "weak";
  tradeoffTag: string | null;        // neutral descriptor only — never a recommendation
  netToSellerEstimateCents: number | null; state: OfferState;
}
// INVARIANT: state='accepted' is set ONLY by a recorded seller authorization (§5). Never AI/system.

// ─── §2.6 Money ─────────────────────────────────────────────────────────────
export type MoneyKind = "emd" | "repair_credit" | "net_sheet_line" | "disbursement" | "closing_cost";
export interface MoneyItem {
  id: string; dealId: string; kind: MoneyKind; label: string; amountCents: number;
  direction: "buyer_pays" | "seller_pays" | "credit_to_buyer" | "to_seller";
  dueDate: string | null; state: "pending" | "scheduled" | "received" | "agreed" | "disbursed";
  payeeLabel: string | null;         // a NAME, never an account number (§6.1)
  verifiedOutOfBand: boolean;
}
export interface RepairRequest {
  id: string; dealId: string; summary: string; requestedCents: number;
  proposedResolutionCents: number | null; state: "pending" | "accepted" | "countered" | "declined";
}
// INVARIANT: resolution reflects a recorded seller authorization (§5). Never AI/system.

// ─── §2.7 Documents, tasks, deadlines ───────────────────────────────────────
export type DocState = "unviewed" | "viewed" | "acknowledged" | "signed";
export interface DealDocument {
  id: string; dealId: string; name: string; category: "review" | "signature";
  audience: PartyRole; plainSummary: string | null; state: DocState; fileUrl: string | null;
}
export interface Task {
  id: string; dealId: string; ownerRole: PartyRole; label: string;
  dueDate: string | null; urgency: "now" | "soon" | "later"; done: boolean;
}
export type RiskLevel = "ok" | "watch" | "at_risk";
export interface Deadline { id: string; dealId: string; label: string; date: string; ownerRole: PartyRole; risk: RiskLevel }

// ─── §2.8 Activity, AI drafts, messages ─────────────────────────────────────
export type TransactionEventType =
  | "listing_activated" | "showing_logged" | "offer_received" | "offers_presented" | "offer_accepted"
  | "escrow_opened" | "emd_due" | "emd_received"
  | "disclosures_completed" | "disclosures_delivered" | "disclosures_acknowledged"
  | "inspection_scheduled" | "inspection_report_ready" | "repair_requested" | "repair_resolved"
  | "appraisal_ordered" | "appraisal_result" | "loan_status_changed" | "contingency_removed" | "all_contingencies_removed"
  | "walkthrough_scheduled" | "clear_to_close" | "funded" | "recorded" | "proceeds_disbursed" | "possession_transferred"
  | "deadline_approaching" | "deadline_missed" | "deal_cancelled";

export type ActorRole = PartyRole | "system" | "ai";
export interface ActivityEvent {
  id: string; dealId: string | null; type: TransactionEventType | null;
  text: string;                      // role-relative, rendered by the backend catalog (§4)
  occurredAt: string | null; actorRole?: ActorRole;
}

export type ApprovalState = "pending" | "sent" | "dismissed";
export interface ApprovalItem {
  id: string; dealId: string; drafterRole: "ai"; approverRole: "buyer_agent" | "listing_agent";
  recipientPartyId: string; channel: "email" | "sms";
  draftBody: string;                 // full content shown before send — never hidden (§6.3)
  reasoning: string; reflectsPrincipalDecisionId: string | null;
  riskClass: "low" | "standard"; state: ApprovalState;
}
// INVARIANT: an ApprovalItem conveying a principal's decision MUST carry reflectsPrincipalDecisionId (§5, §6.3).

// ─── §5 Write-authority matrix (mirror of backend authority.py) ─────────────
export const AUTHORITY: Record<string, readonly PartyRole[] | readonly ("system")[]> = {
  "offer.author": ["buyer_agent"],
  "offer.accept": ["seller"],                    // never ai/system
  "disclosure.complete": ["seller"],
  "disclosure.deliver": ["listing_agent"],
  "disclosure.acknowledge": ["buyer", "buyer_agent"],
  "contingency.remove": ["buyer", "buyer_agent"],
  "repair.resolve": ["seller"],                  // never ai/system
  "money.verify_out_of_band": ["buyer", "seller"],
  "approval.approve_send": ["buyer_agent", "listing_agent"],
  "deadline.write": ["system"],
  "health.write": ["system"],
};
export const NEVER_BY_MACHINE = ["offer.accept", "repair.resolve"] as const;

// ─── §3 Naming reconciliation — surface view-models are aliases over the above ─
// | Canonical      | Buyer          | Seller       | Buyer's agent    | Listing agent |
// | Deal (+view)   | DealSummary    | SaleSummary  | DealSummary      | ListingSummary |
// | DealPhase      | DealPhase      | DealPhase    | DealStage        | ListingStatus  |
// | Contingency    | Contingency    | BuyerMilestone(read) | detail    | buyer-side health(read) |
// | Disclosure     | DealDocument   | Disclosure   | detail           | detail         |
// | MoneyItem(emd) | DepositStep    | —            | pipeline peek    | detail         |
// | MoneyItem(net) | —              | NetSheet     | —                | netToSeller    |
// | RepairRequest  | inspections    | BuyerRequest | —                | queue draft    |
// | ApprovalItem   | —              | —            | ApprovalItem     | ApprovalItem   |
// | ActivityEvent  | activity       | activity     | AIActivityEvent  | co-pilot feed  |
