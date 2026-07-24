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
}

export interface TransactionSummary {
  id: string;
  status: string;
  property_address: string | null;
  created_at: string;
}

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
}

export interface Message {
  id: string;
  subject: string | null;
  body: string | null;
  status: "draft" | "approved" | "sent";
  sent_at: string | null;
  party_id: string | null;
}

export interface DealParty {
  id: string;
  name: string | null;
  role: string;
  email: string | null;
  permission_tier?: string;
}

export interface AuditRow {
  actor: string;
  action: string;
  entity_type: string;
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
  deadlines: Deadline[];
  tasks: Task[];
  messages: Message[];
  risk_flags: DealRiskFlag[];
  approvals: { id: string; message_id: string; approved_by: string }[];
  audit_log: AuditRow[];
}
