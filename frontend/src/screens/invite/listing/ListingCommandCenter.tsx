import { useCallback, useEffect, useMemo, useState } from "react";
import { fmtDate } from "../../../lib/format";
import { Icon, IconName } from "../../../lib/icons";
import { humanize, initials } from "../helpers";
import "../agent/agent.css";
import { usePoll } from "../shared/usePoll";
import { ActivityList, ApprovalQueue, DealOverlay, EarningsView, Greeting, RadarView, RiskPill, ScheduleView } from "../agent/AgentCommandCenter";
import { ApprovalItem, DealDetail, EarningsData, ScheduleItem } from "../agent/types";
import {
  BuyerSideHealth, LISTING_STATUS_LABEL, ListingPortfolio, ListingSummary,
  Offer, OfferComparison, SellerRow,
} from "./types";

type Papi = <T,>(path: string, init?: RequestInit) => Promise<T>;
type View = "today" | "listings" | "offers" | "sellers" | "schedule" | "earnings" | "activity" | "radar";
type Filter = "all" | "active" | "in_escrow" | "attention";

const usd = (c: number | null) => c == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(c / 100);
const MS_ICON: Record<BuyerSideHealth["milestones"][number]["state"], IconName> = { complete: "check", in_progress: "hourglass", pending: "clock", at_risk: "warning" };

