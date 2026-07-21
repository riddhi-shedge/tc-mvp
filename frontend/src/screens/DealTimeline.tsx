import { Deadline } from "../lib/api";

/** A horizontal, date-proportional deal timeline: Acceptance → Close of Escrow,
 *  every deadline plotted by its real date, a live "today" line, and urgency
 *  color. The signature at-a-glance view for the deal. */
export function DealTimeline({
  deadlines,
  acceptanceDate,
}: {
  deadlines: Deadline[];
  acceptanceDate: string | null;
}) {
  function shortName(name: string): string {
    return name
      .replace(/ (ends|due|delivery|contingency|\(.*\))/gi, "")
      .replace(/Close of escrow/i, "COE")
      .trim();
  }

  // Group deadlines that share a date (e.g. inspection/appraisal/insurance all
  // land on the same day) into one marker so flags don't stack.
  const byDate = new Map<string, { t: number; names: string[]; id: string }>();
  for (const d of deadlines) {
    const t = Date.parse(d.due_date);
    if (Number.isNaN(t)) continue;
    const g = byDate.get(d.due_date) ?? { t, names: [], id: d.id };
    g.names.push(shortName(d.name));
    byDate.set(d.due_date, g);
  }
  const dated = [...byDate.values()].sort((a, b) => a.t - b.t);

  if (dated.length === 0) {
    return (
      <div className="card">
        <h2>◷ Timeline</h2>
        <div className="empty">
          <span className="emoji">🗓️</span>
          No deadlines computed yet — confirm the extracted fields to build the timeline.
        </div>
      </div>
    );
  }

  const acc = acceptanceDate ? Date.parse(acceptanceDate) : NaN;
  const start = !Number.isNaN(acc) ? Math.min(acc, dated[0].t) : dated[0].t;
  const end = dated[dated.length - 1].t;
  const span = Math.max(end - start, 86_400_000);
  const now = Date.now();
  const pct = (t: number) => Math.max(0, Math.min(100, ((t - start) / span) * 100));
  const todayPct = pct(now);
  const showToday = now >= start && now <= end;

  const dayMs = 86_400_000;
  function urgency(t: number): "overdue" | "danger" | "warn" | "ok" {
    const days = Math.round((t - now) / dayMs);
    if (days < 0) return "overdue";
    if (days <= 3) return "danger";
    if (days <= 10) return "warn";
    return "ok";
  }

  return (
    <div className="card timeline-card">
      <div className="between" style={{ marginBottom: "1.1rem" }}>
        <h2 style={{ margin: 0 }}>◷ Deal timeline</h2>
        <span className="muted">Acceptance → Close of Escrow</span>
      </div>

      <div className="tl">
        <div className="tl-track" />
        <div
          className="tl-progress"
          style={{ width: `${showToday ? todayPct : now > end ? 100 : 0}%` }}
        />
        {showToday && (
          <div className="tl-today" style={{ left: `${todayPct}%` }}>
            <span className="tl-today-label">Today</span>
          </div>
        )}

        {dated.map((d, i) => {
          const u = urgency(d.t);
          const above = i % 2 === 0;
          const days = Math.round((d.t - now) / dayMs);
          return (
            <div
              key={d.id}
              className={`tl-marker ${above ? "above" : "below"}`}
              style={{ left: `${pct(d.t)}%` }}
            >
              <span className={`tl-dot ${u}`} />
              <div className="tl-flag">
                <div className="tl-flag-name">
                  {d.names.slice(0, 2).join(", ")}
                  {d.names.length > 2 ? ` +${d.names.length - 2}` : ""}
                </div>
                <div className="tl-flag-date">
                  {new Date(d.t).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  <span className={`tl-days ${u}`}>
                    {days < 0 ? `${-days}d ago` : days === 0 ? "today" : `${days}d`}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="tl-legend">
        <span><span className="tl-dot ok" /> on track</span>
        <span><span className="tl-dot warn" /> approaching</span>
        <span><span className="tl-dot danger" /> imminent</span>
        <span><span className="tl-dot overdue" /> passed</span>
      </div>
    </div>
  );
}
