import { supabase } from "./supabase";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(
      typeof detail === "string"
        ? detail
        : ((detail as { message?: string })?.message ?? "Request failed"),
    );
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body.detail ?? res.statusText);
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// ---- API types (mirror the backend responses we use) -----------------------

export interface InboxItem {
  id: string;
  from_email: string;
  subject: string | null;
  attachment_name: string | null;
  attachment_count: number;
  detected_doc_type: string | null;
  status: "pending" | "needs_manual";
  needs_manual_reason: string | null;
  source: "email" | "manual";
  suggestion: { transaction_id: string; reason: string } | null;
  created_at: string;
}

export interface DealDocument {
  id: string;
  external_ref: string | null;
  doc_type: string | null;
  storage_path: string | null;
  status: string;
  created_at?: string;
}

export interface TransactionSummary {
  id: string;
  status: string;
  property_address: string | null;
  created_at: string;
}

// Enriched per-deal rollup for the pipeline board.
export interface DealSummary {
  id: string;
  status: string;
  stage: string;
  property_address: string | null;
  coe_date: string | null;
  purchase_price: string | null;
  all_cash: boolean;
  total_tasks: number;
  done_tasks: number;
  open_tasks: number;
  risk_count: number;
}

export interface CalendarDeadline {
  transaction_id: string;
  property_address: string | null;
  name: string;
  due_date: string;
  key: string | null;
}

export interface OpenTask {
  id: string;
  transaction_id: string;
  property_address: string | null;
  title: string;
  status: string;
  due_date: string | null;
  assigned_party_id: string | null;
}

// Pipeline stages, left-to-right (mirror of repo.DEAL_STAGES).
export const DEAL_STAGES: { id: string; name: string }[] = [
  { id: "new", name: "New offer" },
  { id: "cont", name: "Contingency period" },
  { id: "closing", name: "Closing" },
  { id: "closed", name: "Closed" },
];

export interface ExtractedField {
  id: string;
  name: string;
  value: string;
  confidence: number;
  confirmed: boolean;
  deadline_driving: boolean;
}

export interface ExtractionErrorDetail {
  message: string;
  reasons: string[];
  manual_fields_required: boolean;
}

export function asExtractionError(err: unknown): ExtractionErrorDetail | null {
  if (err instanceof ApiError && err.status === 422 && typeof err.detail === "object") {
    const d = err.detail as Partial<ExtractionErrorDetail>;
    if (Array.isArray(d.reasons)) return d as ExtractionErrorDetail;
  }
  return null;
}

// Mirror of the verified §5 v2 list (backend app/contracts/fields.py is the
// source of truth; the backend validates names regardless).
export const S5_FIELD_NAMES = [
  "buyer_names",
  "seller_names",
  "property_address",
  "apn",
  "purchase_price",
  "initial_deposit_amount",
  "increased_deposit_amount",
  "loan_amount",
  "financing_type",
  "down_payment",
  "all_cash",
  "acceptance_date",
  "close_of_escrow",
  "possession_date",
  "emd_due_days",
  "inspection_contingency_days",
  "loan_contingency_days",
  "appraisal_contingency_days",
  "insurance_contingency_days",
  "disclosure_delivery_days",
  "verification_of_funds_days",
  "loan_contingency_present",
  "appraisal_contingency_present",
  "inspection_contingency_present",
  "insurance_contingency_present",
  "buyer_agent",
  "listing_agent",
  "escrow_holder",
  "title_company",
  "lender_contact",
] as const;

// §5 field → display group (mirror of app/contracts/fields.py FieldSpec.group).
export const S5_FIELD_GROUP: Record<string, string> = {
  buyer_names: "parties", seller_names: "parties",
  property_address: "property", apn: "property",
  items_included: "property", items_excluded: "property",
  home_warranty_paid_by: "allocation", home_warranty_issued_by: "allocation",
  other_terms: "terms",
  purchase_price: "financial", initial_deposit_amount: "financial",
  increased_deposit_amount: "financial", loan_amount: "financial",
  financing_type: "financial", down_payment: "financial", all_cash: "financial",
  acceptance_date: "dates", close_of_escrow: "dates", possession_date: "dates",
  emd_due_days: "contingency", inspection_contingency_days: "contingency",
  loan_contingency_days: "contingency", appraisal_contingency_days: "contingency",
  insurance_contingency_days: "contingency", disclosure_delivery_days: "contingency",
  verification_of_funds_days: "contingency",
  loan_contingency_present: "flags", appraisal_contingency_present: "flags",
  inspection_contingency_present: "flags", insurance_contingency_present: "flags",
  buyer_agent: "contacts", listing_agent: "contacts", escrow_holder: "contacts",
  title_company: "contacts", lender_contact: "contacts",
};

// Ordered, labelled groups for the extraction-review sections.
export const S5_GROUPS: { key: string; label: string; icon: string }[] = [
  { key: "property", label: "Property", icon: "🏠" },
  { key: "parties", label: "Parties", icon: "👥" },
  { key: "financial", label: "Financial", icon: "💵" },
  { key: "dates", label: "Dates", icon: "📅" },
  { key: "contingency", label: "Contingencies", icon: "⏳" },
  { key: "flags", label: "Contingency flags", icon: "🚩" },
  { key: "allocation", label: "Costs & allocation", icon: "🧾" },
  { key: "terms", label: "Other terms", icon: "📝" },
  { key: "contacts", label: "Contacts", icon: "📇" },
  { key: "other", label: "Other", icon: "•" },
];

