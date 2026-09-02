import { useEffect, useMemo, useRef, useState } from "react";
import { api, Deadline, DealDocument, Task } from "../lib/api";
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
type MkState = "done" | "overdue" | "next" | "up" | "goal";

// Measured chip widths so the lane packer never lets two labels overlap.
const meter =
  typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
function chipWidth(label: string, date: string | null): number {
  if (!meter) return 120;
  meter.font = "600 11.8px Inter, system-ui, sans-serif";
  let w = 24 + 7 + 7 + meter.measureText(label).width; // padding + dot + gap + label
  if (date) {
    meter.font = "500 9.9px ui-monospace, Menlo, monospace";
    w += 7 + meter.measureText(date).width;
  }
  return Math.ceil(w);
}

const LANE_TOPS = [96, 62, 28]; // chip y per lane; lane 0 sits nearest the axis
const AXIS_Y = 142;
const PAD = 34;
const GAP = 6;

/** The deal runway with PHASE CHAPTER ZOOM: pill-chip milestones packed into
 *  collision-free lanes, a clickable phase strip (Whole deal → glide into a
 *  chapter → Esc back out), crowded stretches folding into "+N" chips that zoom
 *  on click, and a today line. Hovering a chip shows its linked task. */
export function DealTimeline({
  id,
  deadlines,
  tasks,
  documents,
  acceptanceDate,
  onChanged,
}: {
  id: string;
  deadlines: Deadline[];
  tasks: Task[];
  documents: DealDocument[];
  acceptanceDate: string | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [played, setPlayed] = useState(false);
  // Extra lanes absorbed from the old Deal Map tab: flexible work (tasks) and
  // the paper trail (documents) against the same date axis. Off by default —
  // the hero view stays the contractual runway.
  const [showTasks, setShowTasks] = useState(false);
  const [showDocs, setShowDocs] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const r = requestAnimationFrame(() => requestAnimationFrame(() => setPlayed(true)));
    return () => cancelAnimationFrame(r);
  }, []);
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // ---- data prep (grouping, states, phases) --------------------------------
  const model = useMemo(() => {
    const byDate = new Map<string, Milestone>();
    for (const d of deadlines) {
      const t = Date.parse(d.due_date);
      if (Number.isNaN(t)) continue;
      const g = byDate.get(d.due_date) ?? {
        key: d.due_date, t, dateIso: d.due_date, names: [], deadlineIds: [],
        anchor: false, isCoe: false,
      };
      g.names.push(shortName(d.name));
      g.deadlineIds.push(d.id);
      if (/escrow/i.test(d.name)) g.isCoe = true;
      byDate.set(d.due_date, g);
    }
    const dated = [...byDate.values()].sort((a, b) => a.t - b.t);
    const accT = acceptanceDate ? Date.parse(acceptanceDate) : NaN;
    const milestones: Milestone[] = [];
    if (!Number.isNaN(accT)) {
      milestones.push({
        key: "acceptance", t: accT, dateIso: acceptanceDate as string,
        names: ["Acceptance"], deadlineIds: [], anchor: true, isCoe: false,
      });
    }
    milestones.push(...dated);
    if (milestones.length === 0) return null;

    const coe = milestones.find((m) => m.isCoe) ?? milestones[milestones.length - 1];
    const start = milestones[0].t;
    const end = Math.max(coe.t, milestones[milestones.length - 1].t) + DAY;
    const contTs = milestones
      .filter((m) => /inspection|appraisal|loan|insurance/i.test(m.names.join(" ")))
      .map((m) => m.t);
    const contEnd = contTs.length ? Math.max(...contTs) + DAY : start;
    const phases: { n: string; from: number; to: number; c: string }[] = [];
    if (contEnd > start && contEnd < end) {
      phases.push({ n: "Contingency period", from: start, to: contEnd, c: "cont" });
      phases.push({ n: "Closing", from: contEnd, to: end, c: "close" });
    } else {
      phases.push({ n: "In escrow", from: start, to: end, c: "cont" });
    }
    return { milestones, coe, start, end, phases };
  }, [deadlines, acceptanceDate]);

  // ---- zoom state (animated) ------------------------------------------------
  const [view, setView] = useState<{ f: number; t: number } | null>(null);
  const viewRef = useRef(view);
  viewRef.current = view;
  const animRef = useRef<number>(0);
  const reduced =
    typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function zoomTo(f: number | null, t?: number) {
    if (!model) return;
    const target = f === null ? { f: model.start, t: model.end } : { f, t: t as number };
    const isWhole = f === null;
    const cur = viewRef.current ?? { f: model.start, t: model.end };
    cancelAnimationFrame(animRef.current);
    if (reduced) { setView(isWhole ? null : target); return; }
    const startTs = performance.now();
    const dur = 430;
    const ease = (u: number) => 1 - Math.pow(1 - u, 3);
    const step = (now: number) => {
      const u = Math.min(1, (now - startTs) / dur);
      const k = ease(u);
      setView({ f: cur.f + (target.f - cur.f) * k, t: cur.t + (target.t - cur.t) * k });
      if (u < 1) animRef.current = requestAnimationFrame(step);
      else setView(isWhole ? null : target);
    };
    animRef.current = requestAnimationFrame(step);
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") zoomTo(null); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model]);

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

  if (!model) {
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

  const { milestones, coe, start, end, phases } = model;
  const now = Date.now();
  const from = view?.f ?? start;
  const to = view?.t ?? end;
  const xOf = (t: number) => PAD + ((t - from) / (to - from)) * (Math.max(width, 320) - PAD * 2);
  const pxPerDay = (Math.max(width, 320) - PAD * 2) / ((to - from) / DAY);
  const withDate = pxPerDay > 15;

  // task state per milestone
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
  const stateOf = (m: Milestone): MkState => {
    if (m.anchor || doneOf(m)) return "done";
    if (m.t < now - DAY) return "overdue";
    if (m.isCoe) return "goal";
    return "up";
  };
  const nextKey = milestones
    .filter((m) => !m.anchor && m.t >= now - DAY && !doneOf(m))
    .sort((a, b) => a.t - b.t)[0]?.key;
  const daysToClose = Math.round((coe.t - now) / DAY);
  const nextM = milestones.find((m) => m.key === nextKey);
  const nextDays = nextM ? Math.round((nextM.t - now) / DAY) : null;

  // ---- lane packing (collision-free chips; overflow → +N clusters) ---------
  const inRange = milestones
    .filter((m) => m.t >= from - DAY / 2 && m.t <= to + DAY / 2)
    .map((m) => {
      const st: MkState = m.key === nextKey ? "next" : stateOf(m);
      const label =
        (m.isCoe ? "Close of escrow" : m.names[0]) +
        (m.names.length > 1 ? ` +${m.names.length - 1}` : "");
      const date = withDate ? fmtDate(m.dateIso).replace(/,\s*\d{4}$/, "") : null;
      const pri = st === "next" ? 5 : st === "overdue" ? 4 : st === "goal" ? 3 : m.anchor ? 2 : 1;
      return { m, st, label, date, pri, x: xOf(m.t), w: chipWidth(label, date) };
    });
  const W = Math.max(width, 320);
  const lanes: [number, number][][] = LANE_TOPS.map(() => []);
  const placed: (typeof inRange[number] & { cx: number; lane: number })[] = [];
  const overflow: typeof inRange = [];
  for (const c of [...inRange].sort((a, b) => b.pri - a.pri || a.m.t - b.m.t)) {
    const cx = Math.max(4 + c.w / 2, Math.min(W - 4 - c.w / 2, c.x));
    let lane = -1;
    for (let i = 0; i < lanes.length; i++) {
      if (lanes[i].every(([a, b]) => cx + c.w / 2 + GAP < a || cx - c.w / 2 - GAP > b)) {
        lane = i;
        break;
      }
    }
    if (lane === -1) { overflow.push(c); continue; }
    lanes[lane].push([cx - c.w / 2, cx + c.w / 2]);
    placed.push({ ...c, cx, lane });
  }
  overflow.sort((a, b) => a.x - b.x);
  const clusters: { items: typeof overflow; x0: number; x1: number }[] = [];
  for (const c of overflow) {
    const g = clusters[clusters.length - 1];
    if (g && c.x - g.x1 < 60) { g.items.push(c); g.x1 = c.x; }
    else clusters.push({ items: [c], x0: c.x, x1: c.x });
  }

  // week/day ticks
  const ticks: { x: number; label: string | null }[] = [];
  const stepDays = pxPerDay > 34 ? 1 : 7;
  const firstDay = Math.ceil((from - start) / DAY);
  const lastDay = Math.floor((to - start) / DAY);
  for (let d = firstDay; d <= lastDay; d++) {
    if (stepDays === 7 && d % 7 !== 0) continue;
    const t = start + d * DAY;
    const x = xOf(t);
    if (x < PAD - 6 || x > W - PAD + 6) continue;
    const show = stepDays === 1 ? d % 2 === 0 : true;
    ticks.push({ x, label: show ? fmtDate(new Date(t).toISOString()).replace(/,\s*\d{4}$/, "") : null });
  }

  const isWhole = view === null;
  const activePhase = phases.find(
    (p) => Math.abs(p.from - from) < DAY / 2 && Math.abs(p.to - to) < DAY / 2,
  );
  const todayX = now >= from && now <= to ? xOf(now) : null;

  // ---- extra lanes (former Deal Map): tasks + document arrivals ------------
  type LaneItem = { at: number; label: string; tone: string; square?: boolean };
  const extraLanes: { name: string; items: LaneItem[] }[] = [];
  if (showTasks) {
    extraLanes.push({
      name: "Tasks",
      items: tasks
        .filter((t) => t.due_date)
        .map((t) => ({
          at: Date.parse(t.due_date as string),
          label: `${t.title} — due ${fmtDate(t.due_date as string).replace(/,\s*\d{4}$/, "")}`,
          tone: isDone(t) ? "done" : Date.parse(t.due_date as string) < now - DAY ? "overdue" : "up",
        })),
    });
  }
  if (showDocs) {
    extraLanes.push({
      name: "Documents",
      items: documents
        .filter((d) => d.created_at)
        .map((d) => ({
          at: Date.parse(d.created_at as string),
          label: `${
            d.doc_type === "other" && d.label ? d.label : (d.doc_type ?? "document").replace(/_/g, " ")
          } — received ${fmtDate(d.created_at as string).replace(/,\s*\d{4}$/, "")}`,
          tone: "doc",
          square: true,
        })),
    });
  }
  const LANE_H = 30;
  const stageHeight = 216 + extraLanes.length * LANE_H + (extraLanes.length ? 6 : 0);

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

      <div className="tz-btns">
        <button className={`tz-zb ${isWhole ? "on" : ""}`} onClick={() => zoomTo(null)}>
          Whole deal
        </button>
        {phases.map((p) => (
          <button
            key={p.n}
            className={`tz-zb ${activePhase?.n === p.n ? "on" : ""}`}
            onClick={() => zoomTo(p.from, p.to)}
          >
            {p.n}
          </button>
        ))}
        <span className="tz-sep" />
        <button
          className={`tz-zb tz-lane-toggle ${showTasks ? "on" : ""}`}
          title="Overlay task due dates as a lane (from the old Deal Map)"
          onClick={() => setShowTasks((v) => !v)}
        >
          Tasks
        </button>
        <button
          className={`tz-zb tz-lane-toggle ${showDocs ? "on" : ""}`}
          title="Overlay document arrivals as a lane (from the old Deal Map)"
          onClick={() => setShowDocs((v) => !v)}
        >
          Documents
        </button>
        {!isWhole && <span className="tz-esc">Esc to zoom out</span>}
      </div>

      <div
        className={`tz-stage ${played ? "play" : ""}`}
        ref={stageRef}
        style={{ height: stageHeight }}
      >
        <div className="tz-axis" />
        {todayX !== null && (
          <>
            <div className="tz-today" style={{ left: todayX }} />
            <div className="tz-today-lab" style={{ left: todayX }}>today</div>
          </>
        )}
        {ticks.map((tk, i) => (
          <span key={i}>
            <div className="tz-tick" style={{ left: tk.x }} />
            {tk.label && <div className="tz-tick-lab" style={{ left: tk.x }}>{tk.label}</div>}
          </span>
        ))}
        <div className="tz-strip">
          {phases.map((p) => {
            const x0 = Math.max(2, xOf(p.from));
            const x1 = Math.min(W - 2, xOf(p.to));
            if (x1 - x0 < 10) return null;
            return (
              <div
                key={p.n}
                className={`tz-band b-${p.c} ${activePhase?.n === p.n ? "active" : ""}`}
                style={{ left: x0 + 2, width: x1 - x0 - 4 }}
                onClick={() => zoomTo(p.from, p.to)}
                role="button"
                title={`Zoom into ${p.n}`}
              >
                <span>{x1 - x0 > 110 ? p.n : p.n.slice(0, 4)}</span>
              </div>
            );
          })}
        </div>

        {inRange.map((c) => (
          <div
            key={c.m.key}
            className={`tz-pip s-${c.st}`}
            style={{ left: c.x }}
            title={`${c.m.names.join(", ")} — ${fmtDate(c.m.dateIso)}`}
          />
        ))}

        {placed.map((c, i) => {
          const top = LANE_TOPS[c.lane];
          const openTask = linkedTasks(c.m).find((t) => !isDone(t)) ?? linkedTasks(c.m)[0] ?? null;
          return (
            <div
              key={c.m.key}
              className={`tz-mk s-${c.st}`}
              style={{ left: c.cx, top, transitionDelay: played ? "0s" : `${0.2 + i * 0.05}s` }}
            >
              {c.st === "next" && <span className="tz-nexttag">NEXT</span>}
              <div className="tz-chip">
                <i />
                {c.st === "done" && <Icon name="check" size={11} />}
                {c.label}
                {c.date && <span className="d">{c.date}</span>}
              </div>
              <div className="tz-pop">
                <div className="tz-pt">
                  <Icon name={iconFor(c.m.names[0])} size={12} /> {c.m.names.join(", ")} ·{" "}
                  {fmtDate(c.m.dateIso).replace(/,\s*\d{4}$/, "")}
                </div>
                {openTask ? (
                  <>
                    <div className="tz-pn">{openTask.title}</div>
                    <div className="tz-acts">
                      {isDone(openTask) ? (
                        <button disabled={busy} onClick={() => void markDone(openTask.id, false)}>
                          Reopen
                        </button>
                      ) : (
                        <button
                          className="pri"
                          disabled={busy}
                          onClick={() => void markDone(openTask.id, true)}
                        >
                          Mark done
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="tz-pn muted">
                    {c.m.anchor ? "Contract executed" : "No task linked"}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {/* stems drawn separately so chips can be nudged without bending them */}
        {placed.map((c) => (
          <div
            key={`stem-${c.m.key}`}
            className="tz-stem"
            style={{ left: c.x, top: LANE_TOPS[c.lane] + 24, height: AXIS_Y - 3 - (LANE_TOPS[c.lane] + 24) }}
          />
        ))}

        {extraLanes.map((lane, li) => {
          const top = 208 + li * LANE_H;
          return (
            <div key={lane.name} className="tz-lane" style={{ top }}>
              <span className="tz-lane-name">{lane.name}</span>
              <div className="tz-lane-line" />
              {lane.items
                .filter((it) => it.at >= from - DAY / 2 && it.at <= to + DAY / 2)
                .map((it, i) => (
                  <div
                    key={i}
                    className={`tz-lane-pip t-${it.tone} ${it.square ? "sq" : ""}`}
                    style={{ left: xOf(it.at) }}
                    title={it.label}
                  />
                ))}
            </div>
          );
        })}

        {clusters.map((g, i) => {
          const cx = (g.x0 + g.x1) / 2;
          const lo = Math.min(...g.items.map((c) => c.m.t));
          const hi = Math.max(...g.items.map((c) => c.m.t));
          return (
            <button
              key={i}
              className="tz-more"
              style={{ left: cx, top: LANE_TOPS[LANE_TOPS.length - 1] - 32 }}
              title={g.items.map((c) => `${c.m.names.join(", ")} — ${fmtDate(c.m.dateIso)}`).join("\n")}
              onClick={() =>
                zoomTo(Math.max(start, lo - 1.5 * DAY), Math.min(end, hi + 1.5 * DAY))
              }
            >
              +{g.items.length} deadline{g.items.length > 1 ? "s" : ""}
            </button>
          );
        })}
      </div>

      <div className="tlr-legend">
        <span><span className="tlr-dot d-done" /> done</span>
        <span><span className="tlr-dot d-next" /> next up</span>
        <span><span className="tlr-dot d-up" /> upcoming</span>
        <span><span className="tlr-dot d-over" /> overdue</span>
        <span><span className="tlr-dot d-goal" /> close of escrow</span>
        <span style={{ marginLeft: "auto" }} className="muted">
          click a phase to zoom · hover a chip for its task
        </span>
      </div>
    </div>
  );
}
