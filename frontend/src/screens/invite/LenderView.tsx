import { fmtDate } from "../../lib/format";
import { Icon } from "../../lib/icons";
import { TaskRow, daysTo, humanize, isDone, useCountUp } from "./helpers";
import { RoleViewProps } from "./types";

const DOCS = [
  { v: "preapproval", label: "Preapproval / underwriter letter" },
  { v: "other", label: "Closing disclosure" },
  { v: "proof_of_funds", label: "Proof of funds" },
  { v: "other", label: "Other loan document" },
];
const dstamp = (iso: string) => fmtDate(iso).replace(/,\s*\d{4}$/, "");
const money = (s?: string) => {
  const m = (s || "").match(/[\d,]+(?:\.\d+)?/);
  return m ? parseFloat(m[0].replace(/,/g, "")) : null;
};

/** Lender / loan officer's view — a loan COCKPIT. An LTV gauge, the loan figures,
 *  borrower, the conditions to clear, and their loan documents to upload. */
export function LenderView({ ws, busy, docType, setDocType, cycle, onFile }: RoleViewProps) {
  const fv = (k: string) => ws.fields[k];
  const find = (re: RegExp) => ws.deadlines.find((d) => re.test(d.name)) ?? null;
  const loan = money(fv("loan_amount"));
  const price = money(fv("purchase_price"));
  const ltv = loan && price ? Math.min(100, Math.round((loan / price) * 100)) : null;
  const shownLtv = useCountUp(ltv, 900);
  const past = (iso?: string | null) => (daysTo(iso ?? null) ?? 1) < 0;

  const conditions = [
    { label: "Appraisal contingency", date: find(/appraisal/i)?.due_date ?? null, done: past(find(/appraisal/i)?.due_date) },
    { label: "Loan contingency", date: find(/loan/i)?.due_date ?? null, done: past(find(/loan/i)?.due_date) },
    { label: "Clear to close", date: find(/escrow|clos/i)?.due_date ?? null, done: past(find(/escrow|clos/i)?.due_date) },
  ];
  const figs: [string, string][] = [["Loan amount", "loan_amount"], ["Purchase price", "purchase_price"], ["Down payment", "down_payment"]];
  const shownFigs = figs.filter(([, k]) => fv(k) != null);
  const openTasks = ws.my_tasks.filter((t) => !isDone(t.status));

  return (
    <div className="lv">
      <div className="lv-head">
        <div className="lv-eyebrow"><Icon name="money" size={13} /> Loan file</div>
        <h1 className="lv-title">{fv("buyer_names") ?? "Loan file"}</h1>
        <div className="lv-sub muted">{ws.property?.address ?? ""}</div>
      </div>

      <div className="role-body lv-body">
        <div className="card lv-top">
          {ltv != null && (
            <div className="lv-gauge" style={{ background: `conic-gradient(#2563a8 ${shownLtv * 3.6}deg, var(--line) 0)` }}>
              <div className="lv-gauge-in"><b>{shownLtv}%</b><span>LTV</span></div>
            </div>
          )}
          <div className="lv-figs">
            {shownFigs.map(([label, k]) => (
              <div key={k} className="lv-fig"><span className="lv-fig-k">{label}</span><span className="lv-fig-v mono">{fv(k)}</span></div>
            ))}
          </div>
        </div>

        <div className="card">
          <h2><Icon name="clipboard" size={17} /> Conditions to clear</h2>
          {conditions.map((c, i) => (
            <div key={i} className={`lv-cond ${c.done ? "done" : ""}`}>
              <span className="lv-cond-box">{c.done ? "✓" : ""}</span>
              <span className="lv-cond-lbl">{c.label}</span>
              {c.date && <span className="mono lv-cond-date">{dstamp(c.date)}</span>}
            </div>
          ))}
        </div>

        <div className="card">
          <h2><Icon name="checkCircle" size={17} /> Your items</h2>
          {openTasks.length === 0 ? (
            <div className="role-clear"><span>✓</span> Nothing outstanding on your side.</div>
          ) : <div className="stack">{openTasks.map((t) => <TaskRow key={t.id} t={t} busy={busy} cycle={cycle} fmt={fmtDate} />)}</div>}
        </div>

        <div className="card">
          <h2><Icon name="doc" size={17} /> Upload loan documents</h2>
          <div className="inv-upload">
            <select value={docType} onChange={(e) => setDocType(e.target.value)} style={{ maxWidth: 280 }}>
              {DOCS.map((d, i) => <option key={i} value={d.v}>{d.label}</option>)}
            </select>
            <label className={`inv-uploadbtn ${busy ? "off" : ""}`}><Icon name="attach" size={14} /> Choose file…<input type="file" hidden disabled={busy} onChange={onFile} /></label>
          </div>
          {ws.my_documents.length > 0 && (
            <div className="stack" style={{ marginTop: ".8rem" }}>
              {ws.my_documents.map((d) => (
                <div key={d.id} className="inv-doc">
                  <div className="doc-ic sm" style={{ background: "#2563a81a", color: "#2563a8" }}><Icon name="doc" size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}><div className="doc-name">{humanize(d.doc_type ?? "document")}</div>{d.created_at && <div className="muted" style={{ fontSize: ".76rem" }}>Uploaded {fmtDate(d.created_at)}</div>}</div>
                  <span className="badge ok">{d.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <p className="inv-foot muted"><Icon name="lock" size={13} /> Scoped to this loan — no wiring data, and drafts never send without the coordinator's approval.</p>
      </div>
    </div>
  );
}
