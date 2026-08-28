import { useEffect, useState } from "react";
import { Icon } from "../../lib/icons";
import { Task } from "./types";

export const DAY = 86_400_000;
export const humanize = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
export const isDone = (s: string) => s === "done" || s === "complete";
export const TASK_NEXT: Record<string, string> = { pending: "in_progress", in_progress: "done", done: "pending" };

export function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso + "T00:00:00").getTime();
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.round((t - now.getTime()) / DAY);
}
export const countdown = (n: number | null) => (n == null ? "—" : n < 0 ? `${-n}d ago` : n === 0 ? "today" : `${n}d`);
export function initials(name: string | null, role: string) {
  const s = (name || role || "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** Ease a number from 0 → target on mount (respects reduced motion). */
export function useCountUp(target: number | null, dur = 950): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (target == null) { setV(0); return; }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { setV(target); return; }
    let raf = 0; const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / dur);
      setV(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, dur]);
  return v;
}

/** A shared task row (checkbox cycles pending → in-progress → done). */
export function TaskRow({ t, busy, cycle, fmt }: { t: Task; busy: boolean; cycle: (t: Task) => void; fmt: (d: string) => string }) {
  const done = isDone(t.status);
  const inProg = t.status === "in_progress";
  return (
    <div className={`task-row ${done ? "done" : ""} ${inProg ? "doing" : ""}`}>
      <button className={`task-check ${done ? "done" : ""} ${inProg ? "doing" : ""}`} disabled={busy} onClick={() => cycle(t)}>
        {done ? "✓" : inProg ? "◐" : ""}
      </button>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="task-title">{t.title}</div>
        {t.due_date && <div className="task-meta muted"><Icon name="calendar" size={12} /> {fmt(t.due_date)}</div>}
      </div>
    </div>
  );
}
