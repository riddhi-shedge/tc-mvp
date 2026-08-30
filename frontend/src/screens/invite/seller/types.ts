// Seller workspace data contracts (§7). The adapter maps /party/workspace onto these.

export type SellerPhase = "offer" | "escrow_open" | "disclosures" | "buyer_contingencies" | "closing" | "closed";

export interface SaleSummary {
  propertyAddress: string;
  heroPhotoUrl: string | null;
  photoCount: number;
  phase: SellerPhase;
  closeDate: string | null;
  daysToClose: number | null;
  estimatedNetProceedsCents: number | null;
  beforeMortgagePayoff: boolean;
  status: { level: "on_track" | "action_soon" | "at_risk"; nextActionLabel: string };
}

export type BuyerMilestoneState = "complete" | "in_progress" | "pending" | "at_risk";
export interface BuyerMilestone {
  id: string;
  label: string;
  detail: string | null;
  state: BuyerMilestoneState;
}
export interface DealHealth {
  meter: "on_track" | "watch" | "at_risk";
  milestones: BuyerMilestone[];
}

export type DisclosureKind = "tds" | "spq" | "nhd" | "lead_paint" | "mello_roos" | "other";
export type DisclosureState = "draft" | "completed" | "delivered" | "acknowledged";
export interface Disclosure {
  id: string;
  kind: DisclosureKind;
  title: string;
  state: DisclosureState;
  dueDate: string | null;
  explanation: string; // plain-language what & why (static CA library)
  stakes: string; // plain-language consequence
}

export interface NetSheetLine { label: string; amountCents: number; kind: "credit" | "debit" }
export interface NetSheet {
  lines: NetSheetLine[];
  estimatedNetProceedsCents: number;
  disbursementVerified: boolean;
  beforeMortgagePayoff: boolean;
}

export type RequestKind = "repair" | "credit";
export interface BuyerRequest {
  id: string;
  kind: RequestKind;
  summary: string;
  amountCents: number | null;
  proceedsAfterAcceptCents: number;
  state: "pending" | "accepted" | "countered" | "declined";
}

export interface SellerTask { id: string; label: string; dueDate: string | null; done: boolean; urgency: "now" | "soon" | "later" }
export interface TeamMember { id?: string | null; name: string | null; role: string; phone?: string | null }
export interface ActivityEvent { id: string; text: string; occurredAt: string | null }

export interface SaleDeal {
  summary: SaleSummary;
  dealHealth: DealHealth | null;
  disclosures: Disclosure[];
  netSheet: NetSheet | null;
  requests: BuyerRequest[];
  tasks: SellerTask[];
  team: TeamMember[];
  activity: ActivityEvent[];
}
