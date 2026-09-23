import { useEffect, useState } from "react";
import { fmtDate } from "../../lib/format";
import { Icon, IconName } from "../../lib/icons";
import { DOC_TYPES, RoleViewProps } from "./types";

const DAY = 86_400_000;
const humanize = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
const isDone = (s: string) => s === "done" || s === "complete";
function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso + "T00:00:00").getTime();
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.round((t - now.getTime()) / DAY);
}
const shortName = (n: string) => n.replace(/\s+(contingency\s+)?(ends|due|delivery|delivered|deadline).*$/i, "").trim();
function initials(name: string | null, role: string) {
  const s = (name || role || "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** The buyer's view — an immersive "your future home" portal. A photo hero, a
 *  move-in countdown, the journey to the keys, and their numbers/team/to-dos.
 *  Deliberately warm and distinct from the coordinator's dashboard. */
export function BuyerView({ ws, busy, docType, setDocType, cycle, onFile }: RoleViewProps) {
  const prop = ws.property;
  const addr = prop?.address ?? null;
  const photo = prop?.photo_url ?? null;
  const d = prop?.details ?? {};
  const fv = (k: string) => ws.fields[k];

  const coe = ws.deadlines.find((x) => /escrow|clos/i.test(x.name)) ?? null;
  const keysDate = coe?.due_date ?? null;
  const nDays = daysTo(keysDate);

  // count the "days to keys" up on load — a small, warm moment
  const [shownDays, setShownDays] = useState(0);
  useEffect(() => {
    if (nDays == null || nDays <= 0) { setShownDays(nDays ?? 0); return; }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { setShownDays(nDays); return; }
    let raf = 0; const start = performance.now(); const dur = 950;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / dur);
      setShownDays(Math.round(nDays * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [nDays]);

  // progress through the escrow window (acceptance → close)
  const acc = fv("acceptance_date");
  let pct = 0;
  if (acc && keysDate) {
    const a = new Date(acc + "T00:00:00").getTime();
    const c = new Date(keysDate + "T00:00:00").getTime();
    const now = Date.now();
    pct = c > a ? Math.min(100, Math.max(0, ((now - a) / (c - a)) * 100)) : 0;
  }

  const facts: [IconName, string, unknown][] = [
    ["home", "beds", d.beds], ["home", "baths", d.baths], ["board", "sq ft", d.sqft], ["clock", "built", d.year_built],
  ];
  const shownFacts = facts.filter(([, , v]) => v != null && v !== "");

  const money: [string, string, IconName][] = [
    ["Purchase price", "purchase_price", "home"],
    ["Your loan", "loan_amount", "bank"],
    ["Down payment", "down_payment", "money"],
    ["Earnest money", "initial_deposit_amount", "receipt"],
  ];
  const shownMoney = money.filter(([, k]) => fv(k) != null);

  // journey to the keys
  const step = (label: string, date: string | null) => ({ label, date, done: (daysTo(date) ?? 1) < 0 });
  const mids = ws.deadlines
    .filter((x) => x !== coe)
    .sort((a, b) => a.due_date.localeCompare(b.due_date))
    .map((x) => step(shortName(x.name), x.due_date));
  const journey = [
    { label: "Offer accepted", date: acc ?? null, done: true },
    ...mids,
    ...(keysDate ? [step("Closing day", keysDate)] : []),
    { label: "Move in 🔑", date: keysDate, done: false, keys: true },
  ];
  const activeIdx = journey.findIndex((s) => !s.done);

  const openTasks = ws.my_tasks.filter((t) => !isDone(t.status));

  return (
    <div className="bv">
      {/* HERO */}
      <div className={`bv-hero ${photo ? "has-photo" : ""}`}>
        <div className="bv-hero-photo" style={photo ? { backgroundImage: `url(${photo})` } : undefined} />
        <div className="bv-hero-scrim" />
        <div className="bv-hero-in">
          <div className="bv-eyebrow"><Icon name="home" size={13} /> Your future home</div>
          <h1 className="bv-addr">{addr ?? "Your new home"}</h1>
          {(prop?.city || prop?.zip) && <div className="bv-city">{[prop?.city, prop?.zip].filter(Boolean).join(", ")}</div>}
        </div>
      </div>

      <div className="bv-body">
      {/* COUNTDOWN */}
      {keysDate && (
        <div className="bv-count card">
          <div className="bv-count-main">
            <div className="bv-count-n">{nDays != null && nDays > 0 ? shownDays : nDays === 0 ? "0" : "✓"}</div>
            <div>
              <div className="bv-count-lbl">
                {nDays != null && nDays > 0 ? `days until you get the keys` : nDays === 0 ? "Closing day." : "Closed. Congratulations!"}
              </div>
              <div className="bv-count-date muted">Closing {fmtDate(keysDate)}</div>
            </div>
          </div>
          <div className="bv-progress"><div className="bv-progress-fill" style={{ width: `${pct}%` }} /></div>
        </div>
      )}

      {/* HOME AT A GLANCE */}
      {(shownFacts.length > 0 || addr) && (
        <div className="card bv-glance">
          <h2><Icon name="home" size={17} /> Your home at a glance</h2>
          {shownFacts.length > 0 ? (
            <div className="bv-facts">
              {shownFacts.map(([icon, label, v]) => (
                <div key={label} className="bv-fact"><Icon name={icon} size={18} /><div className="bv-fact-v">{String(v)}</div><div className="bv-fact-k">{label}</div></div>
              ))}
            </div>
          ) : (
            <p className="muted" style={{ margin: 0 }}>Home details (beds, baths, size) will appear here once available.</p>
          )}
          {addr && (
            <div className="bv-links">
              <a className="bv-link" href={prop?.deep_links?.maps ?? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addr)}`} target="_blank" rel="noreferrer"><Icon name="pin" size={13} /> Walk the neighborhood</a>
              <a className="bv-link" href={prop?.deep_links?.zillow ?? `https://www.zillow.com/homes/${encodeURIComponent(addr)}_rb/`} target="_blank" rel="noreferrer"><Icon name="external" size={13} /> See it on Zillow</a>
            </div>
          )}
        </div>
      )}

      {/* JOURNEY */}
      <div className="card bv-journey">
        <h2><Icon name="flag" size={17} /> Your journey to the keys</h2>
        <div className="bv-path">
          {journey.map((s, i) => (
            <div key={i} className={`bv-step ${s.done ? "done" : ""} ${i === activeIdx ? "on" : ""} ${"keys" in s && s.keys ? "keys" : ""}`}>
              <div className="bv-step-dot">{s.done ? "✓" : "keys" in s && s.keys ? "🔑" : i + 1}</div>
              <div className="bv-step-body">
                <div className="bv-step-lbl">{s.label}</div>
                {s.date && <div className="bv-step-date muted">{fmtDate(s.date)}</div>}
              </div>
              {i === activeIdx && <span className="bv-step-now">You're here</span>}
            </div>
          ))}
        </div>
      </div>

      {/* NUMBERS */}
      {shownMoney.length > 0 && (
        <div className="card">
          <h2><Icon name="money" size={17} /> Your numbers</h2>
          <div className="bv-nums">
            {shownMoney.map(([label, k, icon]) => (
              <div key={k} className="bv-num"><div className="bv-num-ic"><Icon name={icon} size={16} /></div><div><div className="bv-num-k">{label}</div><div className="bv-num-v">{fv(k)}</div></div></div>
            ))}
          </div>
        </div>
      )}

      {/* TO-DOS */}
      <div className="card">
        <h2><Icon name="checkCircle" size={17} /> What needs you</h2>
        {openTasks.length === 0 ? (
          <div className="bv-clear"><span>✓</span> You're all caught up.</div>
        ) : (
          <div className="stack">
            {openTasks.map((t) => (
              <div key={t.id} className={`task-row ${t.status === "in_progress" ? "doing" : ""}`}>
                <button className={`task-check ${t.status === "in_progress" ? "doing" : ""}`} disabled={busy} onClick={() => cycle(t)}>{t.status === "in_progress" ? "◐" : ""}</button>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="task-title">{t.title}</div>
                  {t.due_date && <div className="task-meta muted"><Icon name="calendar" size={12} /> {fmtDate(t.due_date)}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* YOUR TEAM */}
      <div className="card">
        <h2><Icon name="users" size={17} /> Your team</h2>
        <div className="bv-team">
          {ws.roster.map((p, i) => (
            <div key={i} className="bv-teammate">
              <div className="bv-ava">{initials(p.name, p.role)}</div>
              <div className="bv-teammate-name">{p.name ?? humanize(p.role)}</div>
              <div className="bv-teammate-role">{humanize(p.role)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* UPLOAD */}
      <div className="card">
        <h2><Icon name="doc" size={17} /> Send a document</h2>
        <p className="muted" style={{ margin: "-0.4rem 0 0.8rem" }}>Anything your coordinator asked for. Only they see it.</p>
        <div className="inv-upload">
          <select value={docType} onChange={(e) => setDocType(e.target.value)} style={{ maxWidth: 220 }}>
            {DOC_TYPES.map((t) => <option key={t.v} value={t.v}>{t.label}</option>)}
          </select>
          <label className={`inv-uploadbtn ${busy ? "off" : ""}`}><Icon name="attach" size={14} /> Choose file…<input type="file" hidden disabled={busy} onChange={onFile} /></label>
        </div>
        {ws.my_documents.length > 0 && (
          <div className="stack" style={{ marginTop: "0.8rem" }}>
            {ws.my_documents.map((doc) => (
              <div key={doc.id} className="inv-doc">
                <div className="doc-ic sm" style={{ background: "#5257ea1a", color: "#5257ea" }}><Icon name="doc" size={16} /></div>
                <div style={{ flex: 1, minWidth: 0 }}><div className="doc-name">{humanize(doc.doc_type ?? "document")}</div>{doc.created_at && <div className="muted" style={{ fontSize: "0.76rem" }}>Uploaded {fmtDate(doc.created_at)}</div>}</div>
                <span className="badge ok">{doc.status}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
