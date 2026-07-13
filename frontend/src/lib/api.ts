import { supabase } from "./supabase";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(detail);
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
  created_at: string;
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
}

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
}

export interface Message {
  id: string;
  subject: string | null;
  body: string | null;
  status: "draft" | "approved" | "sent";
  sent_at: string | null;
}

export interface AuditRow {
  actor: string;
  action: string;
  entity_type: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface FullState {
  transaction: { id: string; status: string };
  property: { address: string } | null;
  extracted_fields: ExtractedField[];
  deadlines: Deadline[];
  tasks: Task[];
  messages: Message[];
  approvals: { id: string; message_id: string; approved_by: string }[];
  audit_log: AuditRow[];
}
