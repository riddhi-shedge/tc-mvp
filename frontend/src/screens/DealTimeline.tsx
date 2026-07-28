import { CSSProperties, useEffect, useState } from "react";
import { api, Deadline, Task } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon, IconName } from "../lib/icons";

const DAY = 86_400_000;

function iconFor(name: string): IconName {
  const s = name.toLowerCase();
  if (s.includes("acceptance")) return "flag";
  if (s.includes("earnest") || s.includes("deposit") || s.includes("emd")) return "pin";
  if (s.includes("disclosure")) return "clipboard";
  if (s.includes("inspection")) return "search";
  if (s.includes("appraisal")) return "tag";
  if (s.includes("loan")) return "bank";
  if (s.includes("insurance")) return "shield";
  if (s.includes("verification") || s.includes("funds")) return "money";
  if (s.includes("walk")) return "user";
  if (s.includes("escrow") || s.includes("closing")) return "key";
  if (s.includes("possession")) return "key";
  return "flag";
}
function shortName(name: string): string {
  return name
    .replace(/ (ends|due|delivery|contingency|\(.*\))/gi, "")
    .replace(/Close of escrow/i, "Close of escrow")
    .trim();
}
const isDone = (t: Task) => t.status === "done" || t.status === "complete";

type Milestone = {
  key: string;
  t: number;
  dateIso: string;
  names: string[];
  deadlineIds: string[];
  anchor: boolean;
  isCoe: boolean;
};

/** The "deal runway": a proportional timeline (Acceptance → Close of Escrow) with
 *  phase bands, icon milestones that show done/next/upcoming state, a live pulsing
 *  "today", a draw-in on load, and hover-for-task actions. */
