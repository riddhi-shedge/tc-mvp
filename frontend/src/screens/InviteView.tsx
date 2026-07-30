import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { fmtDate } from "../lib/format";
import { Icon, IconName } from "../lib/icons";

const API: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const DAY = 86_400_000;

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
const STAGE_LABEL: Record<string, string> = { new: "New offer", cont: "Contingency period", closing: "Closing", closed: "Closed" };

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
function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso + "T00:00:00").getTime();
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.round((t - now.getTime()) / DAY);
}
const countdown = (n: number | null) => (n == null ? "—" : n < 0 ? `${-n}d ago` : n === 0 ? "today" : `${n}d`);
const dstamp = (iso: string) => fmtDate(iso).replace(/,\s*\d{4}$/, "");

type ViewName = "home" | "calendar" | "deal";

/** An invited party's own scoped WORKSPACE — the same shell as the coordinator
 *  (Home · Calendar · My deal), but showing only what they're allowed to see and
 *  do: the roster + process, and only their own tasks and documents. */
export function InviteView({ token }: { token: string }) {
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [docType, setDocType] = useState("other");
  const [view, setView] = useState<ViewName>("home");
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); d.setHours(0, 0, 0, 0); return d; });
  const [dark, setDark] = useState(() => document.documentElement.getAttribute("data-theme") === "dark");

  function toggleTheme() {
    setDark((d) => {
      const next = !d;
      document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
      localStorage.setItem("theme", next ? "dark" : "light");
      return next;
    });
  }

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

  const weeks = useMemo(() => {
    const start = new Date(cursor);
    start.setDate(start.getDate() - start.getDay());
    return Array.from({ length: 6 }, (_, w) =>
      Array.from({ length: 7 }, (_, d) => { const x = new Date(start); x.setDate(start.getDate() + w * 7 + d); return x; }),
    );
  }, [cursor]);

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
  if (!ws) return <div className="inv-wrap"><p className="muted" style={{ padding: "10vh 2rem", textAlign: "center" }}>Loading your workspace…</p></div>;

  const openTasks = ws.my_tasks.filter((t) => !isDone(t.status));
  const nextDl = [...ws.timeline].filter((d) => (daysTo(d.due_date) ?? -1) >= 0).sort((a, b) => a.due_date.localeCompare(b.due_date))[0] ?? null;
  const blurb = ROLE_BLURB[ws.me.role] ?? "See where the deal stands, complete your tasks, and upload your documents.";

  const nav: { id: ViewName; label: string; icon: IconName }[] = [
    { id: "home", label: "Home", icon: "home" },
    { id: "calendar", label: "Calendar", icon: "calendar" },
    { id: "deal", label: "My deal", icon: "doc" },
  ];

  const taskRow = (t: Task) => {
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
          {t.due_date && <div className="task-meta muted"><Icon name="calendar" size={12} /> {dstamp(t.due_date)}</div>}
        </div>
        <span className={`st-pill ${meta.cls}`}>{meta.label}</span>
      </div>
    );
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">T</div>
          <div>
            <div className="name">Terra</div>
            <div className="sub">Shared workspace</div>
          </div>
        </div>
        {nav.map((n) => (
          <button key={n.id} className={`nav-item ${view === n.id ? "active" : ""}`} onClick={() => setView(n.id)}>
            {view === n.id && <span className="side-ind" />}
            <span className="ni-label"><span className="ic"><Icon name={n.icon} /></span> {n.label}</span>
          </button>
        ))}
        <div className="spacer" />
        <div className="side-account">
          <div className="side-ava" style={{ background: tint(ws.me.role) }}>{initials(ws.me.name, ws.me.role)}</div>
          <div className="side-account-info">
            <div className="side-email">{ws.me.name ?? "You"}</div>
            <div className="side-plan">{humanize(ws.me.role)}</div>
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <div className="crumbs"><b>{nav.find((n) => n.id === view)?.label}</b></div>
          <div className="top-sp" />
          <button className="kbtn icon" title="Toggle theme" onClick={toggleTheme}>{dark ? "☀" : "☾"}</button>
        </div>
        <div className="page">
          {/* ---- HOME ---- */}
          {view === "home" && (
            <div className="hm">
              <div>
                <h1>Hi {ws.me.name ?? "there"}</h1>
                <div className="hm-sub">{ws.property_address ?? "Your transaction"} · {blurb}</div>
              </div>
              <div className="hm-stats">
                <div className="hm-stat"><div className="hm-k"><span className="hm-kd" style={{ background: "var(--gold-500)" }} />Your open tasks</div><div className="hm-v tnum">{openTasks.length}</div></div>
                <div className="hm-stat"><div className="hm-k"><span className="hm-kd" style={{ background: "var(--red-600)" }} />Next deadline</div><div className="hm-v" style={{ fontSize: "1.1rem" }}>{nextDl ? dstamp(nextDl.due_date) : "—"}</div></div>
                <div className="hm-stat"><div className="hm-k"><span className="hm-kd" style={{ background: "var(--muted)" }} />Stage</div><div className="hm-v" style={{ fontSize: "1.05rem" }}>{ws.stage ? STAGE_LABEL[ws.stage] ?? ws.stage : "—"}</div></div>
              </div>
              <div className="hm-cols">
                <div>
                  <div className="hm-section">
                    <div className="hm-sh"><span className="hm-st">Your tasks</span><span className="hm-sc">{openTasks.length}</span></div>
                    <div className="hm-list">
                      {openTasks.length === 0 ? <div className="hm-empty">Nothing needs you right now.</div> : openTasks.map(taskRow)}
                    </div>
                  </div>
                </div>
                <div>
                  <div className="hm-section">
                    <div className="hm-sh"><span className="hm-st">Coming up</span><span className="hm-sc">{ws.timeline.length}</span></div>
                    <div className="hm-list">
                      {ws.timeline.length === 0 ? <div className="hm-empty">No dated milestones yet.</div> :
                        [...ws.timeline].sort((a, b) => a.due_date.localeCompare(b.due_date)).slice(0, 8).map((d, i) => {
                          const n = daysTo(d.due_date);
                          return (
                            <div key={i} className="hm-row" style={{ cursor: "default" }}>
                              <span className="hm-date tnum">{dstamp(d.due_date)}</span>
                              <div className="hm-main"><div className="hm-title">{d.name}</div></div>
                              <span className={`pill-${n != null && n <= 2 ? "red" : n != null && n <= 7 ? "amber" : "plain"}`}>{countdown(n)}</span>
                            </div>
                          );
                        })}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ---- CALENDAR ---- */}
          {view === "calendar" && (
            <div className="cal">
              <div className="page-head">
                <div><h1>Calendar</h1><div className="muted">The deal's key dates and your tasks.</div></div>
                <div className="row" style={{ gap: "0.5rem", flex: "0 0 auto" }}>
                  <button className="secondary" onClick={() => { const d = new Date(); d.setDate(1); d.setHours(0, 0, 0, 0); setCursor(d); }}>Today</button>
                </div>
              </div>
              <div className="card cal-main">
                <div className="cal-toolbar">
                  <button className="kbtn icon" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>‹</button>
                  <b>{cursor.toLocaleDateString("en-US", { month: "long", year: "numeric" })}</b>
                  <button className="kbtn icon" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>›</button>
                </div>
                <div className="cal-dow">{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((w) => <div key={w}>{w}</div>)}</div>
                <div className="cal-weeks">
                  {weeks.map((wk, wi) => (
                    <div key={wi} className="cal-week">
                      {wk.map((day) => {
                        const k = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
                        const inMonth = day.getMonth() === cursor.getMonth();
                        const isToday = daysTo(k) === 0;
                        const dls = ws.timeline.filter((d) => d.due_date === k);
                        const tks = ws.my_tasks.filter((t) => t.due_date === k);
                        return (
                          <div key={k} className={`cal-day ${inMonth ? "" : "off"} ${isToday ? "today" : ""}`} style={{ cursor: "default" }}>
                            <div className="cal-dnum">{day.getDate()}</div>
                            {dls.map((d, i) => <div key={`d${i}`} className="cal-dl" title={d.name}><span className="cal-dot" /> {d.name.replace(/ (ends|due|delivery|delivered).*$/i, "")}</div>)}
                            {tks.map((t) => <div key={t.id} className="cal-task" title={t.title}><span className="cal-task-t">{t.title}</span></div>)}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ---- MY DEAL ---- */}
          {view === "deal" && (
            <>
              <div className="card inv-hero" style={{ marginBottom: "1.1rem" }}>
                <div className="inv-eyebrow">Your view · {humanize(ws.me.role)}</div>
                <h1 style={{ margin: "0.2rem 0 0" }}>{ws.property_address ?? "This property"}</h1>
                <p className="muted" style={{ margin: "0.4rem 0 0" }}>{blurb} Private information for other parties stays private.</p>
              </div>

              <div className="card">
                <h2><Icon name="checkCircle" size={17} /> Your tasks</h2>
                {ws.my_tasks.length === 0 ? (
                  <div className="empty"><span className="empty-ic"><Icon name="checkCircle" size={24} /></span>Nothing needs you right now.</div>
                ) : <div className="stack">{ws.my_tasks.map(taskRow)}</div>}
              </div>

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

              <div className="card">
                <h2><Icon name="calendar" size={17} /> The process</h2>
                {ws.timeline.length === 0 ? (
                  <div className="empty"><span className="empty-ic"><Icon name="calendar" size={26} /></span>No dated milestones yet.</div>
                ) : (
                  <div className="stack">
                    {ws.timeline.map((d, i) => (
                      <div key={i} className="inv-dl"><span className="inv-dl-date">{fmtDate(d.due_date)}</span><span className="inv-dl-name">{d.name}</span></div>
                    ))}
                  </div>
                )}
              </div>

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
                <Icon name="lock" size={13} /> Scoped to this deal — you complete only your own tasks and upload your own
                documents. You can't see other parties' private information or any other transaction.
              </p>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
