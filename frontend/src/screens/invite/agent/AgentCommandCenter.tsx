import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtDate } from "../../../lib/format";
import { Icon, IconName } from "../../../lib/icons";
import { daysTo, humanize, initials } from "../helpers";
import { usePoll } from "../shared/usePoll";
import "./agent.css";
import {
  ApprovalItem, ClientRow, DealDetail, DealSummary, EarningsData, Portfolio, RiskLevel, ScheduleItem, STAGE_LABEL,
} from "./types";

type Papi = <T,>(path: string, init?: RequestInit) => Promise<T>;
type View = "today" | "pipeline" | "clients" | "schedule" | "earnings" | "activity" | "radar";
type PipeFilter = "all" | "at_risk" | "closing";

const RISK_RANK: Record<RiskLevel, number> = { at_risk: 2, watch: 1, ok: 0 };
const usd = (c: number | null | undefined) =>
  c == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(c / 100);

function riskLabel(risk: RiskLevel, date: string | null): string {
  const n = date ? daysTo(date) : null;
  if (risk === "at_risk") return n != null && n < 0 ? `${-n}d overdue` : "At risk";
  if (risk === "watch") return n != null ? `${n}d` : "Watch";
  return "On track";
}
export function RiskPill({ risk, date }: { risk: RiskLevel; date: string | null }) {
  const icon: IconName = risk === "at_risk" ? "warning" : risk === "watch" ? "clock" : "check";
  return <span className={`aw-risk ${risk}`}><Icon name={icon} size={11} /> {riskLabel(risk, date)}</span>;
}

