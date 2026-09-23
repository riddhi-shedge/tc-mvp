/** P-D: the deadline runway — time as space. The next 10 business days as
 *  columns (today widest, weekends compressed to slivers), deadline chips
 *  stacked in their day, anything overdue folded into today's column. Read-only:
 *  deadlines are SOR-owned facts; chips never look editable. Weekend-only
 *  compression client-side — CA legal holidays live in the compliance service
 *  and are not marked here (flagged in docs/ui-redesign.md). */

export type RunwayItem = { name: string; due_date: string; tag?: string | null };

const iso = (d: Date) => {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0"), dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
};

export function Runway({ items, maxPerDay = 3 }: { items: RunwayItem[]; maxPerDay?: number }) {
  const cols: { key: string; label: string; today?: boolean; gap?: boolean; chips: { text: string; cls: string; title: string }[] }[] = [];
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const todayIso = iso(d);
  let biz = 0;
  while (biz < 10) {
    const day = iso(d);
    const dow = d.getDay();
    if (dow === 0 || dow === 6) {
      if (!cols[cols.length - 1]?.gap) cols.push({ key: `gap-${day}`, label: "", gap: true, chips: [] });
    } else {
      const today = biz === 0;
      const due = items.filter((x) => x.due_date === day);
      const overdue = today ? items.filter((x) => x.due_date < todayIso) : [];
      const chips = [
        ...overdue.map((x) => ({ text: x.tag ? `${x.tag} · ${x.name}` : x.name, cls: "overdue", title: `${x.name} · overdue (${x.due_date})${x.tag ? ` · ${x.tag}` : ""}` })),
        ...due.map((x) => ({ text: x.tag ? `${x.tag} · ${x.name}` : x.name, cls: today ? "today" : biz <= 3 ? "soon" : "later", title: `${x.name} · ${x.due_date}${x.tag ? ` · ${x.tag}` : ""}` })),
      ];
      cols.push({
        key: day, today,
        label: today ? "Today" : `${d.toLocaleDateString("en-US", { weekday: "short" }).slice(0, 2)} ${d.getDate()}`,
        chips,
      });
      biz++;
    }
    d.setDate(d.getDate() + 1);
  }
  return (
    <div className="rw" role="img" aria-label="Deadline runway, next ten business days">
      {cols.map((c) =>
        c.gap ? (
          <div key={c.key} className="rw-gap" />
        ) : (
          <div key={c.key} className={`rw-day ${c.today ? "today" : ""}`}>
            <div className="rw-d">{c.label}</div>
            {c.chips.slice(0, maxPerDay).map((ch, i) => (
              <div key={i} className={`rw-chip ${ch.cls}`} title={ch.title}>{ch.text}</div>
            ))}
            {c.chips.length > maxPerDay && <div className="rw-more">+{c.chips.length - maxPerDay}</div>}
          </div>
        ),
      )}
    </div>
  );
}
