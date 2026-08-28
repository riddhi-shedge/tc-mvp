import { fmtDate } from "../../lib/format";
import { Icon } from "../../lib/icons";
import { TaskRow, countdown, daysTo, humanize, initials, isDone } from "./helpers";
import { RoleViewProps } from "./types";

const DOCS = [
  { v: "counter_offer", label: "Counter offer" },
  { v: "disclosure", label: "Disclosure" },
  { v: "other", label: "Addendum" },
  { v: "other", label: "Other document" },
];
const dstamp = (iso: string) => fmtDate(iso).replace(/,\s*\d{4}$/, "");
const STAGE_LABEL: Record<string, string> = { new: "New offer", cont: "Contingency period", closing: "Closing", closed: "Closed" };

/** Agent / broker's view — a command DECK. The full deal at a glance: figures,
 *  timeline, parties, their tasks, and their side's documents to upload. */
export function AgentView({ ws, busy, docType, setDocType, cycle, onFile }: RoleViewProps) {
  const fv = (k: string) => ws.fields[k];
  const coe = ws.deadlines.find((d) => /escrow|clos/i.test(d.name)) ?? null;
  const summary: [string, string | null][] = [
    ["Price", fv("purchase_price") ?? null],
    ["Close", coe ? dstamp(coe.due_date) : null],
    ["Loan", fv("loan_amount") ?? null],
    ["Stage", ws.stage ? STAGE_LABEL[ws.stage] ?? ws.stage : null],
  ];
  const shownSummary = summary.filter(([, v]) => v != null);
  const openTasks = ws.my_tasks.filter((t) => !isDone(t.status));

  return (
    <div className="av">
      <div className="av-head">
        <div>
          <div className="av-eyebrow"><Icon name="contract" size={13} /> Deal cockpit · {humanize(ws.me.role)}</div>
          <h1 className="av-title">{ws.property?.address ?? "Your deal"}</h1>
        </div>
      </div>

      <div className="role-body av-body">
        <div className="av-summary">
          {shownSummary.map(([k, v]) => (
            <div key={k} className="av-sum"><div className="av-sum-k">{k}</div><div className="av-sum-v">{v}</div></div>
          ))}
        </div>

        <div className="av-cols">
          <div className="card">
            <h2><Icon name="calendar" size={17} /> Timeline</h2>
            {ws.deadlines.length === 0 ? (
              <div className="role-clear"><span>—</span> No dated milestones yet.</div>
            ) : (
              <div className="stack">
                {[...ws.deadlines].sort((a, b) => a.due_date.localeCompare(b.due_date)).map((d, i) => {
                  const n = daysTo(d.due_date);
                  return (
                    <div key={i} className="av-dl">
                      <span className="av-dl-date mono">{dstamp(d.due_date)}</span>
                      <span className="av-dl-name">{d.name}</span>
                      <span className={`pill-${n != null && n <= 2 ? "red" : n != null && n <= 7 ? "amber" : "plain"}`}>{countdown(n)}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="card">
            <h2><Icon name="users" size={17} /> Parties</h2>
            <div className="av-parties">
              {ws.roster.map((p, i) => (
                <div key={i} className="av-party">
                  <div className="av-party-ava" style={{ background: "#c07512" }}>{initials(p.name, p.role)}</div>
                  <div style={{ minWidth: 0 }}><div className="prow-name">{p.name ?? humanize(p.role)}</div><div className="prow-role">{humanize(p.role)}</div></div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <h2><Icon name="checkCircle" size={17} /> Your tasks</h2>
          {openTasks.length === 0 ? (
            <div className="role-clear"><span>✓</span> Nothing needs you right now.</div>
          ) : <div className="stack">{openTasks.map((t) => <TaskRow key={t.id} t={t} busy={busy} cycle={cycle} fmt={fmtDate} />)}</div>}
        </div>

        <div className="card">
          <h2><Icon name="doc" size={17} /> Upload a document</h2>
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
                  <div className="doc-ic sm" style={{ background: "#c075121a", color: "#c07512" }}><Icon name="doc" size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}><div className="doc-name">{humanize(d.doc_type ?? "document")}</div>{d.created_at && <div className="muted" style={{ fontSize: ".76rem" }}>Uploaded {fmtDate(d.created_at)}</div>}</div>
                  <span className="badge ok">{d.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <p className="inv-foot muted"><Icon name="lock" size={13} /> A read-only view of your deal — you complete your own tasks and upload your side's documents.</p>
      </div>
    </div>
  );
}
