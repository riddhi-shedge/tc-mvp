import { fmtDate } from "../../lib/format";
import { Icon } from "../../lib/icons";
import { TaskRow, daysTo, humanize, initials, isDone, useCountUp } from "./helpers";
import { RoleViewProps } from "./types";

const DOCS = [
  { v: "other", label: "Escrow instructions" },
  { v: "other", label: "Estimated closing statement" },
  { v: "other", label: "Amendment" },
  { v: "preliminary_report", label: "Preliminary title report" },
  { v: "other", label: "Other document" },
];
const dstamp = (iso: string) => fmtDate(iso).replace(/,\s*\d{4}$/, "");

/** Escrow officer's view — a precise closing FILE. A readiness gauge, the closing
 *  figures (no wiring — Rule 5), a conditions checklist, and who to coordinate. */
export function EscrowView({ ws, busy, docType, setDocType, cycle, onFile }: RoleViewProps) {
  const fv = (k: string) => ws.fields[k];
  const find = (re: RegExp) => ws.deadlines.find((d) => re.test(d.name)) ?? null;
  const coe = find(/escrow|clos/i);
  const past = (iso?: string | null) => (daysTo(iso ?? null) ?? 1) < 0;

  // These rows track the CONTRACT CLOCK, not confirmed facts: "done" means the
  // deadline date has passed, nothing more. The labels must say exactly that.
  const conditions = [
    { label: "Deposit deadline", date: find(/earnest|deposit|emd/i)?.due_date ?? null, done: past(find(/earnest|deposit|emd/i)?.due_date) },
    { label: "Inspection contingency deadline", date: find(/inspection/i)?.due_date ?? null, done: past(find(/inspection/i)?.due_date) },
    { label: "Appraisal contingency deadline", date: find(/appraisal/i)?.due_date ?? null, done: past(find(/appraisal/i)?.due_date) },
    { label: "Loan contingency deadline", date: find(/loan/i)?.due_date ?? null, done: past(find(/loan/i)?.due_date) },
    { label: "Close of escrow", date: coe?.due_date ?? null, done: past(coe?.due_date) },
  ];
  const doneCount = conditions.filter((c) => c.done).length;
  const pct = Math.round((doneCount / conditions.length) * 100);
  const shownPct = useCountUp(pct, 900);

  const figures: [string, string][] = [["Purchase price", "purchase_price"], ["Earnest money", "initial_deposit_amount"], ["Loan amount", "loan_amount"]];
  const shownFigs = figures.filter(([, k]) => fv(k) != null);
  const openTasks = ws.my_tasks.filter((t) => !isDone(t.status));

  return (
    <div className="ev">
      <div className="ev-head">
        <div className="ev-eyebrow"><Icon name="bank" size={13} /> Escrow file</div>
        <h1 className="ev-addr">{ws.property?.address ?? "Escrow file"}</h1>
        <div className="ev-meta mono">
          {coe?.due_date && <span>CLOSE · {dstamp(coe.due_date)}</span>}
          {fv("apn") && <span>APN · {fv("apn")}</span>}
        </div>
      </div>

      <div className="role-body ev-body">
        {/* signature: closing readiness gauge + conditions */}
        <div className="card ev-ready">
          <div className="ev-gauge" style={{ background: `conic-gradient(#2c6b50 ${shownPct * 3.6}deg, var(--line) 0)` }}>
            <div className="ev-gauge-in"><b>{shownPct}%</b><span>of dates passed</span></div>
          </div>
          <div className="ev-cond">
            <h2 style={{ margin: "0 0 .6rem" }}><Icon name="clipboard" size={17} /> Contract clock</h2>
            <p className="muted" style={{ margin: "0 0 .5rem", fontSize: ".78rem" }}>
              Deadline dates from the contract. A check means the date has passed, not
              that the item is confirmed complete.
            </p>
            {conditions.map((c, i) => (
              <div key={i} className={`ev-cond-row ${c.done ? "done" : ""}`}>
                <span className="ev-cond-box">{c.done ? "✓" : ""}</span>
                <span className="ev-cond-lbl">{c.label}</span>
                {c.date && <span className="ev-cond-date mono">{dstamp(c.date)}</span>}
              </div>
            ))}
          </div>
        </div>

        {shownFigs.length > 0 && (
          <div className="card">
            <h2><Icon name="receipt" size={17} /> Closing figures</h2>
            <div className="ev-figs">
              {shownFigs.map(([label, k]) => (
                <div key={k} className="ev-fig"><span className="ev-fig-k">{label}</span><span className="ev-fig-v mono">{fv(k)}</span></div>
              ))}
              {coe?.due_date && <div className="ev-fig"><span className="ev-fig-k">Close of escrow</span><span className="ev-fig-v mono">{fmtDate(coe.due_date)}</span></div>}
            </div>
            <p className="muted" style={{ margin: ".7rem 0 0", fontSize: ".8rem" }}><Icon name="lock" size={12} /> Wiring and payment details are never shown here.</p>
          </div>
        )}

        <div className="card">
          <h2><Icon name="users" size={17} /> Parties to coordinate</h2>
          <div className="ev-parties">
            {ws.roster.map((p, i) => (
              <div key={i} className="ev-party">
                <div className="ev-party-ava">{initials(p.name, p.role)}</div>
                <div style={{ minWidth: 0 }}><div className="prow-name">{p.name ?? humanize(p.role)}</div><div className="prow-role">{humanize(p.role)}</div></div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h2><Icon name="checkCircle" size={17} /> Your items</h2>
          {openTasks.length === 0 ? (
            <div className="role-clear"><span>✓</span> Nothing outstanding on your side.</div>
          ) : <div className="stack">{openTasks.map((t) => <TaskRow key={t.id} t={t} busy={busy} cycle={cycle} fmt={fmtDate} />)}</div>}
        </div>

        <div className="card">
          <h2><Icon name="doc" size={17} /> Upload escrow documents</h2>
          <div className="inv-upload">
            <select value={docType} onChange={(e) => setDocType(e.target.value)} style={{ maxWidth: 260 }}>
              {DOCS.map((d, i) => <option key={i} value={d.v}>{d.label}</option>)}
            </select>
            <label className={`inv-uploadbtn ${busy ? "off" : ""}`}><Icon name="attach" size={14} /> Choose file…<input type="file" hidden disabled={busy} onChange={onFile} /></label>
          </div>
          {ws.my_documents.length > 0 && (
            <div className="stack" style={{ marginTop: ".8rem" }}>
              {ws.my_documents.map((d) => (
                <div key={d.id} className="inv-doc">
                  <div className="doc-ic sm" style={{ background: "#4f5a6a1a", color: "#4f5a6a" }}><Icon name="doc" size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}><div className="doc-name">{humanize(d.doc_type ?? "document")}</div>{d.created_at && <div className="muted" style={{ fontSize: ".76rem" }}>Uploaded {fmtDate(d.created_at)}</div>}</div>
                  <span className="badge ok">{d.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <p className="inv-foot muted"><Icon name="lock" size={13} /> Scoped to this file. No wiring data is stored, and messages require the coordinator's approval.</p>
      </div>
    </div>
  );
}