// A deadline-driving field → keyword found in its computed Deadline's name, so
// the extraction card can show the resolved calendar date (from the CA engine —
// never recomputed in the browser) next to the raw day-count.
export const FIELD_DEADLINE_KEYWORD: Record<string, string> = {
  acceptance_date: "acceptance",
  close_of_escrow: "escrow",
  emd_due_days: "earnest",
  inspection_contingency_days: "inspection",
  loan_contingency_days: "loan",
  appraisal_contingency_days: "appraisal",
  insurance_contingency_days: "insurance",
  disclosure_delivery_days: "disclosure",
};

export interface Deadline {
  id: string;
  name: string;
  due_date: string;
}

export interface Task {
  id: string;
  title: string;
  status: string;
  deadline_id: string | null;
  assigned_party_id: string | null;
  // TC-authored metadata (persisted in the task's audit details).
  description?: string | null;
  due_date?: string | null;
  priority?: string; // low | normal | high | urgent
}

export interface Message {
  id: string;
  subject: string | null;
  body: string | null;
  status: "draft" | "approved" | "sent";
  sent_at: string | null;
  party_id: string | null;
}

// A follow-up nudge scheduled when a message is sent — surfaces to the TC when
// remind_at passes with no logged reply. Never sends anything itself.
export interface Reminder {
  id: string;
  message_id: string | null;
  remind_at: string;
  note: string | null;
}

export interface DealParty {
  id: string;
  name: string | null;
  role: string;
  email: string | null;
  phone?: string | null;
  company?: string | null;
  permission_tier?: string;
}

// The full expected cast of a CA residential deal, grouped for display. The
// backend (app/master/parties.ROLE_TIERS) owns permission tiers; this drives the
// roster UI — which roles to show and label, and where a slot is still empty.
export const PARTY_ROSTER: { group: string; roles: { role: string; label: string }[] }[] = [
  { group: "Principals", roles: [
    { role: "buyer", label: "Buyer" },
    { role: "seller", label: "Seller" },
  ] },
  { group: "Agents", roles: [
    { role: "buyer_agent", label: "Buyer's agent" },
    { role: "listing_agent", label: "Listing agent" },
  ] },
  { group: "Escrow · Title · Lender", roles: [
    { role: "escrow", label: "Escrow" },
    { role: "title", label: "Title" },
    { role: "lender", label: "Lender / loan officer" },
  ] },
  { group: "Inspection & vendors", roles: [
    { role: "inspector_general", label: "General inspector" },
    { role: "inspector_termite", label: "Termite inspector" },
    { role: "inspector_roof", label: "Roof inspector" },
    { role: "inspector_sewer", label: "Sewer inspector" },
    { role: "appraiser", label: "Appraiser" },
    { role: "home_warranty", label: "Home warranty" },
    { role: "insurance", label: "Insurance" },
  ] },
];

export const PARTY_ROLE_LABEL: Record<string, string> = Object.fromEntries(
  PARTY_ROSTER.flatMap((g) => g.roles.map((r) => [r.role, r.label])),
);

export interface AuditRow {
  actor: string;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface DealRiskFlag {
  id: string;
  severity: string;
  description: string;
  case_key: string | null;
  resolved: boolean;
}

// ---- Dashboard (Prompt 7): a read-only aggregation over the SOR ------------

export interface DashboardPartyView {
  party: DealParty;
  open_tasks: Task[];
  done_tasks: Task[];
  last_message_status: string | null;
}

export interface Dashboard {
  transaction_id: string;
  parties: DashboardPartyView[];
  party_progress: {
    buyers_total: number;
    proof_of_funds_confirmed: number;
    disclosures_confirmed: number;
  };
  risk_alerts: DealRiskFlag[];
  communication: { sent: Message[]; pending: Message[]; replies: unknown[] };
}

export interface PartyAccessToken {
  party_id: string;
  access_token: string;
}

// The §8 tier that gets a scoped access link (matches the backend default).
export const RECEIVING_END_ROLES = new Set([
  "inspector_general",
  "inspector_pest",
  "appraiser",
  "contractor",
]);

export function isReceivingEnd(p: DealParty): boolean {
  return p.permission_tier === "receiving_end" || RECEIVING_END_ROLES.has(p.role);
}

const COLLABORATOR_ROLES = new Set(["buyer_agent", "listing_agent", "broker", "agent"]);
export function isCollaborator(p: DealParty): boolean {
  return p.permission_tier === "collaborator" || COLLABORATOR_ROLES.has(p.role);
}
/** Parties who can receive a live invite link (vendors: own task; agents/broker:
 *  read-only deal view). Email-only parties (buyer/seller/lender/escrow) can't. */
export function isInvitable(_p: DealParty): boolean {
  // Every party on the deal gets their own scoped workspace link.
  return true;
}

// Timeline-readiness breakdown (backend _deadline_gate_state): which
// deadline-driving §5 fields still block the timeline. `missing_fields` need
// hand-entry, `unconfirmed_fields` need a one-tap confirm.
export interface TimelineGate {
  ready: boolean;
  missing_fields: string[];
  unconfirmed_fields: string[];
}

export interface FullState {
  transaction: { id: string; status: string };
  property: { address: string } | null;
  timeline_gate?: TimelineGate;
  parties: DealParty[];
  documents: DealDocument[];
  extracted_fields: ExtractedField[];
  // One resolved value per field name — a later confirmed value (e.g. a counter
  // offer's price) supersedes an earlier one; superseded_from carries the prior.
  effective_fields?: Record<
    string,
    { value: string; confirmed: boolean; deadline_driving: boolean; superseded_from: string | null }
  >;
  deadlines: Deadline[];
  tasks: Task[];
  messages: Message[];
  reminders: Reminder[];
  risk_flags: DealRiskFlag[];
  approvals: { id: string; message_id: string; approved_by: string }[];
  audit_log: AuditRow[];
}
