import { useCallback, useEffect, useState } from "react";
import { api, DealSummary } from "../lib/api";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

/* My quarter — the TC's personal self-assessment. Live figures are derived from
 * the same board rollup Home uses; quarter-over-quarter comparison needs closed-
 * deal history we don't warehouse yet, so those points are clearly marked as
 * sample until that history is wired (no pretending nonexistent data is real). */

const DAY = 86_400_000;
function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso + "T00:00:00").getTime();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((t - today.getTime()) / DAY);
}
function money(s: string | null): number {
  if (!s) return 0;
  const n = Number(String(s).replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) ? n : 0;
}
function fmtM(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1_000)}k`;
  return `$${n}`;
}

export function Quarter() {
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  // BUG-26: don't hardcode a stale quarter. Figures are all-time until quarter
  // history lands; label the CURRENT quarter rather than a fixed past one.
  const now = new Date();
  const quarterLabel = `Q${Math.floor(now.getMonth() / 3) + 1} ${now.getFullYear()}`;

  const load = useCallback(async () => {
    try {
      setDeals(await api.get<DealSummary[]>("/transactions/board"));
      setLoadError(false);
      setLoaded(true);
    } catch (err) {
      setLoadError(true);
      toast(err instanceof Error ? err.message : "Failed to load", { error: true });
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const closed = deals.filter((d) => d.stage === "closed");
  const active = deals.filter((d) => d.stage !== "closed");
  const closingWk = active.filter((d) => {
    const n = daysTo(d.coe_date);
    return n != null && n >= 0 && n <= 7;
  }).length;
  const doneTasks = deals.reduce((s, d) => s + d.done_tasks, 0);
  const totalTasks = deals.reduce((s, d) => s + d.total_tasks, 0);
  const taskRate = totalTasks ? Math.round((doneTasks / totalTasks) * 100) : 0;
  const pipeline = active.reduce((s, d) => s + money(d.purchase_price), 0);
  const closedVol = closed.reduce((s, d) => s + money(d.purchase_price), 0);


  return (
    <div className="qtr">
      <div className="qtr-head">
        <div>
          <h1>Your quarter</h1>
          <div className="muted">{quarterLabel} · your personal performance, visible only to you</div>
        </div>
      </div>

      <div className="qtr-note">
        <div className="qtr-note-lab"><Icon name="sparkle" size={14} /> Quarter in review</div>
        <h2>
          {loadError ? "Couldn't load your quarter" : loaded ? `${closed.length} deal${closed.length === 1 ? "" : "s"} closed` : "Loading your quarter…"}
          {loaded && ` · ${active.length} active in your pipeline`}
        </h2>
        <p>
          You have {active.length} active deal{active.length === 1 ? "" : "s"} worth {fmtM(pipeline)} in your pipeline,
          with {closingWk} closing this week. You've completed {doneTasks} of {totalTasks} tasks ({taskRate}%).
        </p>
      </div>

      <div className="qtr-scores">
        <Score k="Deals closed" v={loaded ? String(closed.length) : "—"} d="live from your board" live />
        <Score k="Active pipeline" v={loaded ? fmtM(pipeline) : "—"} d={`${active.length} deals`} live />
        <Score k="Task completion" v={loaded ? `${taskRate}%` : "—"} d={`${doneTasks}/${totalTasks} done`} live />
        <Score k="Volume closed" v={loaded ? fmtM(closedVol) : "—"} d="live from your board" live />
      </div>

      <div className="qtr-cols">
        <div className="card">
          <div className="card-h">
            <h3>Trends</h3>
          </div>
          <p className="muted qtr-ring-s">
            Monthly closings and your on-time deadline rate build here as deals close.
            Nothing to chart yet.
          </p>
        </div>
      </div>
    </div>
  );
}

function Score({ k, v, d, live }: { k: string; v: string; d: string; live?: boolean }) {
  return (
    <div className="qtr-score">
      <div className="qtr-score-k">
        {k}
        {live && <span className="chip-live">live</span>}
      </div>
      <div className="qtr-score-v tnum">{v}</div>
      <div className="qtr-score-d">{d}</div>
    </div>
  );
}
