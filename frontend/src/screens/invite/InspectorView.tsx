import { fmtDate } from "../../lib/format";
import { Icon } from "../../lib/icons";
import { TaskRow, countdown, daysTo, humanize, isDone } from "./helpers";
import { RoleViewProps } from "./types";

const SUBTYPE: Record<string, { label: string; emoji: string; accent: string; docLabel: string }> = {
  inspector_termite: { label: "Termite / pest inspection", emoji: "🪳", accent: "#2f855a", docLabel: "Termite report" },
  inspector_general: { label: "Property inspection", emoji: "📋", accent: "#b8720f", docLabel: "Inspection report" },
  inspector_roof: { label: "Roof inspection", emoji: "🏠", accent: "#7a5230", docLabel: "Roof report" },
  inspector_sewer: { label: "Sewer / lateral inspection", emoji: "💧", accent: "#2563a8", docLabel: "Sewer report" },
};

/** Inspector's view — a focused field WORK-ORDER. The property + how to reach it,
 *  the deadline, and one job: do the inspection and upload the report. No money. */
export function InspectorView({ ws, busy, cycle, onFile }: RoleViewProps) {
  const role = ws.me.role;
  const sub = SUBTYPE[role] ?? { label: "Inspection", emoji: "📋", accent: "#b8720f", docLabel: "Inspection report" };
  const addr = ws.property?.address ?? null;
  const photo = ws.property?.photo_url ?? null;
  const maps = ws.property?.deep_links?.maps ?? (addr ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addr)}` : null);
  const due = ws.deadlines.find((d) => /inspection/i.test(d.name))?.due_date ?? null;
  const n = daysTo(due);
  const openTasks = ws.my_tasks.filter((t) => !isDone(t.status));
  const uploaded = ws.my_documents.length > 0;

  return (
    <div className="iw" style={{ ["--iw-accent" as string]: sub.accent }}>
      {/* the job ticket */}
      <div className="iw-ticket">
        <div className="iw-ticket-l">
          <div className="iw-eyebrow"><span className="iw-emoji">{sub.emoji}</span> Your inspection</div>
          <h1 className="iw-title">{sub.label}</h1>
          <div className="iw-addr"><Icon name="pin" size={15} /> {addr ?? "the property"}</div>
          {maps && <a className="iw-map" href={maps} target="_blank" rel="noreferrer"><Icon name="external" size={13} /> Open in Google Maps</a>}
        </div>
        <div className="iw-ticket-r">
          {due ? (
            <div className={`iw-due ${n != null && n <= 2 ? "soon" : ""}`}>
              <b>{countdown(n)}</b><span>{n != null && n < 0 ? "overdue" : "to inspect"}</span>
              <small className="mono">{fmtDate(due)}</small>
            </div>
          ) : <div className="iw-due"><b>—</b><span>no date set</span></div>}
        </div>
      </div>

      {photo && <div className="iw-photo" style={{ backgroundImage: `url(${photo})` }} aria-label="the property" />}

      <div className="role-body iw-body">
        {/* one big action */}
        <div className={`iw-action ${uploaded ? "has" : ""}`}>
          <div className="iw-action-h">{uploaded ? "Report received — thank you" : "Upload your report"}</div>
          <p className="iw-action-p">{uploaded ? "Your coordinator has your report and takes it from here. You can add another file if needed." : `When your ${sub.label.toLowerCase()} is complete, upload the report — that's all we need from you.`}</p>
          <label className={`iw-drop ${busy ? "off" : ""}`}>
            <span className="iw-drop-ic"><Icon name="attach" size={26} /></span>
            <span className="iw-drop-t">{busy ? "Uploading…" : `Choose your ${sub.docLabel.toLowerCase()}`}</span>
            <span className="iw-drop-s">PDF · only your coordinator sees it</span>
            <input type="file" hidden disabled={busy} onChange={onFile} />
          </label>
          {uploaded && (
            <div className="stack" style={{ marginTop: "1rem" }}>
              {ws.my_documents.map((d) => (
                <div key={d.id} className="inv-doc">
                  <div className="doc-ic sm" style={{ background: `${sub.accent}1a`, color: sub.accent }}><Icon name="doc" size={16} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}><div className="doc-name">{humanize(d.doc_type ?? "report")}</div>{d.created_at && <div className="muted" style={{ fontSize: ".76rem" }}>Uploaded {fmtDate(d.created_at)}</div>}</div>
                  <span className="badge ok">{d.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {openTasks.length > 0 && (
          <div className="card">
            <h2><Icon name="checkCircle" size={17} /> Your task</h2>
            <div className="stack">{openTasks.map((t) => <TaskRow key={t.id} t={t} busy={busy} cycle={cycle} fmt={fmtDate} />)}</div>
          </div>
        )}
        <p className="inv-foot muted"><Icon name="lock" size={13} /> Scoped to your inspection on this property — you don't see the deal's price, parties, or other transactions.</p>
      </div>
    </div>
  );
}