export function ListingCommandCenter({ papi }: { papi: Papi }) {
  const [pf, setPf] = useState<ListingPortfolio | null>(null);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [sellers, setSellers] = useState<SellerRow[] | null>(null);
  const [schedule, setSchedule] = useState<ScheduleItem[] | null>(null);
  const [earnings, setEarnings] = useState<EarningsData | null>(null);
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [offerSel, setOfferSel] = useState<string | null>(null);
  const [offerData, setOfferData] = useState<OfferComparison | null>(null);
  const [view, setView] = useState<View>("today");
  const [filter, setFilter] = useState<Filter>("all");
  const [drafting, setDrafting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // One request loads the book AND the queue (the portfolio ships approvalItems).
  const loadAll = useCallback(async () => {
    try {
      const p = await papi<ListingPortfolio & { approvalItems?: ApprovalItem[] }>("/listing/portfolio");
      setPf(p);
      if (p.approvalItems) setApprovals(p.approvalItems);
    } catch (e) { setErr(e instanceof Error ? e.message : "Couldn't load your book."); }
  }, [papi]);
  useEffect(() => { void loadAll(); }, [loadAll]);
  usePoll(() => { void loadAll(); }); // §7 live-sync
  useEffect(() => {
    if (view === "sellers" && sellers === null) papi<{ sellers: SellerRow[] }>("/listing/sellers").then((d) => setSellers(d.sellers)).catch(() => setSellers([]));
    if (view === "schedule" && schedule === null) papi<{ items: ScheduleItem[] }>("/listing/schedule").then((d) => setSchedule(d.items)).catch(() => setSchedule([]));
    if (view === "earnings" && earnings === null) papi<EarningsData>("/listing/earnings").then(setEarnings).catch(() => setEarnings(null));
  }, [view, sellers, schedule, earnings, papi]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setDetail(null); };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openListing = useCallback(async (id: string) => {
    try { setDetail(await papi<DealDetail>(`/agent/deals/${id}`)); }
    catch (e) { setErr(e instanceof Error ? e.message : "Couldn't open that listing."); }
  }, [papi]);
  const openOffers = useCallback(async (id: string) => {
    setOfferSel(id); setView("offers"); setOfferData(null);
    try { setOfferData(await papi<OfferComparison>(`/listing/offers/${id}`)); }
    catch (e) { setErr(e instanceof Error ? e.message : "Couldn't load offers."); }
  }, [papi]);

  async function approve(item: ApprovalItem, editedBody?: string) {
    setApprovals((p) => p.filter((a) => a.id !== item.id));
    setPf((p) => p && { ...p, stats: { ...p.stats, needYouToday: Math.max(0, p.stats.needYouToday - 1) } });
    try { await papi(`/agent/approvals/${item.id}/approve`, { method: "POST", body: JSON.stringify({ transaction_id: item.dealId, body: editedBody ?? null }) }); }
    catch (e) { setErr(e instanceof Error ? e.message : "Approve failed."); void loadAll(); }
  }
  async function dismiss(item: ApprovalItem) {
    setApprovals((p) => p.filter((a) => a.id !== item.id));
    setPf((p) => p && { ...p, stats: { ...p.stats, needYouToday: Math.max(0, p.stats.needYouToday - 1) } });
    try { await papi(`/agent/approvals/${item.id}/dismiss`, { method: "POST", body: JSON.stringify({ transaction_id: item.dealId }) }); }
    catch (e) { setErr(e instanceof Error ? e.message : "Dismiss failed."); void loadAll(); }
  }
  async function draftComparison(listingId: string) {
    setDrafting(true); setErr(null);
    try { await papi(`/listing/offers/${listingId}/draft-comparison`, { method: "POST" }); await loadAll(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Co-pilot drafting is unavailable."); }
    finally { setDrafting(false); }
  }
  async function draftSellerUpdate(listingId: string) {
    setDrafting(true); setErr(null);
    try {
      await papi(`/listing/sellers/${listingId}/draft-update`, { method: "POST" });
      await loadAll();
      setView("today");
    } catch (e) { setErr(e instanceof Error ? e.message : "Drafting is unavailable right now."); }
    finally { setDrafting(false); }
  }
  async function refreshCopilot() {
    setDrafting(true); setErr(null);
    try { await papi("/agent/copilot/refresh", { method: "POST", body: JSON.stringify({ limit: 8 }) }); await loadAll(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Co-pilot drafting is unavailable."); }
    finally { setDrafting(false); }
  }

  if (!pf) return <div className="aw"><div className="aw-topbar"><span className="aw-wordmark">Ter<b>ra</b></span></div>
    <div style={{ padding: "2rem" }}><div className="aw-empty">{err ?? "Loading your listings…"}</div></div></div>;

  const { stats, listings, radar, activity, weekly, me } = pf;
  const withOffers = listings.filter((l) => l.offerCount > 0);
  const nav: { id: View; label: string; icon: IconName; count?: number; hot?: boolean; ai?: boolean }[] = [
    { id: "listings", label: "Listings", icon: "home" },
    { id: "today", label: "Today", icon: "inbox", count: stats.needYouToday, hot: stats.needYouToday > 0 },
    { id: "offers", label: "Offers", icon: "receipt", count: stats.offersToReview, ai: true },
    { id: "sellers", label: "Sellers", icon: "users" },
    { id: "schedule", label: "Schedule", icon: "calendar" },
    { id: "earnings", label: "Earnings", icon: "money" },
    { id: "activity", label: "AI activity", icon: "sparkle" },
    { id: "radar", label: "Deadline radar", icon: "flag" },
  ];

  return (
    <div className="aw">
      <header className="aw-topbar">
        <span className="aw-wordmark">Ter<b>ra</b></span>
        <span className="label" style={{ marginLeft: ".2rem" }}>Listing command center</span>
        <span className="aw-sp" />
        <span className="aw-avatar" title={me.name ?? "Agent"}>{initials(me.name, me.role)}</span>
      </header>

      <div className="aw-main">
        <nav className="aw-rail" aria-label="Views">
          {nav.map((n) => (
            <button key={n.id} className={`aw-nav ${view === n.id ? "on" : ""}`} onClick={() => setView(n.id)}>
              <Icon name={n.icon} size={16} /> <span className="navlabel">{n.label}</span>
              {n.count != null && n.count > 0 && <span className="cnt" style={n.ai ? { background: "var(--ai-bg)", color: "var(--ai)" } : n.hot ? { background: "var(--clay)", color: "#fff" } : undefined}>{n.count}</span>}
            </button>
          ))}
        </nav>

        <main className="aw-canvas">
          {view === "today" && (
            <>
              <Greeting name={me.name} stats={`${stats.liveListings} live listing${stats.liveListings === 1 ? "" : "s"} · ${stats.needYouToday} decision${stats.needYouToday === 1 ? "" : "s"} waiting on you`} />
              <ListingStats stats={stats} onStat={(k) => k === "offers" ? setView("offers") : k === "escrow" ? (setView("listings"), setFilter("in_escrow")) : k === "need" ? setView("today") : setView("listings")} />
              {withOffers.length > 0 && (
                <div className="aw-card" style={{ padding: ".7rem .8rem", marginBottom: "1rem", borderColor: "var(--ai-line)", background: "var(--ai-bg)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: ".5rem" }}>
                    <Icon name="receipt" size={15} style={{ color: "var(--ai)" }} />
                    <b style={{ color: "var(--ai)" }}>{withOffers.length} listing{withOffers.length > 1 ? "s have" : " has"} offers to present</b>
                    <button className="aw-btn aw-btn-g sm" style={{ marginLeft: "auto" }} onClick={() => openOffers(withOffers[0].id)}>Review offers</button>
                  </div>
                </div>
              )}
              <div className="aw-h"><h1>Needs you today</h1>
                <button className="aw-btn aw-btn-g sm" disabled={drafting} onClick={() => void refreshCopilot()}><Icon name="sparkle" size={13} /> {drafting ? "Drafting…" : "Draft outreach"}</button>
              </div>
              <ApprovalQueue items={approvals} onApprove={approve} onDismiss={dismiss} onOpenDeal={openListing} />
            </>
          )}

          {view === "listings" && <ListingsPipeline listings={listings} filter={filter} setFilter={setFilter} onOpen={openListing} onOffers={openOffers} />}

          {view === "offers" && (
            <OffersView listings={withOffers} selected={offerSel} data={offerData} onSelect={openOffers}
              onDraft={draftComparison} drafting={drafting} onOpenListing={openListing} />
          )}

          {view === "sellers" && <SellersView sellers={sellers} onOpen={openListing} onOffers={openOffers} onDraftUpdate={draftSellerUpdate} drafting={drafting} />}

          {view === "schedule" && <ScheduleView items={schedule} onOpen={openListing} />}

          {view === "earnings" && (
            <EarningsView
              data={earnings}
              onOpen={openListing}
              personHeader="Seller & property"
              totalsDefs={[["activeCents", "on market — potential (est.)"], ["inEscrowCents", "in escrow (est.)"], ["closedCents", "closed (est.)"]]}
            />
          )}
          {view === "activity" && (<><div className="aw-h"><h1>What your co-pilot did</h1></div><ActivityList activity={activity} onOpen={openListing} full /></>)}
          {view === "radar" && <RadarView radar={radar} onOpen={openListing} />}

          {err && <div className="aw-empty" style={{ marginTop: "1rem", color: "#7c3623" }}>{err}</div>}
        </main>

        <aside className="aw-panel" aria-label="Co-pilot activity">
          <div className="aw-h"><h2 style={{ fontSize: "1rem" }}>Co-pilot</h2></div>
          <div className="aw-weekly">
            <div className="box"><div className="n tnum">{weekly.handled}</div><div className="label">handled</div></div>
            <div className="box"><div className="n esc tnum">{weekly.escalated}</div><div className="label">escalated</div></div>
          </div>
          <div className="label" style={{ marginBottom: ".4rem" }}>Recent activity</div>
          <ActivityList activity={activity.slice(0, 24)} onOpen={openListing} />
        </aside>
      </div>

      <nav className="aw-botnav" aria-label="Views">
        {nav.slice(0, 5).map((n) => (
          <button key={n.id} className={view === n.id ? "on" : ""} onClick={() => setView(n.id)}>
            <Icon name={n.icon} size={18} />{n.label.split(" ")[0]}
            {n.count != null && n.count > 0 && <span className="cnt">{n.count}</span>}
          </button>
        ))}
      </nav>

      {detail && <DealOverlay detail={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function ListingStats({ stats, onStat }: { stats: ListingPortfolio["stats"]; onStat: (k: "live" | "offers" | "escrow" | "need") => void }) {
  const cells: { k: "live" | "offers" | "escrow" | "need"; n: number; l: string; ai?: boolean; alert?: boolean }[] = [
    { k: "live", n: stats.liveListings, l: "live listings" },
    { k: "offers", n: stats.offersToReview, l: "offers to review", ai: true },
    { k: "escrow", n: stats.inEscrow, l: "in escrow" },
    { k: "need", n: stats.needYouToday, l: "need you today", alert: stats.needYouToday > 0 },
  ];
  return (
    <div className="aw-stats">
      {cells.map((c) => (
        <button key={c.k} className={`aw-stat ${c.alert ? "alert" : ""}`} onClick={() => onStat(c.k)}>
          <div className="aw-stat-n" style={c.ai ? { color: "var(--ai)" } : undefined}>{c.n}</div><div className="aw-stat-l">{c.l}</div>
        </button>
      ))}
    </div>
  );
}

function ListingsPipeline({ listings, filter, setFilter, onOpen, onOffers }: {
  listings: ListingSummary[]; filter: Filter; setFilter: (f: Filter) => void; onOpen: (id: string) => void; onOffers: (id: string) => void;
}) {
  const [drawer, setDrawer] = useState<string | null>(null);
  const rows = useMemo(() => listings.filter((l) =>
    filter === "all" ? true : filter === "active" ? l.status === "active" : filter === "in_escrow" ? l.status === "in_escrow" : l.risk === "at_risk"), [listings, filter]);
  const tabs: { k: Filter; l: string }[] = [{ k: "all", l: "All" }, { k: "active", l: "On market" }, { k: "in_escrow", l: "In escrow" }, { k: "attention", l: "Needs attention" }];
  return (
    <>
      <div className="aw-h"><h1>Listings</h1><span className="muted">{rows.length} of {listings.length}</span></div>
      <div className="aw-tabs">{tabs.map((t) => <button key={t.k} className={`aw-tab ${filter === t.k ? "on" : ""}`} onClick={() => setFilter(t.k)}>{t.l}</button>)}</div>
      {rows.length === 0 ? <div className="aw-empty">No listings match this filter.</div> : (
        <div className="aw-tablewrap">
          <table className="aw-table">
            <thead><tr><th>Property &amp; seller</th><th className="col-opt">Status</th><th>Signal</th><th className="col-opt">List / close</th><th></th></tr></thead>
            <tbody>
              {rows.map((l) => (
                <ListingRow key={l.id} l={l} open={drawer === l.id} onToggle={() => setDrawer(drawer === l.id ? null : l.id)} onOpen={onOpen} onOffers={onOffers} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function ListingRow({ l, open, onToggle, onOpen, onOffers }: { l: ListingSummary; open: boolean; onToggle: () => void; onOpen: (id: string) => void; onOffers: (id: string) => void }) {
  const stale = l.status === "active" && (l.daysOnMarket ?? 0) > 30;
  return (
    <>
      <tr className="click" onClick={onToggle}>
        <td><div className="aw-client">{l.propertyAddress}</div><div className="aw-addr">{l.sellerName}</div></td>
        <td className="col-opt"><span className="aw-stage">{LISTING_STATUS_LABEL[l.status]}</span></td>
        <td>
          {l.status === "active"
            ? <span className={`aw-risk ${stale ? "at_risk" : "ok"}`}><Icon name={stale ? "warning" : "clock"} size={11} /> {l.daysOnMarket}d on market{stale ? " · stale" : ""}</span>
            : l.nextDeadline ? <><RiskPill risk={l.nextDeadline.risk} date={l.nextDeadline.date} /><div className="aw-addr">{l.nextDeadline.label}</div></> : <span className="muted">—</span>}
        </td>
        <td className="col-opt tnum">{l.status === "active" ? usd(l.listPriceCents) : l.closeDate ? fmtDate(l.closeDate) : "—"}</td>
        <td style={{ textAlign: "right" }}><Icon name="chevron" size={14} style={{ transform: open ? "rotate(180deg)" : "none" }} /></td>
      </tr>
      {open && (
        <tr className="aw-drawer-row"><td colSpan={5}>
          <div className="aw-drawer">
            <div className="aw-peek"><b>{l.status === "active" ? "List" : "EMD"}</b>{l.peek.line1.replace(/^(List|EMD) /, "")}</div>
            <div className="aw-peek"><b>{l.status === "active" ? "Offers" : "Loan"}</b>{l.peek.line2}</div>
            <div className="aw-peek"><b>{l.status === "active" ? "DOM" : "Next"}</b>{l.peek.line3}</div>
            {l.offerCount > 0 && <button className="aw-btn aw-btn-p sm" onClick={() => onOffers(l.id)}><Icon name="receipt" size={12} /> Review offers</button>}
            <button className="aw-btn aw-btn-g sm" style={{ marginLeft: l.offerCount > 0 ? 0 : "auto" }} onClick={() => onOpen(l.id)}>Open listing</button>
          </div>
        </td></tr>
      )}
    </>
  );
}

function OffersView({ listings, selected, data, onSelect, onDraft, drafting, onOpenListing }: {
  listings: ListingSummary[]; selected: string | null; data: OfferComparison | null;
  onSelect: (id: string) => void; onDraft: (id: string) => void; drafting: boolean; onOpenListing: (id: string) => void;
}) {
  if (listings.length === 0) return (<><div className="aw-h"><h1>Offers</h1></div><div className="aw-empty">No listings have offers to present right now.</div></>);
  const sel = selected ?? listings[0].id;
  return (
    <>
      <div className="aw-h"><h1>Offers to present</h1><span className="muted">{listings.length} listing{listings.length > 1 ? "s" : ""}</span></div>
      <div className="aw-tabs" style={{ flexWrap: "wrap" }}>
        {listings.map((l) => <button key={l.id} className={`aw-tab ${sel === l.id ? "on" : ""}`} onClick={() => onSelect(l.id)}>{l.propertyAddress.split(",")[0]} · {l.offerCount}</button>)}
      </div>
      {!data ? <div className="aw-empty">Loading offers…</div> : <OfferComparisonBlock data={data} onDraft={() => onDraft(sel)} drafting={drafting} onOpenListing={() => onOpenListing(sel)} />}
    </>
  );
}

function OfferComparisonBlock({ data, onDraft, drafting, onOpenListing }: { data: OfferComparison; onDraft: () => void; drafting: boolean; onOpenListing: () => void }) {
  const hasSample = data.offers.some((o) => o.sample);
  const meter = data.buyerHealth.meter;
  return (
    <>
      {hasSample && <div className="aw-offers-banner"><Icon name="sparkle" size={13} /> Illustrative comparison — the SOR holds one accepted offer for this listing; sample competing offers are shown to demonstrate the present-to-seller workflow.</div>}
      <div className="aw-offers" role="list" aria-label="Offers">
        {data.offers.map((o) => <OfferCard key={o.id} o={o} />)}
      </div>
      <div className="aw-offer-pick">
        <button className="aw-btn aw-btn-p" disabled={drafting} onClick={onDraft}><Icon name="sparkle" size={13} /> {drafting ? "Drafting…" : "Draft comparison for seller"}</button>
        <button className="aw-btn aw-btn-g" onClick={onOpenListing}>Open listing</button>
        <span className="muted" style={{ fontSize: 12 }}>You present the tradeoffs; your seller decides. Nothing sends without your approval.</span>
      </div>

      <div className="aw-h" style={{ marginTop: "1.2rem" }}>
        <h2 style={{ fontSize: "1rem" }}>Buyer-side health · will it close?</h2>
        <span className={`aw-risk ${meter === "on_track" ? "ok" : meter}`}><Icon name={meter === "on_track" ? "check" : meter === "watch" ? "clock" : "warning"} size={11} /> {meter === "on_track" ? "On track" : meter === "watch" ? "Watch" : "At risk"}</span>
      </div>
      <div className="aw-card" style={{ padding: ".3rem .8rem" }}>
        {data.buyerHealth.milestones.map((m) => (
          <div className="aw-list-row" key={m.id} style={{ cursor: "default" }}>
            <span className={`aw-ms-ic ${m.state}`} style={{ width: 20, height: 20 }}><Icon name={MS_ICON[m.state]} size={11} /></span>
            <div style={{ flex: 1 }}>{m.label}{m.detail && <div className="aw-addr">{m.detail}</div>}</div>
          </div>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: ".4rem" }}>Read-only — these are the buyer's steps. Shown so you can answer “will it close?” for your seller.</p>
    </>
  );
}

function OfferCard({ o }: { o: Offer }) {
  const dims: [string, string, string][] = [
    ["Financing", humanize(o.financing), o.strength === "strong" ? "strong" : o.strength === "weak" ? "weak" : ""],
    ["Down", o.downPaymentPct != null ? `${o.downPaymentPct}%` : "—", (o.downPaymentPct ?? 0) >= 20 ? "strong" : ""],
    ["Contingencies", o.contingencies, /none/i.test(o.contingencies) ? "strong" : /full/i.test(o.contingencies) ? "weak" : ""],
    ["Close", `${o.closeDays}d`, o.closeDays <= 21 ? "strong" : o.closeDays >= 45 ? "weak" : ""],
  ];
  return (
    <div className={`aw-offer ${o.strength}`} role="listitem">
      <div className="aw-offer-agent"><Icon name="user" size={12} /> {o.buyerAgentName}{o.sample && <span className="aw-sample">sample</span>}</div>
      <div className="aw-offer-price">{usd(o.priceCents)}</div>
      {o.tradeoffTag && <span className="aw-offer-tag">{o.tradeoffTag}</span>}
      {dims.map(([k, v, cls]) => <div className="aw-offer-dim" key={k}><span className="k">{k}</span><span className={`v ${cls}`}>{v}</span></div>)}
      {o.netToSellerEstimateCents != null && <div className="aw-offer-net">Est. net to seller {usd(o.netToSellerEstimateCents)}</div>}
    </div>
  );
}

function SellersView({ sellers, onOpen, onOffers, onDraftUpdate, drafting }: {
  sellers: SellerRow[] | null; onOpen: (id: string) => void; onOffers: (id: string) => void;
  onDraftUpdate: (id: string) => void; drafting: boolean;
}) {
  if (sellers === null) return <div className="aw-empty">Loading sellers…</div>;
  const STATUS: Record<string, string> = { pre_market: "Pre-market", active: "Active", in_escrow: "In escrow", closed: "Closed" };
  return (
    <>
      <div className="aw-h"><h1>Sellers</h1><span className="muted">{sellers.length} — everything you recite when they call asking "so… what's happening?"</span></div>
      {sellers.length === 0 ? <div className="aw-empty">No sellers yet.</div> : sellers.map((c) => (
        <div className="aw-card aw-cc" key={c.listingId}>
          <div className="aw-cc-top">
            <div>
              <div className="aw-client" style={{ fontSize: "1.05rem" }}>{c.sellerName}</div>
              <div className="aw-addr">{c.propertyAddress}</div>
            </div>
            <div className="aw-cc-meta">
              <span className="aw-stage">{STATUS[c.status] ?? c.status}</span>
              {c.daysOnMarket != null && (
                <span className={`aw-risk ${c.daysOnMarket > 30 ? "at_risk" : "ok"}`}>
                  {c.daysOnMarket}d on market{c.daysOnMarket > 30 ? " · stale" : ""}
                </span>
              )}
              {c.priceCents != null && <span className="tnum" style={{ fontWeight: 650 }}>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(c.priceCents / 100)}</span>}
            </div>
          </div>

          <div className="aw-cc-row">
            {c.offerCount > 0 && (
              <button className="aw-btn aw-btn-p sm" onClick={() => onOffers(c.listingId)}>
                <Icon name="receipt" size={12} /> {c.offerCount} offers to present
              </button>
            )}
            {c.nextDeadline && (
              <span className="aw-cc-next">
                <RiskPill risk={c.nextDeadline.risk} date={c.nextDeadline.date} />
                <span className="aw-addr">{c.nextDeadline.label}</span>
              </span>
            )}
            {c.disclosures.length > 0 && (
              <span className="aw-cc-conts" title="Disclosure delivery — the listing agent's liability clock">
                {c.disclosures.map((x) => (
                  <span key={x.kind} className={`aw-cdot ${x.delivered ? "done" : "open"}`}>
                    {x.delivered ? "✓" : "○"} {x.kind.toUpperCase()}
                  </span>
                ))}
              </span>
            )}
          </div>

          {c.pulse && (
            <div className="aw-cc-row" style={{ marginTop: 0 }}>
              <span className="aw-addr">
                Activity this week: <b>{c.pulse.showings}</b> showings · <b>{c.pulse.views}</b> views · <b>{c.pulse.saves}</b> saves
                <span className="aw-sample" style={{ marginLeft: 6 }}>sample</span>
              </span>
            </div>
          )}

          {c.talkingPoints.length > 0 && (
            <div className="aw-cc-talk">
              <div className="aw-cc-talk-h">Talking points — before you pick up</div>
              {c.talkingPoints.map((t) => (
                <div key={t.id} className="aw-cc-talk-row">
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: t.mode === "needs_you" ? "var(--ai)" : "var(--sage)", flex: "none", marginTop: 6 }} />
                  <span>{t.text}</span>
                  {t.occurredAt && <span className="aw-addr tnum" style={{ marginLeft: "auto", flex: "none" }}>{fmtDate(t.occurredAt).replace(/, \d{4}$/, "")}</span>}
                </div>
              ))}
            </div>
          )}

          <div className="aw-cc-actions">
            <button className="aw-btn aw-btn-p sm" disabled={drafting} onClick={() => onDraftUpdate(c.listingId)}>
              <Icon name="sparkle" size={12} /> {drafting ? "Drafting…" : "Draft seller update"}
            </button>
            <button className="aw-btn aw-btn-g sm" onClick={() => onOpen(c.listingId)}>Open listing</button>
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

