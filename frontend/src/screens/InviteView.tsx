import { ChangeEvent, useCallback, useEffect, useState } from "react";
import { fmtDate } from "../lib/format";
import { Icon, IconName } from "../lib/icons";
import { AgentView } from "./invite/AgentView";
import { BuyerView } from "./invite/BuyerView";
import { EscrowView } from "./invite/EscrowView";
import { InspectorView } from "./invite/InspectorView";
import { LenderView } from "./invite/LenderView";
import { SellerView } from "./invite/SellerView";
import { themeFor } from "./invite/roleThemes";
import { DOC_TYPES, RoleViewProps, Task, Workspace } from "./invite/types";

const ROLE_VIEWS: Record<string, (p: RoleViewProps) => JSX.Element> = {
  buyer: BuyerView, seller: SellerView, escrow: EscrowView,
  inspector: InspectorView, lender: LenderView, agent: AgentView,
};

const API: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const DAY = 86_400_000;

const humanize = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
const TASK_NEXT: Record<string, string> = { pending: "in_progress", in_progress: "done", done: "pending" };
const TASK_META: Record<string, { label: string; cls: string }> = {
  pending: { label: "Not started", cls: "st-todo" },
  in_progress: { label: "In progress", cls: "st-doing" },
  done: { label: "Done", cls: "st-done" },
  complete: { label: "Done", cls: "st-done" },
};
const isDone = (s: string) => s === "done" || s === "complete";
const STAGES: { key: string; label: string }[] = [
  { key: "new", label: "New offer" },
  { key: "cont", label: "Contingencies" },
  { key: "closing", label: "Closing" },
  { key: "closed", label: "Closed" },
];
const roleTint: Record<string, string> = {
  buyer: "#5257ea", seller: "#0e9488", buyer_agent: "#c07512", listing_agent: "#c07512",
  escrow: "#4f5a6a", title: "#4f5a6a", lender: "#2563a8", loan_officer: "#2563a8",
};
const tint = (r: string) => roleTint[r] ?? "#8457d6";
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
const mapsLink = (addr: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addr)}`;
const zillowLink = (addr: string) => `https://www.zillow.com/homes/${encodeURIComponent(addr)}_rb/`;

// Money-panel framings: which fields each role's summary shows, in order.
const MONEY_FRAMES: Record<string, { title: string; icon: IconName; rows: [string, string][] }> = {
  money_milestones: { title: "Your numbers", icon: "money", rows: [["purchase_price", "Purchase price"], ["initial_deposit_amount", "Earnest money"], ["loan_amount", "Loan"], ["down_payment", "Down payment"]] },
  offer_summary: { title: "The offer", icon: "receipt", rows: [["purchase_price", "Accepted offer"], ["initial_deposit_amount", "Buyer's deposit"], ["close_of_escrow", "Closing"]] },
  closing_summary: { title: "Closing figures", icon: "bank", rows: [["purchase_price", "Purchase price"], ["initial_deposit_amount", "Earnest money"], ["loan_amount", "Loan"], ["close_of_escrow", "Close of escrow"]] },
  loan_summary: { title: "Loan file", icon: "money", rows: [["loan_amount", "Loan amount"], ["purchase_price", "Purchase price"], ["down_payment", "Down payment"], ["close_of_escrow", "Close of escrow"]] },
};
const DATE_FIELDS = new Set(["close_of_escrow", "acceptance_date"]);

