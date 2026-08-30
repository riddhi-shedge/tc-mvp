// Buyer's-agent command center contracts (§7). List views consume summaries;
// per-deal detail loads on drill-in. RiskLevel is the shared canonical primitive
// (contract §2.7); DealStage is this surface's alias over the canonical DealPhase (§3).
import { RiskLevel } from "../shared/canonical";
export type { RiskLevel } from "../shared/canonical";

export type DealStage = "offer_accepted" | "escrow_open" | "contingencies" | "loan_appraisal" | "closing" | "closed";

export interface DealSummary {
  id: string;
  clientName: string;
  propertyAddress: string;
  stage: DealStage;
  nextDeadline: { label: string; date: string; risk: RiskLevel } | null;
  closeDate: string | null;
  risk: RiskLevel;
  peek: { emd: string; loan: string; appraisalOrNext: string };
}

export interface PipelineStats { activeDeals: number; needYouToday: number; atRisk: number; closingThisWeek: number }

export type RecipientRel = "client" | "buyer" | "listing_agent" | "escrow" | "lender" | "title" | "inspector_general" | "other" | string;
export interface ApprovalItem {
  id: string;
  dealId: string;
  clientName: string;
  title: string;
  recipient: { name: string; relationship: RecipientRel; channel: "email" | "sms" };
  draftBody: string;
  reasoning: string;
  urgency: "urgent" | "normal" | "low";
  riskClass: "low" | "standard";
  state: "pending" | "sent" | "dismissed";
  createdAt: string | null;
}

export interface AIActivityEvent { id: string; dealId: string | null; text: string; mode: "autonomous" | "needs_you"; occurredAt: string | null }
export interface CoPilotWeekly { handled: number; escalated: number }
export interface DeadlineItem { id: string; dealId: string; label: string; date: string; risk: RiskLevel; clientName: string; propertyAddress: string }

export interface Portfolio {
  me: { name: string | null; role: string };
  stats: PipelineStats;
  deals: DealSummary[];
  radar: DeadlineItem[];
  activity: AIActivityEvent[];
  weekly: CoPilotWeekly;
  approvalItems?: ApprovalItem[]; // shipped with the portfolio — one book-load per poll
}

export interface Party { id: string; name: string | null; role: string; phone: string | null }
export interface DealDetail {
  summary: DealSummary;
  fields: Record<string, string>;
  deadlines: { id: string; name: string; due_date: string | null }[];
  parties: Party[];
  tasks: { id: string; title: string; status: string; due_date: string | null }[];
  documents: { id: string; doc_type: string | null; status: string }[];
  messages: { id: string; subject: string; status: string; reasoning: string | null }[];
}

export interface ClientRow { dealId: string; clientName: string; propertyAddress: string; parties: Party[] }

export const STAGE_LABEL: Record<DealStage, string> = {
  offer_accepted: "Offer accepted", escrow_open: "Escrow open", contingencies: "Contingencies",
  loan_appraisal: "Loan & appraisal", closing: "Closing", closed: "Closed",
};
