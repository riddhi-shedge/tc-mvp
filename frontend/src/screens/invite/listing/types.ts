// Listing-agent contracts (§7). Reuses the buyer's-agent shared contracts for the
// queue / feed / radar / detail; adds the listing frame and the offer workflow.
import { AIActivityEvent, CoPilotWeekly, DeadlineItem, Party, RiskLevel } from "../agent/types";

export type { AIActivityEvent, CoPilotWeekly, DeadlineItem, Party, RiskLevel } from "../agent/types";

export type ListingStatus = "pre_market" | "active" | "in_escrow" | "closed";

export interface ListingSummary {
  id: string;
  sellerName: string;
  propertyAddress: string;
  status: ListingStatus;
  listPriceCents: number | null;
  daysOnMarket: number | null;
  offerCount: number;
  nextDeadline: { label: string; date: string; risk: RiskLevel } | null;
  closeDate: string | null;
  risk: RiskLevel;
  peek: { line1: string; line2: string; line3: string };
}

export interface ListingStats { liveListings: number; offersToReview: number; inEscrow: number; needYouToday: number }

export type Financing = "cash" | "conventional" | "fha" | "va" | "other";
export interface Offer {
  id: string;
  buyerAgentName: string;
  priceCents: number;
  financing: Financing;
  downPaymentPct: number | null;
  contingencies: string;
  closeDays: number;
  strength: "strong" | "moderate" | "weak";
  tradeoffTag: string | null;
  netToSellerEstimateCents: number | null;
  state: "received" | "presented" | "accepted" | "countered" | "declined";
  sample: boolean;
}

export interface BuyerSideHealth {
  meter: "on_track" | "watch" | "at_risk";
  milestones: { id: string; label: string; detail: string | null; state: "complete" | "in_progress" | "pending" | "at_risk"; actionableByAgent: false }[];
}

export interface OfferComparison { offers: Offer[]; buyerHealth: BuyerSideHealth; sellerName: string; propertyAddress: string }

export interface ListingPortfolio {
  me: { name: string | null; role: string };
  stats: ListingStats;
  listings: ListingSummary[];
  radar: DeadlineItem[];
  activity: AIActivityEvent[];
  weekly: CoPilotWeekly;
}

// Seller card = roster + the pre-call cram (status/DOM, offers, disclosure
// delivery, sample marketing pulse, talking points).
export interface SellerRow {
  listingId: string;
  sellerName: string;
  propertyAddress: string;
  parties: Party[];
  status: ListingStatus;
  daysOnMarket: number | null;
  offerCount: number;
  priceCents: number | null;
  nextDeadline: { label: string; date: string; risk: RiskLevel } | null;
  disclosures: { kind: string; title: string; delivered: boolean }[];
  pulse: { showings: number; views: number; saves: number } | null;
  talkingPoints: AIActivityEvent[];
}

export const LISTING_STATUS_LABEL: Record<ListingStatus, string> = {
  pre_market: "Pre-market", active: "Active", in_escrow: "In escrow", closed: "Closed",
};
