import { fmtDate } from "../../lib/format";
import { Icon } from "../../lib/icons";
import { TaskRow, daysTo, humanize, initials, isDone } from "./helpers";
import { RoleViewProps } from "./types";

const DOCS = [
  { v: "disclosure", label: "Disclosure (TDS / SPQ)" },
  { v: "other", label: "Repair receipt" },
  { v: "other", label: "HOA documents" },
  { v: "other", label: "Other document" },
];
const dstamp = (iso: string) => fmtDate(iso).replace(/,\s*\d{4}$/, "");

/** The seller's view — "your sale." Reassurance-first: is the buyer on track to
 *  close? Plus the sale figures, what's included, and their disclosures to deliver. */
export function SellerView({ ws, busy, docType, setDocType, cycle, onFile }: RoleViewProps) {
  const prop = ws.property;
  const photo = prop?.photo_url ?? null;
  const fv = (k: string) => ws.fields[k];
  const find = (re: RegExp) => ws.deadlines.find((d) => re.test(d.name)) ?? null;
  const coe = find(/escrow|clos/i);
  const nDays = daysTo(coe?.due_date ?? null);

  const past = (iso?: string | null) => (daysTo(iso ?? null) ?? 1) < 0;
  const progress = [
    { label: "Offer accepted", date: fv("acceptance_date") ?? null, done: true },
    { label: "Earnest money deposited", date: find(/earnest|deposit|emd/i)?.due_date ?? null, done: past(find(/earnest|deposit|emd/i)?.due_date) },
    { label: "Inspections cleared", date: find(/inspection/i)?.due_date ?? null, done: past(find(/inspection/i)?.due_date) },
    { label: "Appraisal cleared", date: find(/appraisal/i)?.due_date ?? null, done: past(find(/appraisal/i)?.due_date) },
    { label: "Loan approved", date: find(/loan/i)?.due_date ?? null, done: past(find(/loan/i)?.due_date) },
    { label: "Clear to close", date: coe?.due_date ?? null, done: past(coe?.due_date) },
  ];
  const doneCount = progress.filter((s) => s.done).length;
  const activeIdx = progress.findIndex((s) => !s.done);
  const pct = Math.round((doneCount / progress.length) * 100);

  const figures: [string, string][] = [["Sale price", "purchase_price"], ["Buyer's deposit", "initial_deposit_amount"], ["Loan", "loan_amount"]];
  const shownFigs = figures.filter(([, k]) => fv(k) != null);
  const openTasks = ws.my_tasks.filter((t) => !isDone(t.status));

  return (
    <div className="sv">
      <div className={`sv-hero ${photo ? "has-photo" : ""}`}>
        <div className="sv-hero-photo" style={photo ? { backgroundImage: `url(${photo})` } : undefined} />
        <div className="sv-hero-scrim" />
        <div className="sv-hero-in">
          <div className="sv-eyebrow"><Icon name="key" size={13} /> Your sale</div>
          <h1 className="sv-addr">{prop?.address ?? "Your sale"}</h1>
          {coe?.due_date && (
            <div className="sv-hero-count">
              {nDays != null && nDays > 0 ? <>Closing in <b>{nDays}</b> days</> : nDays === 0 ? <>Closing today</> : <>Closed. Congratulations on your sale</>}
              <span className="sv-hero-date"> · {fmtDate(coe.due_date)}</span>
            </div>
          )}
        </div>
      </div>

      <div className="role-body sv-body">
        {/* signature: is the buyer on track? */}
        <div className="card sv-track">
          <h2><Icon name="flag" size={17} /> Is the buyer on track to close?</h2>
          <div className="sv-prog-head"><span className="mono-pct">{pct}%</span><span className="muted">to the finish line</span></div>
          <div className="sv-progbar"><div className="sv-progfill" style={{ width: `${pct}%` }} /></div>
          <div className="sv-steps">
            {progress.map((s, i) => (
              <div key={i} className={`sv-step ${s.done ? "done" : ""} ${i === activeIdx ? "on" : ""}`}>
                <span className="sv-step-dot">{s.done ? "✓" : ""}</span>
                <span className="sv-step-lbl">{s.label}</span>
                {s.date && <span className="sv-step-date muted">{dstamp(s.date)}</span>}
                {i === activeIdx && <span className="sv-step-now">in progress</span>}
              </div>
            ))}
          </div>
        </div>

        {shownFigs.length > 0 && (
          <div className="card">
            <h2><Icon name="receipt" size={17} /> Your sale</h2>
            <div className="mgrid">
              {shownFigs.map(([label, k]) => (
                <div key={k} className="mgrid-cell"><div className="mgrid-k">{label}</div><div className="mgrid-v">{fv(k)}</div></div>
              ))}
              {coe?.due_date && <div className="mgrid-cell"><div className="mgrid-k">Closing</div><div className="mgrid-v">{dstamp(coe.due_date)}</div></div>}
            </div>
          </div>
        )}

        {(prop?.included_items || prop?.excluded_items) && (
          <div className="card">
            <h2><Icon name="tag" size={17} /> Included in the sale</h2>
            {prop?.included_items && <p style={{ margin: "0 0 .4rem" }}><b>Stays:</b> {prop.included_items}</p>}
            {prop?.excluded_items && <p className="muted" style={{ margin: 0 }}><b>You keep:</b> {prop.excluded_items}</p>}
          </div>
        )}

        <div className="card">
          <h2><Icon name="checkCircle" size={17} /> What needs you</h2>
          {openTasks.length === 0 ? (
            <div className="role-clear"><span>✓</span> Nothing needs you right now.</div>
          ) : <div className="stack">{openTasks.map((t) => <TaskRow key={t.id} t={t} busy={busy} cycle={cycle} fmt={fmtDate} />)}</div>}
        </div>

        <div className="card">
          <h2><Icon name="users" size={17} /> Your team</h2>
          <div className="inv-roster">
            {ws.roster.map((p, i) => (
              <div key={i} className="inv-person">
                <div className="prow-ava" style={{ background: "#0e9488" }}>{initials(p.name, p.role)}</div>
                <div style={{ minWidth: 0 }}><div className="prow-name">{p.name ?? humanize(p.role)}</div><div className="prow-role">{humanize(p.role)}</div></div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h2><Icon name="doc" size={17} /> Deliver a document</h2>
          <p className="muted" style={{ margin: "-0.4rem 0 0.8rem" }}>Your disclosures, repair receipts, or HOA docs. Only your coordinator sees them.</p>
          <div className="inv-upload">
            <select value={docType} onChange={(e) => setDocType(e.target.value)} style={{ maxWidth: 240 }}>
              {DOCS.map((d, i) => <option key={i} value={d.v}>{d.label}</option>)}
            </select>
            <label className={`inv-uploadbtn ${busy ? "off" : ""}`}><Icon name="attach" size={14} /> Choose file…<input type="file" hidden disabled={busy} onChange={onFile} /></label>
          </div>
          {ws.my_documents.length > 0 && (
            <div className="stack" style={{ marginTop: ".8rem" }}>
              {ws.my_documents.map((d) => (
                <div key={d.id} className="inv-doc">
                  <div className="doc-ic sm" style={{ background: "#0e94881a", color: "#0e9488" }}><Icon name="doc" size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}><div className="doc-name">{humanize(d.doc_type ?? "document")}</div>{d.created_at && <div className="muted" style={{ fontSize: ".76rem" }}>Uploaded {fmtDate(d.created_at)}</div>}</div>
                  <span className="badge ok">{d.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <p className="inv-foot muted"><Icon name="lock" size={13} /> Personalized to your role and scoped to this sale.</p>
      </div>
    </div>
  );
}
