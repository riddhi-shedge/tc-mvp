import { ChangeEvent, useCallback, useEffect, useState } from "react";
import { fmtDate } from "../lib/format";
import { Icon } from "../lib/icons";

const API: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

type Task = { id: string; title: string; status: string; due_date: string | null; priority: string };
type Doc = { id: string; doc_type: string | null; status: string; created_at?: string };
type Workspace = {
  me: { name: string | null; role: string; email: string | null; company: string | null; tier: string };
  property_address: string | null;
  stage: string | null;
  roster: { name: string | null; role: string }[];
  timeline: { name: string; due_date: string }[];
  my_tasks: Task[];
  my_documents: Doc[];
};

const humanize = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
const TASK_NEXT: Record<string, string> = { pending: "in_progress", in_progress: "done", done: "pending" };
const TASK_META: Record<string, { label: string; cls: string }> = {
  pending: { label: "Not started", cls: "st-todo" },
  in_progress: { label: "In progress", cls: "st-doing" },
  done: { label: "Done", cls: "st-done" },
  complete: { label: "Done", cls: "st-done" },
};
const isDone = (s: string) => s === "done" || s === "complete";

// Role → tint (roster avatars) + a tailored line for what this person can do.
const TINT: Record<string, string> = {
  buyer: "#5257ea", seller: "#0e9488", buyer_agent: "#c07512", listing_agent: "#c07512",
  escrow: "#5b6472", title: "#5b6472", lender: "#5b6472",
};
const tint = (r: string) => TINT[r] ?? "#8457d6";
const ROLE_BLURB: Record<string, string> = {
  buyer_agent: "Track the deal, complete your tasks, and upload buyer-side documents.",
  listing_agent: "Track the deal, complete your tasks, and upload seller-side documents.",
  escrow: "See the timeline, confirm your items, and upload escrow documents.",
  lender: "See the loan timeline, respond to status items, and upload loan documents.",
  title: "See the timeline and upload title documents.",
  inspector_general: "Upload your inspection report and mark your inspection complete.",
  appraiser: "Upload your appraisal and mark it complete.",
  buyer: "Follow your purchase, complete your to-dos, and upload requested documents.",
  seller: "Follow your sale, complete your to-dos, and upload requested documents.",
};
const DOC_TYPES = [
  { v: "proof_of_funds", label: "Proof of funds" },
  { v: "inspection_report", label: "Inspection report" },
  { v: "appraisal", label: "Appraisal" },
  { v: "disclosure", label: "Disclosure" },
  { v: "other", label: "Other document" },
];
function initials(name: string | null, role: string) {
  const s = (name || role || "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** An invited party's own scoped workspace: they see who's involved and where the
 *  deal stands, complete only THEIR tasks, and upload their own documents. All
 *  scoping is enforced by the backend from their signed token. */
export function InviteView({ token }: { token: string }) {
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [docType, setDocType] = useState("other");

  const papi = useCallback(
    async <T,>(path: string, init?: RequestInit): Promise<T> => {
      const res = await fetch(`${API}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...init?.headers },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error((body as { detail?: string }).detail ?? "Request failed");
      return body as T;
    },
    [token],
  );

  const load = useCallback(async () => {
    try {
      setWs(await papi<Workspace>("/party/workspace"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "This invite link is invalid or has expired.");
    }
  }, [papi]);
  useEffect(() => { void load(); }, [load]);

  async function cycle(t: Task) {
    setBusy(true);
    try {
      await papi(`/party/tasks/${t.id}/status`, { method: "POST", body: JSON.stringify({ status: TASK_NEXT[t.status] ?? "in_progress" }) });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update that task.");
    } finally {
      setBusy(false);
    }
  }

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const b64 = (reader.result as string).split(",", 2)[1] ?? "";
        await papi("/party/documents", { method: "POST", body: JSON.stringify({ filename: file.name, content_base64: b64, doc_type: docType }) });
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed.");
      } finally {
        setBusy(false);
      }
    };
    reader.readAsDataURL(file);
  }

  if (error) {
    return (
      <div className="inv-wrap">
        <div className="card" style={{ maxWidth: 460, margin: "10vh auto", textAlign: "center" }}>
          <div className="mark" style={{ margin: "0 auto 1rem" }}>T</div>
          <h2>This invite isn't available</h2>
          <p className="muted">{error}</p>
        </div>
      </div>
    );
  }
  if (!ws) return <div className="inv-wrap"><p className="muted" style={{ padding: "10vh 2rem", textAlign: "center" }}>Loading…</p></div>;

  const dateOf = (iso: string | null) => (iso ? fmtDate(iso).replace(/,\s*\d{4}$/, "") : null);
  const blurb = ROLE_BLURB[ws.me.role] ?? "See where the deal stands, complete your tasks, and upload your documents.";

  return (
    <div className="inv-wrap">
      <div className="inv-shell">
        <div className="inv-top">
          <div className="brand">
            <div className="mark">T</div>
            <div>
              <div className="name" style={{ color: "var(--ink)" }}>Terra</div>
              <div className="sub" style={{ color: "var(--muted)" }}>Shared with you</div>
            </div>
          </div>
        </div>

        <div className="card inv-hero">
          <div className="inv-eyebrow">Your view · {humanize(ws.me.role)}</div>
          <h1 style={{ margin: "0.2rem 0 0" }}>Hi {ws.me.name ?? "there"}</h1>
          <p className="muted" style={{ margin: "0.4rem 0 0" }}>
            Here's the transaction for <b style={{ color: "var(--ink)" }}>{ws.property_address ?? "this property"}</b>. {blurb}
          </p>
        </div>

        {/* Your tasks — actionable */}
        <div className="card">
          <h2><Icon name="checkCircle" size={17} /> Your tasks</h2>
          {ws.my_tasks.length === 0 ? (
            <div className="empty"><span className="empty-ic"><Icon name="checkCircle" size={24} /></span>Nothing needs you right now.</div>
          ) : (
            <div className="stack">
              {ws.my_tasks.map((t) => {
                const done = isDone(t.status);
                const inProg = t.status === "in_progress";
                const meta = TASK_META[t.status] ?? TASK_META.pending;
                return (
                  <div key={t.id} className={`task-row ${done ? "done" : ""} ${inProg ? "doing" : ""}`}>
                    <button
                      className={`task-check ${done ? "done" : ""} ${inProg ? "doing" : ""}`}
                      disabled={busy}
                      title={`Mark ${(TASK_META[TASK_NEXT[t.status]] ?? TASK_META.pending).label.toLowerCase()}`}
                      onClick={() => void cycle(t)}
                    >
                      {done ? "✓" : inProg ? "◐" : ""}
                    </button>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="task-title">{t.title}</div>
                      {t.due_date && <div className="task-meta muted"><Icon name="calendar" size={12} /> {dateOf(t.due_date)}</div>}
                    </div>
                    <span className={`st-pill ${meta.cls}`}>{meta.label}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Upload your documents */}
        <div className="card">
          <h2><Icon name="doc" size={17} /> Your documents</h2>
          <p className="muted" style={{ margin: "-0.4rem 0 0.8rem" }}>Upload documents for your part of the deal — only the coordinator sees them.</p>
          <div className="inv-upload">
            <select value={docType} onChange={(e) => setDocType(e.target.value)} style={{ maxWidth: 220 }}>
              {DOC_TYPES.map((d) => <option key={d.v} value={d.v}>{d.label}</option>)}
            </select>
            <label className={`inv-uploadbtn ${busy ? "off" : ""}`}>
              <Icon name="attach" size={14} /> Choose file…
              <input type="file" hidden disabled={busy} onChange={onFile} />
            </label>
          </div>
          {ws.my_documents.length > 0 && (
            <div className="stack" style={{ marginTop: "0.8rem" }}>
              {ws.my_documents.map((d) => (
                <div key={d.id} className="inv-doc">
                  <div className="doc-ic sm" style={{ background: "#8457d61f", color: "#8457d6" }}><Icon name="doc" size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="doc-name">{humanize(d.doc_type ?? "document")}</div>
                    {d.created_at && <div className="muted" style={{ fontSize: "0.76rem" }}>Uploaded {fmtDate(d.created_at)}</div>}
                  </div>
                  <span className="badge ok">{d.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* The process */}
        <div className="card">
          <h2><Icon name="calendar" size={17} /> The process</h2>
          {ws.timeline.length === 0 ? (
            <div className="empty"><span className="empty-ic"><Icon name="calendar" size={26} /></span>No dated milestones yet.</div>
          ) : (
            <div className="stack">
              {ws.timeline.map((d, i) => (
                <div key={i} className="inv-dl">
                  <span className="inv-dl-date">{fmtDate(d.due_date)}</span>
                  <span className="inv-dl-name">{d.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Everyone on this deal (visible to all) */}
        <div className="card">
          <h2><Icon name="users" size={17} /> Everyone on this deal</h2>
          <p className="muted" style={{ margin: "-0.4rem 0 0.8rem" }}>The people coordinating this transaction. Private contact details stay private.</p>
          <div className="inv-roster">
            {ws.roster.map((p, i) => (
              <div key={i} className="inv-person">
                <div className="prow-ava" style={{ background: tint(p.role) }}>{initials(p.name, p.role)}</div>
                <div style={{ minWidth: 0 }}>
                  <div className="prow-name">{p.name ?? humanize(p.role)}</div>
                  <div className="prow-role">{humanize(p.role)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="inv-foot muted">
          <Icon name="lock" size={13} /> Scoped to this deal — you see who's involved and the schedule, complete only your
          own tasks, and upload your own documents. You can't see other parties' private information or any other transaction.
        </p>
      </div>
    </div>
  );
}
