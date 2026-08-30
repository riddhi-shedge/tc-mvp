// The buyer workspace's data contracts (§7 of the brief). The workspace consumes
// these shapes; useBuyerDeal maps the /party/workspace payload onto them.

export type DealPhase = "offer" | "escrow_open" | "contingencies" | "closing" | "keys";

export interface DealSummary {
  propertyAddress: string;
  heroPhotoUrl: string | null;
  photoCount: number;
  phase: DealPhase;
  estimatedKeysDate: string | null; // ISO
  daysToKeys: number | null;
  status: {
    level: "on_track" | "action_soon" | "at_risk";
    nextActionLabel: string;
  };
}

export type ContingencyKind = "inspection" | "loan" | "appraisal" | "other";
export interface Contingency {
  id: string;
  kind: ContingencyKind;
  title: string;
  status: "active" | "in_progress" | "ordered" | "removed";
  removalDate: string | null;
  daysLeft: number | null;
  explanation: string; // plain-language: what it protects
  stakes: string; // plain-language: consequence of removal
}

export interface DepositStep {
  amountLabel: string; // e.g. "$25,500" — never account numbers
  payeeLabel: string | null; // escrow company name
  dueDate: string | null;
  verifiedByBuyer: boolean;
  escrowPhone: string | null; // verified, out-of-band — from the roster
}

export interface BuyerTask {
  id: string;
  label: string;
  dueDate: string | null;
  done: boolean;
  urgency: "now" | "soon" | "later";
}

export interface TeamMember {
  id?: string | null;
  name: string | null;
  role: string;
  phone?: string | null;
}

export interface ActivityEvent {
  id: string;
  text: string;
  occurredAt: string | null;
}

export interface BuyerDeal {
  summary: DealSummary;
  contingencies: Contingency[];
  deposit: DepositStep | null;
  tasks: BuyerTask[];
  team: TeamMember[];
  activity: ActivityEvent[];
}

// The raw /party/workspace payload the adapter consumes.
export interface BuyerWorkspacePayload {
  me: { name: string | null; role: string };
  archetype: string;
  property: {
    address: string | null; city: string | null; zip: string | null;
    photo_url?: string | null; details?: Record<string, string | number | null> | null;
    deep_links?: Record<string, string> | null;
  } | null;
  fields: Record<string, string>;
  stage: string | null;
  roster: { id?: string | null; name: string | null; role: string; phone?: string | null }[];
  deadlines: { name: string; due_date: string }[];
  my_tasks: { id: string; title: string; status: string; due_date: string | null; priority: string }[];
  my_documents: { id: string; doc_type: string | null; status: string; created_at?: string }[];
  activity?: ActivityEvent[];
  deposit?: {
    amount: string; payee: string | null; dueDate: string | null;
    verifiedByBuyer: boolean; escrowContactId: string | null;
  } | null;
}
