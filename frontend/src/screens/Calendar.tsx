import { useCallback, useEffect, useMemo, useState } from "react";
import { api, CalendarDeadline, OpenTask } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

const DAY_MS = 86_400_000;
const CAP_MIN = 120; // planning capacity per day (minutes) for auto-schedule
const SCHEDULE_KEY = "tc_cal_schedule";
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const dkey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const startOfToday = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
const addDays = (d: Date, n: number) => new Date(d.getTime() + n * DAY_MS);
const short = (a: string | null) => (a ?? "").split(",")[0];

// A rough time estimate per task so auto-schedule can pace the day.
function estMinutes(t: OpenTask): number {
  const s = t.title.toLowerCase();
  if (/walk-?through/.test(s)) return 60;
  if (/schedule|complete inspection|inspection/.test(s)) return 45;
  if (/coordinate|closing prep|handover/.test(s)) return 45;
  if (/confirm|verify|release|bind/.test(s)) return 15;
  return 30;
}
const fmtMin = (m: number) => (m >= 60 ? `${Math.round((m / 60) * 10) / 10}h` : `${m}m`);

export function Calendar({ onOpenDeal }: { onOpenDeal: (id: string) => void }) {
  const [deadlines, setDeadlines] = useState<CalendarDeadline[]>([]);
  const [tasks, setTasks] = useState<OpenTask[]>([]);
  const [cursor, setCursor] = useState(() => { const d = startOfToday(); d.setDate(1); return d; });
  const [drag, setDrag] = useState<string | null>(null);
  const [dropDay, setDropDay] = useState<string | null>(null);
  // taskId -> yyyy-mm-dd, persisted locally (no deadline-driving DB columns here)
  const [schedule, setSchedule] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem(SCHEDULE_KEY) ?? "{}"); } catch { return {}; }
  });
  useEffect(() => { localStorage.setItem(SCHEDULE_KEY, JSON.stringify(schedule)); }, [schedule]);

  const load = useCallback(async () => {
    try {
      const [c, t] = await Promise.all([
        api.get<CalendarDeadline[]>("/transactions/calendar"),
        api.get<OpenTask[]>("/transactions/tasks"),
      ]);
      setDeadlines(c);
      setTasks(t);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load calendar", { error: true });
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  // Drop stale scheduled ids (task got done/removed) so the queue stays honest.
  useEffect(() => {
    if (!tasks.length) return;
    const live = new Set(tasks.map((t) => t.id));
    setSchedule((s) => {
      const next = Object.fromEntries(Object.entries(s).filter(([id]) => live.has(id)));
      return Object.keys(next).length === Object.keys(s).length ? s : next;
    });
  }, [tasks]);

  const deadlinesByDay = useMemo(() => {
    const m: Record<string, CalendarDeadline[]> = {};
    for (const d of deadlines) (m[d.due_date] ??= []).push(d);
    return m;
  }, [deadlines]);

  const taskById = useMemo(() => Object.fromEntries(tasks.map((t) => [t.id, t])), [tasks]);
  const scheduledByDay = useMemo(() => {
    const m: Record<string, OpenTask[]> = {};
    for (const [id, day] of Object.entries(schedule)) {
      const t = taskById[id];
      if (t) (m[day] ??= []).push(t);
    }
    return m;
  }, [schedule, taskById]);
  const queue = useMemo(() => tasks.filter((t) => !schedule[t.id]), [tasks, schedule]);

  // 6-week grid starting on the Sunday on/before the 1st of the cursor month.
  const weeks = useMemo(() => {
    const first = new Date(cursor);
    const start = addDays(first, -first.getDay());
    return Array.from({ length: 6 }, (_, w) =>
      Array.from({ length: 7 }, (_, d) => addDays(start, w * 7 + d)),
    );
  }, [cursor]);

  const todayKey = dkey(startOfToday());

  function scheduleOn(taskId: string, day: string) {
    setSchedule((s) => ({ ...s, [taskId]: day }));
  }
  function unschedule(taskId: string) {
    setSchedule((s) => { const n = { ...s }; delete n[taskId]; return n; });
  }

  // Auto-plan: urgent-first, earliest day with remaining capacity up to the due
  // date (undated → within two weeks), so work is paced instead of piling up.
  function autoSchedule() {
    const today = startOfToday();
    const load: Record<string, number> = {};
    const next: Record<string, string> = {};
    const sorted = [...tasks].sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));
    for (const t of sorted) {
      const est = estMinutes(t);
      const due = t.due_date ? new Date(t.due_date + "T00:00:00") : null;
      const last = due && due > today ? due : addDays(today, 14);
      let placed: string | null = null;
      for (let d = new Date(today); d <= last; d = addDays(d, 1)) {
        const k = dkey(d);
        if ((load[k] ?? 0) + est <= CAP_MIN) { placed = k; break; }
      }
      if (!placed) placed = dkey(due && due > today ? due : today);
      load[placed] = (load[placed] ?? 0) + est;
      next[t.id] = placed;
    }
    setSchedule(next);
    toast(`Auto-scheduled ${sorted.length} task${sorted.length === 1 ? "" : "s"}`);
  }

  const monthLabel = cursor.toLocaleDateString("en-US", { month: "long", year: "numeric" });

  return (
    <div className="cal">
      <div className="page-head">
        <div>
          <h1>Calendar</h1>
          <div className="muted">Every deadline across your deals, plus a plan for your work queue.</div>
        </div>
        <div className="row" style={{ gap: "0.5rem", flex: "0 0 auto" }}>
          <button className="secondary" onClick={() => { const d = startOfToday(); d.setDate(1); setCursor(d); }}>Today</button>
          <button className="gold" onClick={autoSchedule} title="Place every open task onto the calendar by urgency, due date, and estimated time">
            <Icon name="sparkle" size={14} /> Auto-schedule
          </button>
        </div>
      </div>

      <div className="cal-grid">
        <div className="cal-main card">
          <div className="cal-toolbar">
            <button className="kbtn icon" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>‹</button>
            <b>{monthLabel}</b>
            <button className="kbtn icon" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>›</button>
            <span className="muted" style={{ marginLeft: "auto", fontSize: "0.78rem" }}>
              drag a task onto a day · {CAP_MIN / 60}h/day plan
            </span>
          </div>
          <div className="cal-dow">{WEEKDAYS.map((w) => <div key={w}>{w}</div>)}</div>
          <div className="cal-weeks">
            {weeks.map((wk, wi) => (
              <div key={wi} className="cal-week">
                {wk.map((day) => {
                  const k = dkey(day);
                  const inMonth = day.getMonth() === cursor.getMonth();
                  const dls = deadlinesByDay[k] ?? [];
                  const scheduled = scheduledByDay[k] ?? [];
                  return (
                    <div
                      key={k}
                      className={`cal-day ${inMonth ? "" : "off"} ${k === todayKey ? "today" : ""} ${dropDay === k ? "drop" : ""}`}
                      onDragOver={drag ? (e) => { e.preventDefault(); setDropDay(k); } : undefined}
                      onDragLeave={() => setDropDay((d) => (d === k ? null : d))}
                      onDrop={drag ? (e) => { e.preventDefault(); scheduleOn(drag, k); setDrag(null); setDropDay(null); } : undefined}
                    >
                      <div className="cal-dnum">{day.getDate()}</div>
                      {dls.map((d, i) => (
                        <div key={`d${i}`} className="cal-dl" title={`${d.name} · ${short(d.property_address)}`}
                          onClick={() => onOpenDeal(d.transaction_id)}>
                          <span className="cal-dot" /> {d.name.replace(/ (ends|due|delivery|delivered).*$/i, "")}
                        </div>
                      ))}
                      {scheduled.map((t) => (
                        <div
                          key={t.id}
                          className="cal-task"
                          draggable
                          onDragStart={() => setDrag(t.id)}
                          onDragEnd={() => { setDrag(null); setDropDay(null); }}
                          onClick={() => onOpenDeal(t.transaction_id)}
                          title={`${t.title} · ${short(t.property_address)} · ~${fmtMin(estMinutes(t))}`}
                        >
                          <span className="cal-task-t">{t.title}</span>
                          <span className="cal-task-m">{fmtMin(estMinutes(t))}</span>
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <aside
          className="cal-queue card"
          onDragOver={drag ? (e) => e.preventDefault() : undefined}
          onDrop={drag ? (e) => { e.preventDefault(); unschedule(drag); setDrag(null); } : undefined}
        >
          <div className="cal-qhead">
            <h2><Icon name="clipboard" size={16} /> Work queue</h2>
            <span className="muted">{queue.length} unscheduled</span>
          </div>
          <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 0.8rem" }}>
            Drag onto a day to plan it, or hit <b>Auto-schedule</b>. Drop back here to unschedule.
          </p>
          {queue.length === 0 ? (
            <div className="empty"><span className="empty-ic"><Icon name="checkCircle" size={24} /></span>Everything's on the calendar.</div>
          ) : (
            <div className="stack">
              {[...queue].sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999")).map((t) => {
                const n = t.due_date ? Math.round((new Date(t.due_date + "T00:00:00").getTime() - startOfToday().getTime()) / DAY_MS) : null;
                return (
                  <div key={t.id} className="cal-qtask" draggable onDragStart={() => setDrag(t.id)} onDragEnd={() => setDrag(null)}>
                    <span className="task-grip">⠿</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="cal-qt">{t.title}</div>
                      <div className="cal-qsub muted">
                        {short(t.property_address)} · ~{fmtMin(estMinutes(t))}
                        {t.due_date ? ` · due ${fmtDate(t.due_date).replace(/,\s*\d{4}$/, "")}${n != null && n < 0 ? " (overdue)" : ""}` : ""}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