export function DealTimeline({
  id,
  deadlines,
  tasks,
  acceptanceDate,
  onChanged,
}: {
  id: string;
  deadlines: Deadline[];
  tasks: Task[];
  acceptanceDate: string | null;
  onChanged: () => void;
}) {
  const [played, setPlayed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const r = requestAnimationFrame(() => requestAnimationFrame(() => setPlayed(true)));
    return () => cancelAnimationFrame(r);
  }, []);

  // group deadlines that share a date into one milestone
  const byDate = new Map<string, Milestone>();
  for (const d of deadlines) {
    const t = Date.parse(d.due_date);
    if (Number.isNaN(t)) continue;
    const g = byDate.get(d.due_date) ?? {
      key: d.due_date, t, dateIso: d.due_date, names: [], deadlineIds: [], anchor: false,
      isCoe: false,
    };
    g.names.push(shortName(d.name));
    g.deadlineIds.push(d.id);
    if (/escrow/i.test(d.name)) g.isCoe = true;
    byDate.set(d.due_date, g);
  }
  const dated = [...byDate.values()].sort((a, b) => a.t - b.t);

  if (dated.length === 0) {
    return (
      <div className="card">
        <h2><Icon name="calendar" size={17} /> Timeline</h2>
        <div className="empty">
          <span className="empty-ic"><Icon name="calendar" size={26} /></span>
          No deadlines computed yet — confirm the extracted fields to build the timeline.
        </div>
      </div>
    );
  }

  const accT = acceptanceDate ? Date.parse(acceptanceDate) : NaN;
  const milestones: Milestone[] = [];
  if (!Number.isNaN(accT)) {
    milestones.push({
      key: "acceptance", t: accT, dateIso: acceptanceDate as string,
      names: ["Acceptance"], deadlineIds: [], anchor: true, isCoe: false,
    });
  }
  milestones.push(...dated);

  const now = Date.now();
  const coe = milestones.find((m) => m.isCoe) ?? milestones[milestones.length - 1];
  const start = milestones[0].t;
  const end = Math.max(coe.t, milestones[milestones.length - 1].t);
  const span = Math.max(end - start, DAY);
  // Inset the plot so the first/last markers (and their centered labels) never
  // overflow the card edges.
  const PAD = 7;
  const pos = (t: number) => PAD + Math.max(0, Math.min(1, (t - start) / span)) * (100 - 2 * PAD);
  const todayPos = pos(now);
  const showToday = now >= start - DAY && now <= end + DAY;

  // per-milestone task state
  const tasksByDeadline = new Map<string, Task[]>();
  for (const tk of tasks) {
    if (tk.deadline_id) {
      const arr = tasksByDeadline.get(tk.deadline_id) ?? [];
      arr.push(tk);
      tasksByDeadline.set(tk.deadline_id, arr);
    }
  }
  const linkedTasks = (m: Milestone) => m.deadlineIds.flatMap((d) => tasksByDeadline.get(d) ?? []);
  const doneOf = (m: Milestone) => {
    const ts = linkedTasks(m);
    return ts.length > 0 && ts.every(isDone);
  };

  type State = "done" | "overdue" | "next" | "up" | "goal";
  const stateOf = (m: Milestone): State => {
    if (m.anchor) return "done";
    if (doneOf(m)) return "done";
    if (m.t < now - DAY) return "overdue";
    if (m.isCoe) return "goal";
    return "up";
  };
  // nearest upcoming, not-done milestone → the "next"
  const nextKey = milestones
    .filter((m) => !m.anchor && m.t >= now - DAY && !doneOf(m))
    .sort((a, b) => a.t - b.t)[0]?.key;

  const daysToClose = Math.round((coe.t - now) / DAY);
  const nextM = milestones.find((m) => m.key === nextKey);
  const nextDays = nextM ? Math.round((nextM.t - now) / DAY) : null;

  // phases: Contingency period, then Closing (only when contingencies clear
  // meaningfully before COE — avoids a zero-width band when the last contingency
  // lands on the close date, as in an all-cash deal).
  const contTs = milestones
    .filter((m) => /inspection|appraisal|loan|insurance/i.test(m.names.join(" ")))
    .map((m) => m.t);
  const contEnd = contTs.length ? Math.max(...contTs) : start;
  const phases: { n: string; from: number; to: number; c: string }[] = [];
  if (contEnd > start && contEnd < end) {
    phases.push({ n: "Contingency period", from: start, to: contEnd, c: "cont" });
    phases.push({ n: "Closing", from: contEnd, to: end, c: "close" });
  } else if (contEnd >= end) {
    phases.push({ n: "Contingency period", from: start, to: end, c: "cont" });
  } else {
    phases.push({ n: "In escrow", from: start, to: end, c: "cont" });
  }

  async function markDone(taskId: string, done: boolean) {
    setBusy(true);
    try {
      await api.patch(`/transactions/${id}/tasks/${taskId}`, { status: done ? "done" : "pending" });
      toast(done ? "Task done" : "Reopened");
      onChanged();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", { error: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card tlr-card">
      <div className="tlr-hero">
        <div>
          <div className="tlr-eyebrow">◷ Deal timeline</div>
          <div className="tlr-count">
            {daysToClose < 0 ? (
              <>Closed <b>{-daysToClose}d ago</b></>
            ) : (
              <>Closing in <b>{daysToClose}d</b></>
            )}
          </div>
        </div>
        {nextM && nextDays != null && (
          <div className="tlr-next">
            <div className="tlr-nlab">Next up</div>
            <div className="tlr-nval">
              <Icon name={iconFor(nextM.names[0])} size={13} /> {nextM.names[0]} ·{" "}
              {nextDays < 0 ? `${-nextDays}d overdue` : nextDays === 0 ? "today" : `in ${nextDays}d`}
            </div>
          </div>
        )}
      </div>

      <div className="tlr-phasebar">
        {phases.map((p, i) => {
          const w = pos(p.to) - pos(p.from);
          return (
            <div key={i} className={`tlr-seg b-${p.c}`} style={{ left: `${pos(p.from)}%`, width: `${w}%` }}>
              {w >= 10 && <span>{p.n}</span>}
            </div>
          );
        })}
      </div>

      <div
        className={`tlr ${played ? "play" : ""}`}
        style={{
          ["--today" as keyof CSSProperties]: `${todayPos}%`,
          ["--fillw" as keyof CSSProperties]: `${todayPos - PAD}%`,
        } as CSSProperties}
      >
        <div className="tlr-track" />
        <div className="tlr-fill" />
        {showToday && <div className="tlr-today" />}

        {milestones.map((m, i) => {
          const st = m.key === nextKey ? "next" : stateOf(m);
          const above = i % 2 === 0;
          const days = Math.round((m.t - now) / DAY);
          // For the close-of-escrow group (loan contingency often shares the
          // date), lead with "Close of escrow" — it's the milestone that matters.
          const dispNames = m.isCoe
            ? ["Close of escrow", ...m.names.filter((n) => !/escrow/i.test(n))]
            : m.names;
          const label = dispNames[0] + (dispNames.length > 1 ? ` +${dispNames.length - 1}` : "");
          const status =
            st === "done" ? "✓ done"
              : days < 0 ? `${-days}d ago`
              : days === 0 ? "today"
              : `${days}d`;
          const pillCls = st === "done" ? "p-done" : st === "next" ? "p-next" : st === "overdue" ? "p-over" : "p-up";
          const openTask = linkedTasks(m).find((t) => !isDone(t)) ?? linkedTasks(m)[0] ?? null;
          return (
            <div
              key={m.key}
              className={`tlr-mk ${above ? "above" : "below"} ${st}`}
              style={{ left: `${pos(m.t)}%`, transitionDelay: `${0.35 + i * 0.08}s` }}
            >
              {st === "next" && <span className="tlr-nexttag">NEXT</span>}
              <div className="tlr-conn" />
              <div className="tlr-ic">{st === "done" ? <Icon name="check" size={22} /> : <Icon name={iconFor(m.names[0])} size={22} />}</div>
              <div className="tlr-lab">
                <div className="tlr-nm" title={m.names.join(", ")}>{label}</div>
                <div className="tlr-dt">{fmtDate(m.dateIso).replace(/,\s*\d{4}$/, "")}</div>
                <span className={`tlr-pill ${pillCls}`}>{status}</span>
              </div>
              <div className="tlr-pop">
                <div className="tlr-pt"><Icon name={iconFor(m.names[0])} size={12} /> {m.names.join(", ")} · {fmtDate(m.dateIso).replace(/,\s*\d{4}$/, "")}</div>
                {openTask ? (
                  <>
                    <div className="tlr-pn">{openTask.title}</div>
                    <div className="tlr-acts">
                      {isDone(openTask) ? (
                        <button disabled={busy} onClick={() => void markDone(openTask.id, false)}>Reopen</button>
                      ) : (
                        <button className="pri" disabled={busy} onClick={() => void markDone(openTask.id, true)}>Mark done</button>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="tlr-pn muted">{m.anchor ? "Contract executed" : "No task linked"}</div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="tlr-legend">
        <span><span className="tlr-dot d-done" /> done</span>
        <span><span className="tlr-dot d-next" /> next up</span>
        <span><span className="tlr-dot d-up" /> upcoming</span>
        <span><span className="tlr-dot d-over" /> overdue</span>
        <span><span className="tlr-dot d-goal" /> close of escrow</span>
        <span style={{ marginLeft: "auto" }} className="muted">hover a milestone for its task →</span>
      </div>
    </div>
  );
}