export function InviteView({ token }: { token: string }) {
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [docType, setDocType] = useState("other");
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
  if (!ws) return (
    <div className="inv-load">
      <div className="inv-load-mark"><span>T</span></div>
      <div className="inv-load-bar"><i /></div>
      <div className="inv-load-txt">Preparing your workspace…</div>
    </div>
  );

  const theme = themeFor(ws.archetype);
  const prop = ws.property;
  const addr = prop?.address ?? null;
  const fv = (k: string) => ws.fields[k];

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

  const propertyCard = () => {
    if (!prop) return null;
    const d = prop.details ?? {};
    const facts: [string, IconName, unknown][] = [
      ["Beds", "home", d.beds], ["Baths", "home", d.baths], ["Sq ft", "board", d.sqft],
      ["Year", "clock", d.year_built], ["Lot", "pin", d.lot_size],
    ];
    const shown = facts.filter(([, , v]) => v != null && v !== "");
    return (
      <div className="card pcard" key="property_card">
        <div className="pcard-media">
          {prop.photo_url ? (
            <img className="pcard-img" src={prop.photo_url} alt={addr ?? "the property"} loading="lazy" />
          ) : (
            <div className="pcard-imgph"><Icon name="home" size={30} /><span>Home photo{addr ? "" : " unavailable"}</span></div>
          )}
        </div>
        <div className="pcard-body">
          <div className="pcard-addr">{addr ?? "This property"}</div>
          {(prop.city || prop.zip) && <div className="muted pcard-sub">{[prop.city, prop.zip].filter(Boolean).join(", ")}</div>}
          {shown.length > 0 && (
            <div className="pcard-facts">
              {shown.map(([label, icon, v]) => (
                <div key={label} className="pcard-fact"><Icon name={icon} size={14} /> <b>{String(v)}</b> {label}</div>
              ))}
            </div>
          )}
          {addr && (
            <div className="pcard-links">
              <a className="pcard-btn" href={prop.deep_links?.maps ?? mapsLink(addr)} target="_blank" rel="noreferrer"><Icon name="pin" size={13} /> Google Maps</a>
              <a className="pcard-btn" href={prop.deep_links?.zillow ?? zillowLink(addr)} target="_blank" rel="noreferrer"><Icon name="external" size={13} /> Zillow</a>
            </div>
          )}
          {shown.length === 0 && <div className="muted pcard-note">Home details will appear here once available.</div>}
        </div>
      </div>
    );
  };

  const moneyPanel = (key: string) => {
    const frame = MONEY_FRAMES[key];
    if (!frame) return null;
    const rows = frame.rows.filter(([k]) => fv(k) != null);
    if (rows.length === 0) return null;
    return (
      <div className="card" key={key}>
        <h2><Icon name={frame.icon} size={17} /> {frame.title}</h2>
        <div className="mgrid">
          {rows.map(([k, label]) => (
            <div key={k} className="mgrid-cell">
              <div className="mgrid-k">{label}</div>
              <div className="mgrid-v">{DATE_FIELDS.has(k) ? fmtDate(fv(k)) : fv(k)}</div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const keyDates = () => (
    <div className="card" key="key_dates">
      <h2><Icon name="calendar" size={17} /> Key dates</h2>
      {ws.deadlines.length === 0 ? (
        <div className="empty"><span className="empty-ic"><Icon name="calendar" size={24} /></span>No dated milestones yet.</div>
      ) : (
        <div className="hm-list">
          {[...ws.deadlines].sort((a, b) => a.due_date.localeCompare(b.due_date)).map((d, i) => {
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
      )}
    </div>
  );

  const dealProgress = () => {
    const idx = Math.max(0, STAGES.findIndex((s) => s.key === ws.stage));
    return (
      <div className="card" key="deal_progress">
        <h2><Icon name="flag" size={17} /> Where the deal stands</h2>
        <div className="stagebar">
          {STAGES.map((s, i) => (
            <div key={s.key} className={`stagebar-step ${i < idx ? "done" : ""} ${i === idx ? "on" : ""}`}>
              <span className="stagebar-dot">{i < idx ? "✓" : i + 1}</span>
              <span className="stagebar-lbl">{s.label}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const includedItems = () => {
    if (!prop?.included_items && !prop?.excluded_items) return null;
    return (
      <div className="card" key="included_items">
        <h2><Icon name="tag" size={17} /> Included in the sale</h2>
        {prop.included_items && <p style={{ margin: "0 0 0.4rem" }}><b>Stays:</b> {prop.included_items}</p>}
        {prop.excluded_items && <p className="muted" style={{ margin: 0 }}><b>Excluded:</b> {prop.excluded_items}</p>}
      </div>
    );
  };

  const myTasks = () => (
    <div className="card" key="my_tasks">
      <h2><Icon name="checkCircle" size={17} /> {ws.archetype === "inspector" ? "Your inspection" : "Your tasks"}</h2>
      {ws.my_tasks.length === 0 ? (
        <div className="empty"><span className="empty-ic"><Icon name="checkCircle" size={24} /></span>Nothing needs you right now.</div>
      ) : <div className="stack">{ws.my_tasks.map(taskRow)}</div>}
    </div>
  );

  const myDocuments = () => (
    <div className="card" key="my_documents">
      <h2><Icon name="doc" size={17} /> {ws.archetype === "inspector" ? "Upload your report" : "Your documents"}</h2>
      <p className="muted" style={{ margin: "-0.4rem 0 0.8rem" }}>Only the coordinator sees what you upload.</p>
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
              <div className="doc-ic sm" style={{ background: theme.soft, color: theme.accent }}><Icon name="doc" size={16} /></div>
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
  );

  const roster = () => (
    <div className="card" key="roster">
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
  );

  const renderSection = (key: string) => {
    switch (key) {
      case "property_card": return propertyCard();
      case "money_milestones":
      case "offer_summary":
      case "closing_summary":
      case "loan_summary": return moneyPanel(key);
      case "key_dates": return keyDates();
      case "deal_progress": return dealProgress();
      case "included_items": return includedItems();
      case "my_tasks": return myTasks();
      case "my_documents": return myDocuments();
      case "roster": return roster();
      default: return null;
    }
  };

  return (
    <div className="inv2" style={{ ["--role-accent" as string]: theme.accent, ["--role-soft" as string]: theme.soft }}>
      <header className="inv2-bar">
        <div className="brand"><div className="mark">T</div><div><div className="name">Terra</div><div className="sub">Shared workspace</div></div></div>
        <div className="inv2-me">
          <div className="side-ava" style={{ background: theme.accent }}>{initials(ws.me.name, ws.me.role)}</div>
          <div><div className="inv2-me-name">{ws.me.name ?? "You"}</div><div className="inv2-me-role">{humanize(ws.me.role)}</div></div>
          <button className="kbtn icon" title="Toggle theme" onClick={toggleTheme}>{dark ? "☀" : "☾"}</button>
        </div>
      </header>

      {ROLE_VIEWS[ws.archetype] ? (
        (() => {
          const RoleView = ROLE_VIEWS[ws.archetype];
          return <RoleView ws={ws} busy={busy} docType={docType} setDocType={setDocType} cycle={cycle} onFile={onFile} />;
        })()
      ) : (
        <main className="inv2-page">
          <section className="inv2-hero">
            <div className="inv2-hero-ic"><Icon name={theme.icon} size={26} /></div>
            <div className="inv2-hero-eyebrow">{theme.eyebrow}</div>
            <h1 className="inv2-hero-title">{theme.greeting(ws.me.name)}</h1>
            <p className="inv2-hero-sub">{addr ? `${addr} · ` : ""}{theme.tagline}</p>
          </section>

          {ws.sections.map(renderSection)}

          <p className="inv-foot muted">
            <Icon name="lock" size={13} /> This view is personalized to your role and scoped to this deal — you see only
            what you need, complete only your own tasks, and can't see other parties' private information or any other transaction.
          </p>
        </main>
      )}
    </div>
  );
}
