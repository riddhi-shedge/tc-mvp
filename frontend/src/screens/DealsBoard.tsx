import { useCallback, useEffect, useState } from "react";
import {
  api,
  DEAL_STAGES,
  DealSummary,
  TransactionSummary,
} from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

type ViewT = "board" | "tbl";

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  return fmtDate(iso).replace(/,\s*\d{4}$/, "");
}
function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  return Math.round((new Date(iso + "T00:00:00").getTime() - Date.now()) / 86_400_000);
}
function urgency(d: DealSummary): "red" | "amber" | "green" | "done" {
  if (d.stage === "closed") return "done";
  const n = daysTo(d.coe_date);
  if (n == null) return "green";
  return n <= 2 ? "red" : n <= 7 ? "amber" : "green";
}
function shortPrice(v: string | null): string | null {
  if (!v) return null;
  const n = parseFloat(v.replace(/[^0-9.]/g, ""));
  if (!isFinite(n) || n === 0) return v;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2).replace(/\.?0+$/, "")}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}K`;
  return `$${n}`;
}
function coeChipLabel(d: DealSummary): string {
  if (d.stage === "closed") return `Closed ${shortDate(d.coe_date)}`;
  const n = daysTo(d.coe_date);
  if (n == null) return "No close date yet";
  return `COE ${shortDate(d.coe_date)} · ${n < 0 ? `${-n}d ago` : `${n}d`}`;
}
function shortAddr(a: string | null): string {
  return (a ?? "(no address)").split(",")[0];
}

export function DealsBoard({ onOpenDeal }: { onOpenDeal: (id: string) => void }) {
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [archived, setArchived] = useState<TransactionSummary[]>([]);
  const [view, setView] = useState<ViewT>(
    () => (localStorage.getItem("deals_view") as ViewT) || "board",
  );
  const [dragId, setDragId] = useState<string | null>(null);
  const [overStage, setOverStage] = useState<string | null>(null);
  const [showArch, setShowArch] = useState(false);
  const [sv, setSv] = useState<"all" | "closing" | "risk">("all");

  const inClosingWk = (d: DealSummary) => {
    const n = daysTo(d.coe_date);
    return d.stage !== "closed" && n != null && n >= 0 && n <= 7;
  };
  const matchSv = (d: DealSummary) =>
    sv === "all" ? true : sv === "closing" ? inClosingWk(d) : d.risk_count > 0;
  const shown = deals.filter(matchSv);
  const svCounts = {
    all: deals.length,
    closing: deals.filter(inClosingWk).length,
    risk: deals.filter((d) => d.risk_count > 0).length,
  };

  const refresh = useCallback(async () => {
    try {
      const [b, all] = await Promise.all([
        api.get<DealSummary[]>("/transactions/board"),
        api.get<TransactionSummary[]>("/transactions"),
      ]);
      setDeals(b);
      setArchived(all.filter((t) => t.status === "archived"));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load deals", { error: true });
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  function pick(v: ViewT) {
    setView(v);
    localStorage.setItem("deals_view", v);
  }

  async function dropOn(stage: string) {
    const id = dragId;
    setDragId(null);
    setOverStage(null);
    if (!id) return;
    const current = deals.find((d) => d.id === id);
    if (!current || current.stage === stage) return;
    setDeals((ds) => ds.map((d) => (d.id === id ? { ...d, stage } : d))); // optimistic
    try {
      await api.post(`/transactions/${id}/stage`, { stage });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Move failed", { error: true });
      await refresh();
    }
  }

  const card = (d: DealSummary) => {
    const u = urgency(d);
    const pct = d.total_tasks ? Math.round((d.done_tasks / d.total_tasks) * 100) : 0;
    return (
      <div
        key={d.id}
        className={`db-deal ${d.status === "canceled" ? "db-canceled" : ""}`}
        data-u={u}
        draggable
        onDragStart={() => setDragId(d.id)}
        onDragEnd={() => setDragId(null)}
        onClick={() => onOpenDeal(d.id)}
      >
        <span className="db-stripe" />
        <div className="db-addr">{shortAddr(d.property_address)}</div>
        {d.status === "canceled" && <span className="db-fell">Fell through</span>}
        <div className="db-chips">
          <span className="db-chip coe" data-u={u === "done" ? "" : u}>◷ {coeChipLabel(d)}</span>
          {shortPrice(d.purchase_price) && <span className="db-chip">{shortPrice(d.purchase_price)}</span>}
          {d.all_cash && <span className="db-chip cash">cash</span>}
        </div>
        <div className="db-foot">
          <div className="db-prog"><i style={{ width: `${pct}%` }} /></div>
          <span className="db-ptxt">{d.done_tasks}/{d.total_tasks}</span>
          {d.risk_count > 0 && <span className="db-risk"><Icon name="warning" size={12} /> {d.risk_count}</span>}
        </div>
      </div>
    );
  };

  return (
    <div className="db">
      <div className="db-head">
        <h2 style={{ margin: 0 }}><Icon name="board" size={17} /> Deals <span className="muted" style={{ fontWeight: 400, fontSize: "0.9rem" }}>· {deals.length} active</span></h2>
        <div className="db-tabs" role="tablist">
          <button className={`db-tab ${view === "board" ? "on" : ""}`} onClick={() => pick("board")}>▦ Board</button>
          <button className={`db-tab ${view === "tbl" ? "on" : ""}`} onClick={() => pick("tbl")}>≣ Table</button>
        </div>
      </div>

      <div className="db-views">
        {([["all", "All deals"], ["closing", "Closing this week"], ["risk", "At risk"]] as const).map(([k, label]) => (
          <button key={k} className={`db-sv ${sv === k ? "on" : ""}`} onClick={() => setSv(k)}>
            {label}<span className="db-sv-c">{svCounts[k]}</span>
          </button>
        ))}
      </div>

      {deals.length === 0 && (
        <div className="card"><div className="empty"><span className="empty-ic"><Icon name="board" size={26} /></span>No active deals — confirm an inbound document to create one.</div></div>
      )}

      {/* BOARD */}
      {view === "board" && deals.length > 0 && (
        <div className="db-board">
          {DEAL_STAGES.map((st) => {
            const inStage = shown.filter((d) => d.stage === st.id);
            return (
              <div
                key={st.id}
                className={`db-col ${overStage === st.id ? "over" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setOverStage(st.id); }}
                onDragLeave={() => setOverStage((s) => (s === st.id ? null : s))}
                onDrop={() => void dropOn(st.id)}
              >
                <div className="db-col-h">
                  <span className={`db-cdot s-${st.id}`} />
                  <span className="db-cname">{st.name}</span>
                  <span className="db-cn">{inStage.length}</span>
                </div>
                <div className="db-stack">{inStage.map(card)}</div>
              </div>
            );
          })}
        </div>
      )}

      {/* CALENDAR */}

      {/* TABLE */}
      {view === "tbl" && deals.length > 0 && (
        <div className="db-tblwrap">
          <table className="db-tbl">
            <thead>
              <tr><th>Property</th><th>Close</th><th>Stage</th><th>Tasks</th><th>Risk</th><th>Price</th></tr>
            </thead>
            <tbody>
              {[...shown]
                .sort((a, b) => (a.coe_date ?? "9999").localeCompare(b.coe_date ?? "9999"))
                .map((d) => {
                  const u = urgency(d);
                  const st = DEAL_STAGES.find((s) => s.id === d.stage)?.name ?? d.stage;
                  const n = daysTo(d.coe_date);
                  return (
                    <tr key={d.id} onClick={() => onOpenDeal(d.id)} style={{ cursor: "pointer" }}>
                      <td><div style={{ fontWeight: 600 }}>{shortAddr(d.property_address)}</div></td>
                      <td>
                        <span className={`db-badge ${u}`}>
                          {d.stage === "closed" ? "closed" : d.coe_date ? `${shortDate(d.coe_date)} · ${n! < 0 ? `${-n!}d ago` : `${n}d`}` : "—"}
                        </span>
                      </td>
                      <td>{st}</td>
                      <td className="tnum">{d.done_tasks}/{d.total_tasks}</td>
                      <td>{d.risk_count > 0 ? <span className="db-badge red"><Icon name="warning" size={12} /> {d.risk_count}</span> : <span className="muted">—</span>}</td>
                      <td className="tnum">{shortPrice(d.purchase_price) ?? "—"}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}

      {/* archived (kept reachable) */}
      {archived.length > 0 && (
        <div style={{ marginTop: "0.4rem" }}>
          <button className="secondary sm" onClick={() => setShowArch((s) => !s)}>
            {showArch ? "Hide" : "Show"} archived ({archived.length})
          </button>
          {showArch && (
            <div className="deal-grid" style={{ marginTop: "0.7rem" }}>
              {archived.map((t) => (
                <div key={t.id} className="deal-tile archived" onClick={() => onOpenDeal(t.id)}>
                  <div className="dt-addr">{shortAddr(t.property_address)}</div>
                  <span className="badge" style={{ alignSelf: "flex-start" }}>archived</span>
                  <div className="dt-meta">
                    <span className="dt-id">{t.id.slice(0, 8)}</span>
                    <button
                      className="secondary sm"
                      onClick={async (e) => {
                        e.stopPropagation();
                        await api.post(`/transactions/${t.id}/unarchive`);
                        await refresh();
                      }}
                    >
                      Unarchive
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

