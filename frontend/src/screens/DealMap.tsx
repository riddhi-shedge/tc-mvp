import { useMemo } from "react";
import { Deadline, DealDocument, DealRiskFlag, Task } from "../lib/api";
import { fmtDate } from "../lib/format";
import { Icon } from "../lib/icons";

/* The Deal Map — a multi-lane operational timeline for one transaction. Lanes for
 * contractual deadlines (fixed), tasks, documents and risks/AI, laid out along a
 * real date axis computed from the deal's own dates. Fixed contract dates read
 * differently from flexible work. Everything here is the deal's real data. */

const WEEK = 7 * 86_400_000;
const t0 = (iso: string) => new Date(iso + (iso.length <= 10 ? "T00:00:00" : "")).getTime();
const dayFloor = (ms: number) => {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
};

type Ev = { at: number; label: string; kind: "fixed" | "task" | "doc" | "risk" };

export function DealMap({
  deadlines,
  tasks,
  documents,
  riskFlags,
}: {
  deadlines: Deadline[];
  tasks: Task[];
  documents: DealDocument[];
  riskFlags: DealRiskFlag[];
}) {
  const model = useMemo(() => {
    const today = dayFloor(Date.now());
    const evsByLane: Record<string, Ev[]> = { Deadlines: [], Tasks: [], Documents: [], "Risks · AI": [] };

    for (const d of deadlines) {
      evsByLane.Deadlines.push({ at: t0(d.due_date), label: d.name.replace(/ (ends|due|delivery).*$/i, ""), kind: "fixed" });
    }
    for (const t of tasks) {
      if (t.due_date) evsByLane.Tasks.push({ at: t0(t.due_date), label: t.title, kind: "task" });
    }
    for (const doc of documents) {
      if (doc.created_at) evsByLane.Documents.push({ at: t0(doc.created_at), label: doc.doc_type ?? "Document", kind: "doc" });
    }
    for (const r of riskFlags.filter((r) => !r.resolved)) {
      evsByLane["Risks · AI"].push({ at: today, label: r.description.slice(0, 40), kind: "risk" });
    }

    const all = Object.values(evsByLane).flat().map((e) => e.at);
    if (all.length === 0) return null;
    let start = dayFloor(Math.min(today, ...all));
    let end = dayFloor(Math.max(today, ...all));
    // Snap start back to a Sunday and pad the end by a week for breathing room.
    start = start - ((new Date(start).getDay()) * 86_400_000);
    end = end + WEEK;
    const span = Math.max(WEEK, end - start);
    const weeks: number[] = [];
    for (let w = start; w <= end; w += WEEK) weeks.push(w);
    const pct = (ms: number) => Math.max(0, Math.min(100, ((ms - start) / span) * 100));

    return { evsByLane, weeks, pct, start, span, todayPct: pct(today) };
  }, [deadlines, tasks, documents, riskFlags]);

  if (!model) {
    return (
      <div className="card">
        <div className="empty">
          <span className="empty-ic"><Icon name="calendar" size={26} /></span>
          The Deal Map appears once the timeline is built and dates are on file.
        </div>
      </div>
    );
  }

  const laneIcon: Record<string, "calendar" | "check" | "doc" | "warning"> = {
    Deadlines: "calendar", Tasks: "check", Documents: "doc", "Risks · AI": "warning",
  };

  return (
    <>
      <div className="dm-ctl">
        <span className="dm-legend"><span className="dm-dot fixed" /> Contractual (fixed)</span>
        <span className="dm-legend"><span className="dm-dot task" /> Flexible work</span>
        <span className="dm-legend"><span className="dm-dot doc" /> Document</span>
        <span className="dm-legend"><span className="dm-dot risk" /> Risk / AI</span>
      </div>
      <div className="dm-wrap">
        <div className="dm-scroll">
          <div className="dm-inner" style={{ minWidth: Math.max(760, model.weeks.length * 96) }}>
            <div className="dm-axis">
              <div className="dm-gut" />
              <div className="dm-track">
                {model.weeks.map((w, i) => (
                  <div key={i} className="dm-wk" style={{ left: `${model.pct(w)}%` }}>{fmtDate(new Date(w).toISOString()).replace(/,\s*\d{4}$/, "")}</div>
                ))}
              </div>
            </div>
            {Object.entries(model.evsByLane).map(([lane, evs]) => (
              <div key={lane} className="dm-lane">
                <div className="dm-glab"><Icon name={laneIcon[lane]} size={13} /> {lane}</div>
                <div className="dm-lane-track">
                  {model.weeks.map((w, i) => (
                    <span key={i} className="dm-grid" style={{ left: `${model.pct(w)}%` }} />
                  ))}
                  <span className="dm-now" style={{ left: `${model.todayPct}%` }} />
                  {evs.length === 0 && <span className="dm-empty-lane">—</span>}
                  {evs.map((e, i) => (
                    <span
                      key={i}
                      className={`dm-ev ${e.kind}`}
                      style={{ left: `${model.pct(e.at)}%` }}
                      title={`${e.label} · ${fmtDate(new Date(e.at).toISOString())}`}
                    >
                      {e.label}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
