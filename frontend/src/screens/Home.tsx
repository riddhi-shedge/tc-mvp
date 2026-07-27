import { ReactNode, useCallback, useEffect, useState } from "react";
import { api, CalendarDeadline, DEAL_STAGES, DealSummary, OpenTask } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

const DAY = 86_400_000;
function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso + "T00:00:00").getTime();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((t - today.getTime()) / DAY);
}
const short = (iso: string | null) => (iso ? fmtDate(iso).replace(/,\s*\d{4}$/, "") : "—");
const addr = (a: string | null) => (a ?? "(no address)").split(",")[0];
function urg(n: number | null): "red" | "amber" | "plain" {
  if (n == null) return "plain";
  return n <= 1 ? "red" : n <= 7 ? "amber" : "plain";
}
function countdown(n: number | null): string {
  if (n == null) return "—";
  return n < 0 ? `${-n}d ago` : n === 0 ? "today" : `${n}d`;
}
const stageName = (id: string) => DEAL_STAGES.find((s) => s.id === id)?.name ?? id;

/** Home — the cross-deal command center: what's due, what's at risk, this week's
 *  deadlines, and the open work queue, across every active deal. */
export function Home({ onOpenDeal }: { onOpenDeal: (id: string) => void }) {
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [cal, setCal] = useState<CalendarDeadline[]>([]);
  const [tasks, setTasks] = useState<OpenTask[]>([]);

  const load = useCallback(async () => {
    try {
      const [b, c, t] = await Promise.all([
        api.get<DealSummary[]>("/transactions/board"),
        api.get<CalendarDeadline[]>("/transactions/calendar"),
        api.get<OpenTask[]>("/transactions/tasks"),
      ]);
      setDeals(b);
      setCal(c);
      setTasks(t);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load", { error: true });
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  const active = deals.filter((d) => d.stage !== "closed");
  const dueToday = cal.filter((d) => daysTo(d.due_date) === 0).length;
  const closingWk = active.filter((d) => {
    const n = daysTo(d.coe_date);
    return n != null && n >= 0 && n <= 7;
  }).length;

  const attention = active
    .filter((d) => {
      const n = daysTo(d.coe_date);
      return d.risk_count > 0 || (n != null && n <= 2);
    })
    .sort((a, b) => (a.coe_date ?? "9999").localeCompare(b.coe_date ?? "9999"));

  const week = [...cal]
    .filter((d) => {
      const n = daysTo(d.due_date);
      return n != null && n >= -2 && n <= 7;
    })
    .sort((a, b) => a.due_date.localeCompare(b.due_date))
    .slice(0, 8);

  const queue = [...tasks].sort(
    (a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"),
  );

  return (
    <div className="hm">
      <div>
        <h1>{greet}</h1>
        <div className="hm-sub">
          {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          {" · "}
          {active.length} active deal{active.length === 1 ? "" : "s"} · {closingWk} closing this week
        </div>
      </div>

      <div className="hm-stats">
        <Stat k="Due today" v={dueToday} dot="var(--red-600)" />
        <Stat k="At risk" v={attention.length} dot="var(--amber-600)" />
        <Stat k="Closing this week" v={closingWk} dot="var(--gold-500)" />
        <Stat k="Open tasks" v={tasks.length} dot="var(--muted)" />
      </div>

      <div className="hm-cols">
        <div>
          <Section title="Needs attention" count={attention.length}>
            {attention.length === 0 ? (
              <Empty>Nothing at risk — nicely on top of it.</Empty>
            ) : (
              attention.map((d) => {
                const n = daysTo(d.coe_date);
                const u = urg(n);
                return (
                  <div key={d.id} className="hm-row" onClick={() => onOpenDeal(d.id)}>
                    <span className={`hm-sev ${u === "plain" ? "amber" : u}`} />
                    <div className="hm-main">
                      <div className="hm-title">{addr(d.property_address)}</div>
                      <div className="hm-rsub">
                        {stageName(d.stage)}
                        {d.risk_count > 0 && <span className="hm-warn"> · <Icon name="warning" size={12} /> {d.risk_count} risk{d.risk_count > 1 ? "s" : ""}</span>}
                      </div>
                    </div>
                    <span className={`pill-${u}`}>COE {countdown(n)}</span>
                  </div>
                );
              })
            )}
          </Section>

          <Section title="Deadlines this week" count={week.length}>
            {week.length === 0 ? (
              <Empty>No deadlines in the next week.</Empty>
            ) : (
              week.map((d, i) => {
                const n = daysTo(d.due_date);
                return (
                  <div key={i} className="hm-row" onClick={() => onOpenDeal(d.transaction_id)}>
                    <span className="hm-date tnum">{short(d.due_date)}</span>
                    <div className="hm-main">
                      <div className="hm-title">{d.name.replace(/ (ends|due|delivery).*$/i, "")}</div>
                      <div className="hm-rsub">{addr(d.property_address)}</div>
                    </div>
                    <span className={`pill-${urg(n)}`}>{countdown(n)}</span>
                  </div>
                );
              })
            )}
          </Section>
        </div>

        <div>
          <Section title="Work queue" count={queue.length}>
            {queue.length === 0 ? (
              <Empty>No open tasks — you're all caught up.</Empty>
            ) : (
              queue.slice(0, 10).map((t) => {
                const n = daysTo(t.due_date);
                return (
                  <div key={t.id} className="hm-row" onClick={() => onOpenDeal(t.transaction_id)}>
                    <span className="hm-ck" />
                    <div className="hm-main">
                      <div className="hm-title">{t.title}</div>
                      <div className="hm-rsub">{addr(t.property_address)}{t.due_date ? ` · due ${short(t.due_date)}` : ""}</div>
                    </div>
                    {t.due_date && <span className={`pill-${urg(n)}`}>{countdown(n)}</span>}
                  </div>
                );
              })
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

function Stat({ k, v, dot }: { k: string; v: number; dot: string }) {
  return (
    <div className="hm-stat">
      <div className="hm-k"><span className="hm-kd" style={{ background: dot }} />{k}</div>
      <div className="hm-v tnum">{v}</div>
    </div>
  );
}
function Section({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <div className="hm-section">
      <div className="hm-sh"><span className="hm-st">{title}</span><span className="hm-sc">{count}</span></div>
      <div className="hm-list">{children}</div>
    </div>
  );
}
function Empty({ children }: { children: ReactNode }) {
  return <div className="hm-empty">{children}</div>;
}
