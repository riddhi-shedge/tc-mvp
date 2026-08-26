export type Task = { id: string; title: string; status: string; due_date: string | null; priority: string };
export type Doc = { id: string; doc_type: string | null; status: string; created_at?: string };
export type PropertyView = {
  address: string | null;
  city: string | null;
  zip: string | null;
  included_items: string | null;
  excluded_items: string | null;
  details?: Record<string, string | number | null> | null;
  photo_url?: string | null;
  deep_links?: Record<string, string> | null;
};
export type Workspace = {
  me: { name: string | null; role: string; email: string | null; company: string | null; tier: string };
  archetype: string;
  sections: string[];
  property: PropertyView | null;
  fields: Record<string, string>;
  stage: string | null;
  roster: { name: string | null; role: string }[];
  deadlines: { name: string; due_date: string }[];
  my_tasks: Task[];
  my_documents: Doc[];
};

/** Handlers + state the shell owns, passed down to a bespoke per-role layout. */
export type RoleViewProps = {
  ws: Workspace;
  busy: boolean;
  docType: string;
  setDocType: (v: string) => void;
  cycle: (t: Task) => void;
  onFile: (e: React.ChangeEvent<HTMLInputElement>) => void;
};

export const DOC_TYPES = [
  { v: "proof_of_funds", label: "Proof of funds" },
  { v: "inspection_report", label: "Inspection report" },
  { v: "appraisal", label: "Appraisal" },
  { v: "disclosure", label: "Disclosure" },
  { v: "other", label: "Other document" },
];