export function AgentCommandCenter({ papi }: { papi: Papi }) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [clients, setClients] = useState<ClientRow[] | null>(null);
  const [schedule, setSchedule] = useState<ScheduleItem[] | null>(null);
  const [earnings, setEarnings] = useState<EarningsData | null>(null);
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [view, setView] = useState<View>("today");
  const [pipeFilter, setPipeFilter] = useState<PipeFilter>("all");
  const [cmdOpen, setCmdOpen] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // One request loads the book AND the queue (the portfolio ships approvalItems),
  // so each load/poll costs a single whole-book read instead of two.
  const loadAll = useCallback(async () => {
    try {
      const p = await papi<Portfolio>("/agent/portfolio");
      setPortfolio(p);
      if (p.approvalItems) setApprovals(p.approvalItems);
    } catch (e) { setErr(e instanceof Error ? e.message : "Couldn't load your book."); }
  }, [papi]);

  useEffect(() => { void loadAll(); }, [loadAll]);
  usePoll(() => { void loadAll(); }); // §7 live-sync
  useEffect(() => {
    if (view === "clients" && clients === null) {
      papi<{ clients: ClientRow[] }>("/agent/clients").then((d) => setClients(d.clients)).catch(() => setClients([]));
    }
    if (view === "schedule" && schedule === null) {
      papi<{ items: ScheduleItem[] }>("/agent/schedule").then((d) => setSchedule(d.items)).catch(() => setSchedule([]));
    }
    if (view === "earnings" && earnings === null) {
      papi<EarningsData>("/agent/earnings").then(setEarnings).catch(() => setEarnings({ rows: [], totals: { inEscrowCents: 0, closingSoonCents: 0, closedCents: 0 }, rateNote: "" }));
    }
  }, [view, clients, schedule, earnings, papi]);

  // ⌘K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmdOpen((o) => !o); }
      if (e.key === "Escape") { setCmdOpen(false); setDetail(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openDeal = useCallback(async (dealId: string) => {
    setCmdOpen(false);
    try { setDetail(await papi<DealDetail>(`/agent/deals/${dealId}`)); }
    catch (e) { setErr(e instanceof Error ? e.message : "Couldn't open that deal."); }
  }, [papi]);

  async function approve(item: ApprovalItem, editedBody?: string) {
    setApprovals((prev) => prev.filter((a) => a.id !== item.id)); // optimistic
    setPortfolio((p) => p && { ...p, stats: { ...p.stats, needYouToday: Math.max(0, p.stats.needYouToday - 1) } });
    try {
      await papi(`/agent/approvals/${item.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ transaction_id: item.dealId, body: editedBody ?? null }),
      });
    } catch (e) { setErr(e instanceof Error ? e.message : "Approve failed."); void loadAll(); }
  }
  async function dismiss(item: ApprovalItem) {
    setApprovals((prev) => prev.filter((a) => a.id !== item.id));
    setPortfolio((p) => p && { ...p, stats: { ...p.stats, needYouToday: Math.max(0, p.stats.needYouToday - 1) } });
    try { await papi(`/agent/approvals/${item.id}/dismiss`, { method: "POST", body: JSON.stringify({ transaction_id: item.dealId }) }); }
    catch (e) { setErr(e instanceof Error ? e.message : "Dismiss failed."); void loadAll(); }
  }
  async function draftClientUpdate(dealId: string) {
    setDrafting(true); setErr(null);
    try {
      await papi(`/agent/clients/${dealId}/draft-update`, { method: "POST" });
      await loadAll();
      setView("today");
    } catch (e) { setErr(e instanceof Error ? e.message : "Drafting is unavailable right now."); }
    finally { setDrafting(false); }
  }
  async function refreshCopilot() {
    setDrafting(true); setErr(null);
    try {
      await papi("/agent/copilot/refresh", { method: "POST", body: JSON.stringify({ limit: 8 }) });
      await loadAll();
    } catch (e) { setErr(e instanceof Error ? e.message : "Co-pilot drafting is unavailable right now."); }
    finally { setDrafting(false); }
  }

  if (err && !portfolio) {
    return <div className="aw"><div className="aw-topbar"><span className="aw-wordmark">Ter<b>ra</b></span></div>
      <div style={{ padding: "2rem" }}><div className="aw-empty">{err}</div></div></div>;
  }
  if (!portfolio) {
    return <div className="aw"><div className="aw-topbar"><span className="aw-wordmark">Ter<b>ra</b></span></div>
      <div style={{ padding: "2rem" }}><div className="aw-empty">Loading your book…</div></div></div>;
  }

  const { stats, deals, radar, activity, weekly, me } = portfolio;
  const nav: { id: View; label: string; icon: IconName; count?: number; hot?: boolean }[] = [
    { id: "pipeline", label: "Pipeline", icon: "board" },
    { id: "today", label: "Today", icon: "inbox", count: stats.needYouToday, hot: stats.needYouToday > 0 },
    { id: "clients", label: "Clients", icon: "users" },
    { id: "schedule", label: "Schedule", icon: "calendar" },
    { id: "earnings", label: "Earnings", icon: "money" },
    { id: "activity", label: "AI activity", icon: "sparkle" },
    { id: "radar", label: "Deadline radar", icon: "flag" },
  ];

  const go = (v: View, f: PipeFilter = "all") => { setView(v); setPipeFilter(f); };

  return (
    <div className="aw">
      <header className="aw-topbar">
        <span className="aw-wordmark">Ter<b>ra</b></span>
        <span className="label" style={{ marginLeft: ".2rem" }}>Command center</span>
        <span className="aw-sp" />
        <button className="aw-kbtn" onClick={() => setCmdOpen(true)}><Icon name="search" size={13} /> Jump / command <kbd>⌘K</kbd></button>
        <span className="aw-avatar" title={me.name ?? "Agent"}>{initials(me.name, me.role)}</span>
      </header>

      <div className="aw-main">
        <nav className="aw-rail" aria-label="Views">
          {nav.map((n) => (
            <button key={n.id} className={`aw-nav ${view === n.id ? "on" : ""}`} onClick={() => go(n.id)}>
              <Icon name={n.icon} size={16} /> <span className="navlabel">{n.label}</span>
              {n.count != null && n.count > 0 && <span className={`cnt ${n.hot ? "hot" : ""}`}>{n.count}</span>}
            </button>
          ))}
        </nav>

        <main className="aw-canvas">
          {view === "today" && (
            <>
              <StatsBar stats={stats} onStat={(k) =>
                k === "need" ? go("today") : k === "risk" ? go("pipeline", "at_risk") : k === "closing" ? go("pipeline", "closing") : go("pipeline")} />
              <div className="aw-h"><h1>Needs you today</h1>
                <button className="aw-btn aw-btn-g sm" disabled={drafting} onClick={() => void refreshCopilot()}>
                  <Icon name="sparkle" size={13} /> {drafting ? "Drafting…" : "Draft outreach"}
                </button>
              </div>
              <ApprovalQueue items={approvals} onApprove={approve} onDismiss={dismiss} onOpenDeal={openDeal} />
            </>
          )}

          {view === "pipeline" && (
            <PipelineView deals={deals} filter={pipeFilter} setFilter={setPipeFilter} onOpen={openDeal} />
          )}

          {view === "clients" && <ClientsView clients={clients} onOpen={openDeal} onDraftUpdate={draftClientUpdate} drafting={drafting} />}

          {view === "schedule" && <ScheduleView items={schedule} onOpen={openDeal} />}

          {view === "earnings" && <EarningsView data={earnings} onOpen={openDeal} />}

          {view === "activity" && (
            <>
              <div className="aw-h"><h1>What your co-pilot did</h1></div>
              <ActivityList activity={activity} onOpen={openDeal} full />
            </>
          )}

          {view === "radar" && <RadarView radar={radar} onOpen={openDeal} />}

          {err && <div className="aw-empty" style={{ marginTop: "1rem", color: "#7c3623" }}>{err}</div>}
        </main>

        <aside className="aw-panel" aria-label="Co-pilot activity">
          <div className="aw-h"><h2 style={{ fontSize: "1rem" }}>Co-pilot</h2></div>
          <div className="aw-weekly">
            <div className="box"><div className="n tnum">{weekly.handled}</div><div className="label">handled</div></div>
            <div className="box"><div className="n esc tnum">{weekly.escalated}</div><div className="label">escalated</div></div>
          </div>
          <div className="label" style={{ marginBottom: ".4rem" }}>Recent activity</div>
          <ActivityList activity={activity.slice(0, 24)} onOpen={openDeal} />
        </aside>
      </div>

      <nav className="aw-botnav" aria-label="Views">
        {nav.map((n) => (
          <button key={n.id} className={view === n.id ? "on" : ""} onClick={() => go(n.id)}>
            <Icon name={n.icon} size={18} />{n.label.split(" ")[0]}
            {n.count != null && n.count > 0 && <span className="cnt">{n.count}</span>}
          </button>
        ))}
      </nav>

      {detail && <DealOverlay detail={detail} onClose={() => setDetail(null)} />}
      {cmdOpen && <CommandPalette deals={deals} approvals={approvals} onClose={() => setCmdOpen(false)}
        onOpenDeal={openDeal} onGo={go} onRefresh={() => { setCmdOpen(false); void refreshCopilot(); }} />}
    </div>
  );
}

function StatsBar({ stats, onStat }: { stats: Portfolio["stats"]; onStat: (k: "active" | "need" | "risk" | "closing") => void }) {
  const cells: { k: "active" | "need" | "risk" | "closing"; n: number; l: string; alert?: boolean }[] = [
    { k: "active", n: stats.activeDeals, l: "active deals" },
    { k: "need", n: stats.needYouToday, l: "need you today", alert: stats.needYouToday > 0 },
    { k: "risk", n: stats.atRisk, l: "at risk", alert: stats.atRisk > 0 },
    { k: "closing", n: stats.closingThisWeek, l: "closing this week" },
  ];
  return (
    <div className="aw-stats">
      {cells.map((c) => (
        <button key={c.k} className={`aw-stat ${c.alert ? "alert" : ""}`} onClick={() => onStat(c.k)}>
          <div className="aw-stat-n">{c.n}</div><div className="aw-stat-l">{c.l}</div>
        </button>
      ))}
    </div>
  );
}

export function ApprovalQueue({ items, onApprove, onDismiss, onOpenDeal }: {
  items: ApprovalItem[]; onApprove: (i: ApprovalItem, body?: string) => void; onDismiss: (i: ApprovalItem) => void; onOpenDeal: (id: string) => void;
}) {
  return (
    <>
      <div className="aw-queue-note"><Icon name="shield" size={14} /> Your co-pilot drafts every outbound message. Nothing leaves without your review and approval.</div>
      {items.length === 0
        ? <div className="aw-empty">Queue clear — no drafts waiting. Use “Draft outreach” to have your co-pilot check the book.</div>
        : <div aria-live="polite">{items.map((it) => <ApprovalRow key={it.id} item={it} onApprove={onApprove} onDismiss={onDismiss} onOpenDeal={onOpenDeal} />)}</div>}
    </>
  );
}

function ApprovalRow({ item, onApprove, onDismiss, onOpenDeal }: {
  item: ApprovalItem; onApprove: (i: ApprovalItem, body?: string) => void; onDismiss: (i: ApprovalItem) => void; onOpenDeal: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(item.draftBody);
  return (
    <div className={`aw-appr ${item.urgency === "urgent" ? "urgent" : ""}`}>
      <div className="aw-appr-row">
        <span className="aw-ai-badge"><Icon name="sparkle" size={10} /> AI draft</span>
        <div className="aw-appr-title">
          <b>{item.title}</b>
          <span className="aw-appr-ctx">
            <button className="aw-btn aw-btn-d sm" style={{ padding: 0 }} onClick={() => onOpenDeal(item.dealId)}>{item.clientName}</button>
            {" · to "}{item.recipient.name} ({humanize(item.recipient.relationship)})
          </span>
        </div>
        {item.urgency === "urgent" && <span className="aw-risk at_risk"><Icon name="warning" size={11} /> Urgent</span>}
        <div className="aw-appr-actions">
          <button className="aw-btn aw-btn-g sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "Hide" : "Review"}</button>
          <button className="aw-btn aw-btn-d sm" onClick={() => onDismiss(item)}>Dismiss</button>
        </div>
      </div>
      {open && (
        <div className="aw-appr-body">
          <div className="aw-appr-to">To <b>{item.recipient.name}</b> · {humanize(item.recipient.relationship)} · {item.recipient.channel}</div>
          <div className="aw-why"><Icon name="sparkle" size={13} /><span><b>Why:</b> {item.reasoning}</span></div>
          {editing
            ? <textarea className="aw-draft" value={body} onChange={(e) => setBody(e.target.value)} aria-label="Edit draft body" />
            : <div className="aw-draft">{body}</div>}
          <div className="aw-appr-actions" style={{ marginTop: ".6rem" }}>
            <button className="aw-btn aw-btn-p" onClick={() => onApprove(item, editing ? body : undefined)}><Icon name="check" size={13} /> Approve &amp; send</button>
            <button className="aw-btn aw-btn-g" onClick={() => setEditing((e) => !e)}><Icon name="doc" size={13} /> {editing ? "Done editing" : "Edit"}</button>
            <button className="aw-btn aw-btn-d" onClick={() => onDismiss(item)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

type SortKey = "risk" | "close" | "stage";
function PipelineView({ deals, filter, setFilter, onOpen }: {
  deals: DealSummary[]; filter: PipeFilter; setFilter: (f: PipeFilter) => void; onOpen: (id: string) => void;
}) {
  const [sort, setSort] = useState<SortKey>("risk");
  const [drawer, setDrawer] = useState<string | null>(null);
  const rows = useMemo(() => {
    let r = deals.filter((d) =>
      filter === "all" ? true : filter === "at_risk" ? d.risk === "at_risk" : (d.closeDate != null && (daysTo(d.closeDate) ?? 99) <= 7 && (daysTo(d.closeDate) ?? -1) >= 0));
    r = [...r].sort((a, b) =>
      sort === "risk" ? RISK_RANK[b.risk] - RISK_RANK[a.risk] || (a.nextDeadline?.date ?? "9999").localeCompare(b.nextDeadline?.date ?? "9999")
      : sort === "close" ? (a.closeDate ?? "9999").localeCompare(b.closeDate ?? "9999")
      : a.stage.localeCompare(b.stage));
    return r;
  }, [deals, filter, sort]);
  const tabs: { k: PipeFilter; l: string }[] = [{ k: "all", l: "All" }, { k: "at_risk", l: "At risk" }, { k: "closing", l: "Closing soon" }];
  return (
    <>
      <div className="aw-h"><h1>Pipeline</h1><span className="muted">{rows.length} of {deals.length} deals</span></div>
      <div className="aw-tabs">{tabs.map((t) => <button key={t.k} className={`aw-tab ${filter === t.k ? "on" : ""}`} onClick={() => setFilter(t.k)}>{t.l}</button>)}</div>
      {rows.length === 0 ? <div className="aw-empty">No deals match this filter.</div> : (
        <div className="aw-tablewrap">
          <table className="aw-table">
            <thead><tr>
              <th onClick={() => setSort("risk")}>Client &amp; property</th>
              <th className="col-opt" onClick={() => setSort("stage")}>Stage</th>
              <th onClick={() => setSort("risk")}>Next deadline</th>
              <th className="col-opt" onClick={() => setSort("close")}>Close</th>
              <th></th>
            </tr></thead>
            <tbody>
              {rows.map((d) => (
                <RowGroup key={d.id} d={d} open={drawer === d.id} onToggle={() => setDrawer(drawer === d.id ? null : d.id)} onOpen={onOpen} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function RowGroup({ d, open, onToggle, onOpen }: { d: DealSummary; open: boolean; onToggle: () => void; onOpen: (id: string) => void }) {
  return (
    <>
      <tr className="click" onClick={onToggle}>
        <td><div className="aw-client">{d.clientName}</div><div className="aw-addr">{d.propertyAddress}</div></td>
        <td className="col-opt"><span className="aw-stage">{STAGE_LABEL[d.stage]}</span></td>
        <td>{d.nextDeadline ? <><RiskPill risk={d.nextDeadline.risk} date={d.nextDeadline.date} /><div className="aw-addr">{d.nextDeadline.label}</div></> : <span className="muted">—</span>}</td>
        <td className="col-opt tnum">{d.closeDate ? fmtDate(d.closeDate) : "—"}</td>
        <td style={{ textAlign: "right" }}><Icon name="chevron" size={14} style={{ transform: open ? "rotate(180deg)" : "none" }} /></td>
      </tr>
      {open && (
        <tr className="aw-drawer-row"><td colSpan={5}>
          <div className="aw-drawer">
            <div className="aw-peek"><b>EMD</b>{d.peek.emd}</div>
            <div className="aw-peek"><b>Loan</b>{d.peek.loan}</div>
            <div className="aw-peek"><b>Next</b>{d.peek.appraisalOrNext}</div>
            <button className="aw-btn aw-btn-p sm" style={{ marginLeft: "auto" }} onClick={() => onOpen(d.id)}>Open deal</button>
          </div>
        </td></tr>
      )}
    </>
  );
}

export function RadarView({ radar, onOpen }: { radar: Portfolio["radar"]; onOpen: (id: string) => void }) {
  const groups = useMemo(() => {
    const over: typeof radar = [], week: typeof radar = [], later: typeof radar = [];
    for (const r of radar) { const n = daysTo(r.date); if (n != null && n < 0) over.push(r); else if (n != null && n <= 14) week.push(r); else later.push(r); }
    return [
      { key: "over", label: "Overdue", icon: "warning" as IconName, items: over },
      { key: "week", label: "Next 14 days", icon: "clock" as IconName, items: week },
      { key: "later", label: "Later", icon: "calendar" as IconName, items: later },
    ];
  }, [radar]);
  return (
    <>
      <div className="aw-h"><h1>Deadline radar</h1><span className="muted">{radar.length} across your book</span></div>
      {radar.length === 0 && <div className="aw-empty">No deadlines on the horizon.</div>}
      {groups.filter((g) => g.items.length).map((g) => (
        <div className="aw-radar-grp" key={g.key}>
          <div className="label"><Icon name={g.icon} size={13} /> {g.label} · {g.items.length}</div>
          {g.items.map((r) => (
            <button key={r.id} className={`aw-radar-item ${r.risk}`} onClick={() => onOpen(r.dealId)} style={{ width: "100%", textAlign: "left" }}>
              <span className="aw-radar-date tnum">{fmtDate(r.date)}</span>
              <div className="aw-radar-main"><div>{r.label}</div><div className="aw-addr">{r.clientName} · {r.propertyAddress}</div></div>
              <RiskPill risk={r.risk} date={r.date} />
            </button>
          ))}
        </div>
      ))}
    </>
  );
}

function ClientsView({ clients, onOpen, onDraftUpdate, drafting }: {
  clients: ClientRow[] | null; onOpen: (id: string) => void; onDraftUpdate: (id: string) => void; drafting: boolean;
}) {
  if (clients === null) return <div className="aw-empty">Loading clients…</div>;
  return (
    <>
      <div className="aw-h"><h1>Clients</h1><span className="muted">{clients.length} — everything you recite when their name lights up</span></div>
      {clients.length === 0 ? <div className="aw-empty">No clients yet.</div> : clients.map((c) => (
        <div className="aw-card aw-cc" key={c.dealId}>
          <div className="aw-cc-top">
            <div>
              <div className="aw-client" style={{ fontSize: "1.05rem" }}>{c.clientName}</div>
              <div className="aw-addr">{c.propertyAddress}</div>
            </div>
            <div className="aw-cc-meta">
              <span className="aw-stage">{STAGE_LABEL[c.stage] ?? c.stage}</span>
              {c.priceCents != null && <span className="tnum" style={{ fontWeight: 650 }}>{usd(c.priceCents)}</span>}
              {c.financing && <span className="muted">{c.financing}</span>}
            </div>
          </div>

          <div className="aw-cc-row">
            {c.nextDeadline && (
              <span className="aw-cc-next">
                <RiskPill risk={c.nextDeadline.risk} date={c.nextDeadline.date} />
                <span className="aw-addr">{c.nextDeadline.label} · {fmtDate(c.nextDeadline.date)}</span>
              </span>
            )}
            {c.contingencies.length > 0 && (
              <span className="aw-cc-conts" title="Contingencies: removed vs active">
                {c.contingencies.map((x) => (
                  <span key={x.kind} className={`aw-cdot ${x.removed ? "done" : "open"}`}>
                    {x.removed ? "✓" : "○"} {x.label}
                  </span>
                ))}
              </span>
            )}
            {c.docTypes.length > 0 && (
              <span className="aw-cc-docs">
                {c.docTypes.slice(0, 4).map((d) => <span key={d} className="aw-doc-chip">{humanize(d)}</span>)}
              </span>
            )}
          </div>

          {c.talkingPoints.length > 0 && (
            <div className="aw-cc-talk">
              <div className="aw-cc-talk-h">Talking points — before you call</div>
              {c.talkingPoints.map((t) => (
                <div key={t.id} className="aw-cc-talk-row">
                  <span className={`dot ${t.mode}`} style={{ width: 6, height: 6, borderRadius: "50%", background: t.mode === "needs_you" ? "var(--ai)" : "var(--sage)", flex: "none", marginTop: 6 }} />
                  <span>{t.text}</span>
                  {t.occurredAt && <span className="aw-addr tnum" style={{ marginLeft: "auto", flex: "none" }}>{fmtDate(t.occurredAt).replace(/, \d{4}$/, "")}</span>}
                </div>
              ))}
            </div>
          )}

          <div className="aw-cc-actions">
            <button className="aw-btn aw-btn-p sm" disabled={drafting} onClick={() => onDraftUpdate(c.dealId)}>
              <Icon name="sparkle" size={12} /> {drafting ? "Drafting…" : "Draft client update"}
            </button>
            <button className="aw-btn aw-btn-g sm" onClick={() => onOpen(c.dealId)}>Open deal</button>
            {c.parties.filter((p) => p.phone).slice(0, 3).map((p) => (
              <a key={p.id} className="aw-btn aw-btn-g sm" href={`tel:${p.phone}`}>
                <Icon name="phone" size={11} /> {humanize(p.role).split(" ")[0]}
              </a>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function ScheduleView({ items, onOpen }: { items: ScheduleItem[] | null; onOpen: (id: string) => void }) {
  if (items === null) return <div className="aw-empty">Loading your schedule…</div>;
  const groups = new Map<string, ScheduleItem[]>();
  for (const it of items) {
    const key = (it.days ?? 99) < 0 ? "Overdue" : it.days === 0 ? "Today" : it.days === 1 ? "Tomorrow" : fmtDate(it.date);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(it);
  }
  return (
    <>
      <div className="aw-h"><h1>Schedule</h1><span className="muted">every dated obligation across the book, next 3 weeks</span></div>
      {items.length === 0 ? <div className="aw-empty">Nothing dated on the horizon.</div> :
        [...groups.entries()].map(([label, its]) => (
          <div key={label} className="aw-radar-grp">
            <div className={`label ${label === "Overdue" ? "" : ""}`} style={label === "Overdue" ? { color: "var(--clay)" } : label === "Today" ? { color: "var(--sage-deep)" } : undefined}>
              {label} · {its.length}
            </div>
            {its.map((it) => (
              <button key={`${it.kind}-${it.id}`} className={`aw-radar-item ${it.risk}`} style={{ width: "100%", textAlign: "left" }} onClick={() => onOpen(it.dealId)}>
                <span className="aw-radar-date"><Icon name={it.kind === "task" ? "checkCircle" : "calendar"} size={13} /></span>
                <div className="aw-radar-main">
                  <div>{it.label}</div>
                  <div className="aw-addr">{it.clientName} · {it.propertyAddress}</div>
                </div>
                <RiskPill risk={it.risk} date={it.date} />
              </button>
            ))}
          </div>
        ))}
    </>
  );
}

function EarningsView({ data, onOpen }: { data: EarningsData | null; onOpen: (id: string) => void }) {
  if (data === null) return <div className="aw-empty">Loading earnings…</div>;
  return (
    <>
      <div className="aw-h"><h1>Earnings</h1><span className="muted">{data.rateNote}</span></div>
      <div className="aw-stats" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <div className="aw-stat"><div className="aw-stat-n tnum">{usd(data.totals.inEscrowCents)}</div><div className="aw-stat-l">in escrow (est.)</div></div>
        <div className="aw-stat"><div className="aw-stat-n tnum">{usd(data.totals.closingSoonCents)}</div><div className="aw-stat-l">closing ≤ 30 days (est.)</div></div>
        <div className="aw-stat"><div className="aw-stat-n tnum">{usd(data.totals.closedCents)}</div><div className="aw-stat-l">closed (est.)</div></div>
      </div>
      {data.rows.length === 0 ? <div className="aw-empty">No priced deals yet.</div> : (
        <div className="aw-tablewrap">
          <table className="aw-table">
            <thead><tr><th>Client &amp; property</th><th className="col-opt">Stage</th><th>Price</th><th>Est. commission</th><th className="col-opt">Close</th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.dealId} className="click" onClick={() => onOpen(r.dealId)}>
                  <td><div className="aw-client">{r.clientName}</div><div className="aw-addr">{r.propertyAddress}</div></td>
                  <td className="col-opt"><span className="aw-stage">{STAGE_LABEL[r.stage] ?? r.stage}</span></td>
                  <td className="tnum">{usd(r.priceCents)}</td>
                  <td className="tnum" style={{ fontWeight: 650 }}>{usd(r.commissionEstCents)}</td>
                  <td className="col-opt tnum">{r.closeDate ? fmtDate(r.closeDate) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ fontSize: "var(--t-s, 12px)", marginTop: 8 }}>
        Estimates use a default buyer-side rate; your actual commission is set by your representation agreement. Display only — nothing here moves money.
      </p>
    </>
  );
}

export function ActivityList({ activity, onOpen, full }: { activity: Portfolio["activity"]; onOpen: (id: string) => void; full?: boolean }) {
  if (activity.length === 0) return <div className="aw-empty">No co-pilot activity yet.</div>;
  return (
    <ul className="aw-feed" aria-live="polite">
      {activity.map((a) => (
        <li key={a.id}>
          <span className={`dot ${a.mode}`} />
          <div style={{ flex: 1 }}>
            <div>{a.text}</div>
            <span className={`mtag ${a.mode}`}>{a.mode === "needs_you" ? "escalated · needs you" : "autonomous"}</span>
            {full && a.dealId && <> · <button className="aw-btn aw-btn-d sm" style={{ padding: 0 }} onClick={() => onOpen(a.dealId!)}>open deal</button></>}
            {a.occurredAt && <time>{fmtDate(a.occurredAt)}</time>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function DealOverlay({ detail, onClose }: { detail: DealDetail; onClose: () => void }) {
  const s = detail.summary;
  const KEY_FIELDS: [string, string][] = [
    ["purchase_price", "Purchase price"], ["initial_deposit_amount", "EMD"], ["loan_amount", "Loan"],
    ["financing_type", "Financing"], ["close_of_escrow", "Close of escrow"], ["acceptance_date", "Accepted"],
  ];
  return (
    <div className="aw-over" onClick={onClose}>
      <div className="aw-over-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={`Deal: ${s.clientName}`}>
        <div className="aw-over-top">
          <div><div className="aw-client" style={{ fontSize: "1.1rem" }}>{s.clientName}</div><div className="aw-addr">{s.propertyAddress}</div></div>
          <div style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
            <span className="aw-stage">{STAGE_LABEL[s.stage]}</span>
            <button className="aw-btn aw-btn-g sm" onClick={onClose}><Icon name="x" size={14} /></button>
          </div>
        </div>
        <div className="aw-over-body">
          <div>
            <div className="label" style={{ marginBottom: ".4rem" }}>Numbers</div>
            <div className="aw-kv">
              {KEY_FIELDS.filter(([k]) => detail.fields[k]).map(([k, l]) => (
                <div key={k}><div className="k">{l}</div><div className="v">{detail.fields[k]}</div></div>
              ))}
            </div>
          </div>
          <div>
            <div className="label" style={{ marginBottom: ".4rem" }}>Deadlines</div>
            <div className="aw-list">
              {detail.deadlines.length === 0 ? <div className="muted">None on file.</div> : detail.deadlines.map((d) => (
                <div className="aw-list-row" key={d.id}>
                  <span className="tnum aw-radar-date">{d.due_date ? fmtDate(d.due_date) : "—"}</span>
                  <div style={{ flex: 1 }}>{d.name}</div>
                  {d.due_date && <RiskPill risk={(daysTo(d.due_date) ?? 99) <= 2 ? "at_risk" : (daysTo(d.due_date) ?? 99) <= 7 ? "watch" : "ok"} date={d.due_date} />}
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="label" style={{ marginBottom: ".4rem" }}>Parties</div>
            <div className="aw-list">
              {detail.parties.map((p) => (
                <div className="aw-list-row" key={p.id}>
                  <span className="aw-avatar" style={{ width: 24, height: 24, fontSize: 10 }}>{initials(p.name, p.role)}</span>
                  <div style={{ flex: 1 }}><div>{p.name ?? humanize(p.role)}</div><div className="aw-addr">{humanize(p.role)}</div></div>
                  {p.phone && <a className="aw-btn aw-btn-g sm" href={`tel:${p.phone}`}><Icon name="phone" size={12} /> Call</a>}
                </div>
              ))}
            </div>
          </div>
          {detail.messages.length > 0 && (
            <div>
              <div className="label" style={{ marginBottom: ".4rem" }}>Co-pilot messages</div>
              <div className="aw-list">
                {detail.messages.map((m) => (
                  <div className="aw-list-row" key={m.id}>
                    <span className="aw-ai-badge"><Icon name="sparkle" size={10} /> AI</span>
                    <div style={{ flex: 1, minWidth: 0 }}><div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.subject}</div>{m.reasoning && <div className="aw-addr">{m.reasoning}</div>}</div>
                    <span className={`aw-risk ${m.status === "draft" ? "watch" : "ok"}`}>{m.status === "draft" ? "Draft" : humanize(m.status)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

type Cmd = { id: string; label: string; sub?: string; kind: string; run: () => void };
function CommandPalette({ deals, approvals, onClose, onOpenDeal, onGo, onRefresh }: {
  deals: DealSummary[]; approvals: ApprovalItem[]; onClose: () => void;
  onOpenDeal: (id: string) => void; onGo: (v: View, f?: PipeFilter) => void; onRefresh: () => void;
}) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const cmds = useMemo<Cmd[]>(() => {
    const base: Cmd[] = [
      { id: "c-risk", label: "Show everything at risk", kind: "view", run: () => { onGo("pipeline", "at_risk"); onClose(); } },
      { id: "c-today", label: `Go to Today (${approvals.length} to review)`, kind: "view", run: () => { onGo("today"); onClose(); } },
      { id: "c-radar", label: "Open the deadline radar", kind: "view", run: () => { onGo("radar"); onClose(); } },
      { id: "c-draft", label: "Draft outreach across the book", kind: "action", run: onRefresh },
    ];
    const dealCmds: Cmd[] = deals.map((d) => ({
      id: `d-${d.id}`, label: d.clientName, sub: d.propertyAddress, kind: "deal", run: () => onOpenDeal(d.id),
    }));
    const all = [...dealCmds, ...base];
    const t = q.trim().toLowerCase();
    return t ? all.filter((c) => (c.label + " " + (c.sub ?? "")).toLowerCase().includes(t)) : all;
  }, [q, deals, approvals.length, onGo, onClose, onOpenDeal, onRefresh]);

  useEffect(() => { setSel(0); }, [q]);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, cmds.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    if (e.key === "Enter") { e.preventDefault(); cmds[sel]?.run(); }
  };
  return (
    <div className="aw-cmdk" onClick={onClose}>
      <div className="aw-cmdk-box" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command palette">
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
          placeholder="Jump to a deal or client, or run a command…" aria-label="Command palette" />
        <div className="aw-cmdk-list">
          {cmds.length === 0 ? <div className="aw-empty" style={{ border: 0 }}>No matches.</div> : cmds.map((c, i) => (
            <button key={c.id} className={`aw-cmdk-item ${i === sel ? "on" : ""}`} onMouseEnter={() => setSel(i)} onClick={c.run}>
              <Icon name={c.kind === "deal" ? "board" : c.kind === "action" ? "sparkle" : "flag"} size={14} />
              <div><div>{c.label}</div>{c.sub && <div className="sub">{c.sub}</div>}</div>
              <span className="aw-cmdk-kind">{c.kind}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
