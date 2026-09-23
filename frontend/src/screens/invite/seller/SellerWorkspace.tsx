import { useEffect, useMemo, useState } from "react";
import { fmtDate } from "../../../lib/format";
import { Icon, IconName } from "../../../lib/icons";
import "../buyer/buyer.css";
import { Define } from "../buyer/TapToDefine";
import { countdown, daysTo, humanize, initials, isDone } from "../helpers";
import { Task, Workspace } from "../types";
import "./seller.css";
import { BuyerMilestone, Disclosure, DisclosureState, NetSheet, SellerPhase } from "./types";
import { buildSaleDeal, usd } from "./useSellerDeal";

type Props = {
  ws: Workspace;
  papi: <T,>(path: string, init?: RequestInit) => Promise<T>;
  reload: () => Promise<void> | void;
  busy: boolean;
  cycle: (t: Task) => void;
};

const PHASES: { key: SellerPhase; label: string }[] = [
  { key: "offer", label: "Offer accepted" },
  { key: "escrow_open", label: "Escrow opened" },
  { key: "disclosures", label: "Disclosures" },
  { key: "buyer_contingencies", label: "Buyer contingencies" },
  { key: "closing", label: "Closing" },
  { key: "closed", label: "Sold" },
];
const MS_ICON: Record<BuyerMilestone["state"], IconName> = { complete: "check", in_progress: "hourglass", pending: "clock", at_risk: "warning" };
const DISCLOSURE_TERMS: Record<string, string[]> = {
  tds: ["TDS", "disclosure"], spq: ["SPQ", "disclosure"], nhd: ["NHD", "disclosure"],
  lead_paint: ["disclosure"], mello_roos: ["Mello-Roos"], other: ["disclosure"],
};
const DISCLOSURE_PILL: Record<DisclosureState, { cls: string; text: string }> = {
  draft: { cls: "warn", text: "To deliver" }, completed: { cls: "warn", text: "Ready to deliver" },
  delivered: { cls: "done", text: "Delivered" }, acknowledged: { cls: "done", text: "Acknowledged" },
};
const prefersReduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export function SellerWorkspace({ ws, papi, reload, busy, cycle }: Props) {
  const deal = useMemo(() => buildSaleDeal(ws), [ws]);
  const s = deal.summary;
  const escrowPhone = deal.team.find((m) => m.role === "escrow")?.phone
    ?? deal.team.find((m) => m.role === "title")?.phone ?? null;
  const moveOut = {
    walkthrough: ws.deadlines.find((d) => /walk/i.test(d.name)) ?? null,
    close: ws.deadlines.find((d) => /escrow|clos/i.test(d.name)) ?? null,
    possession: ws.deadlines.find((d) => /possession/i.test(d.name)) ?? null,
  };
  // Team split: the people working FOR the seller vs everyone else; hide self.
  const myTeam = deal.team.filter((m) => SELLER_TEAM_ROLES.has(m.role));
  const others = deal.team.filter(
    (m) => !SELLER_TEAM_ROLES.has(m.role) && !(m.name === ws.me.name && m.role === ws.me.role),
  );
  const setView_go = (id: string) => { document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); };

  const nav = useMemo(
    () => [
      { id: "sw-overview", label: "Overview", icon: "board" as IconName },
      { id: "sw-health", label: "Deal health", icon: "flag" as IconName },
      { id: "sw-home", label: "Your home", icon: "home" as IconName },
      { id: "sw-disclosures", label: "Disclosures", icon: "doc" as IconName },
      ...(deal.netSheet ? [{ id: "sw-proceeds", label: "Proceeds", icon: "money" as IconName }] : []),
      { id: "sw-requests", label: "Requests", icon: "inbox" as IconName },
      { id: "sw-moveout", label: "Move-out", icon: "key" as IconName },
    ],
    [deal.netSheet],
  );
  const [active, setActive] = useState(nav[0].id);
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (vis) setActive(vis.target.id);
      },
      { rootMargin: "-72px 0px -55% 0px", threshold: 0 },
    );
    nav.forEach((n) => { const el = document.getElementById(n.id); if (el) obs.observe(el); });
    return () => obs.disconnect();
  }, [nav]);
  const goTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: prefersReduced() ? "auto" : "smooth", block: "start" });
    setActive(id);
  };

  return (
    <div className="bw">
      <header className="bw-topbar">
        {s.heroPhotoUrl
          ? <img className="bw-home-thumb" src={s.heroPhotoUrl} alt="" />
          : <span className="bw-home-thumb"><Icon name="home" size={18} /></span>}
        <span className="bw-top-addr">{s.propertyAddress}</span>
        <span className="bw-tag">Selling</span>
        <span className="bw-top-sp" />
        <span className="bw-avatar" title={ws.me.name ?? "You"}>{initials(ws.me.name, ws.me.role)}</span>
      </header>

      <div className="bw-main">
        <nav className="bw-rail" aria-label="Sections">
          <div className="bw-rail-group">
            <div className="section-label">Your sale</div>
            {nav.map((n) => (
              <button key={n.id} type="button" className={`bw-nav ${active === n.id ? "on" : ""}`} onClick={() => goTo(n.id)}>
                <Icon name={n.icon} size={17} /> <span className="bw-nav-label">{n.label}</span>
              </button>
            ))}
          </div>
        </nav>

        <main className="bw-canvas">
          {/* Overview — proceeds + will-it-close, above the fold */}
          <section id="sw-overview" className="bw-sec" style={{ scrollMarginTop: 72 }}>
            <div className="bw-hero" style={s.heroPhotoUrl ? { backgroundImage: `url(${s.heroPhotoUrl})` } : undefined}>
              {!s.heroPhotoUrl && <div className="bw-hero-ph"><Icon name="home" size={34} /></div>}
              {s.photoCount > 0 && <span className="bw-photos">{s.photoCount} photo</span>}
              <div className="bw-hero-scrim" />
              <div className="bw-hero-cap">
                <div>
                  <div className="bw-hero-eyebrow">You're selling</div>
                  <div className="bw-hero-addr">{s.propertyAddress}</div>
                </div>
                <div className="bw-hero-chips">
                  {s.estimatedNetProceedsCents != null && (
                    <div>
                      <div className="bw-chip-n">{usd(s.estimatedNetProceedsCents)}</div>
                      <div className="bw-chip-l">est. proceeds</div>
                    </div>
                  )}
                  {s.daysToClose != null && s.daysToClose >= 0 ? (
                    <div>
                      <div className="bw-chip-n small">{s.daysToClose}</div>
                      <div className="bw-chip-l">{s.daysToClose === 1 ? "day to close" : "days to close"}</div>
                    </div>
                  ) : s.closeDate ? (
                    <div>
                      <div className="bw-chip-n small" style={{ fontSize: "1.05rem", lineHeight: 1.3 }}>{fmtDate(s.closeDate).replace(/, \d{4}$/, "")}</div>
                      <div className="bw-chip-l">{s.phase === "closed" ? "sold" : "closing date"}</div>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
            <StatusLine level={s.status.level} detail={s.status.nextActionLabel} />

            {/* The seller's loop, made literal: will it close · what do I walk
                away with · when do I hand over the keys. */}
            <div className="bw-answers" aria-label="Your three answers">
              <button type="button" className="bw-ans" onClick={() => setView_go("sw-health")}>
                <span className="bw-ans-k">Will it close?</span>
                <span className="bw-ans-v">
                  {deal.dealHealth ? (deal.dealHealth.meter === "on_track" ? <><Icon name="checkCircle" size={13} /> On track</> : deal.dealHealth.meter === "watch" ? "Watch closely" : "At risk") : "—"}
                </span>
              </button>
              <button type="button" className="bw-ans" onClick={() => setView_go(deal.netSheet ? "sw-proceeds" : "sw-health")}>
                <span className="bw-ans-k">What do I walk away with?</span>
                <span className="bw-ans-v">{deal.netSheet ? `${usd(deal.netSheet.estimatedNetProceedsCents)} est.` : "—"}</span>
              </button>
              <button type="button" className="bw-ans" onClick={() => setView_go("sw-moveout")}>
                <span className="bw-ans-k">When do I move out?</span>
                <span className="bw-ans-v">{moveOut.possession?.due_date ? fmtDate(moveOut.possession.due_date).replace(/, \d{4}$/, "") : moveOut.close?.due_date ? fmtDate(moveOut.close.due_date).replace(/, \d{4}$/, "") : "With closing"}</span>
              </button>
            </div>
          </section>

          {/* Deal health — the seller-specific monitor, read-only + inert */}
          <section id="sw-health" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }} aria-label="Deal health">
            <div className="bw-health-top">
              <h2>Will this deal close?</h2>
              {deal.dealHealth && <span className={`bw-meter ${deal.dealHealth.meter}`}>{deal.dealHealth.meter === "on_track" ? "On track" : deal.dealHealth.meter === "watch" ? "Watch" : "At risk"}</span>}
            </div>
            <PhaseTimeline phase={s.phase} />
            <p className="bw-now">{SELLER_NOW[s.phase]}</p>
            <p className="bw-inert-note" style={{ marginTop: ".8rem" }}>These are the buyer's steps, shown so you always know where the deal stands.</p>
            {!deal.dealHealth || deal.dealHealth.milestones.length === 0
              ? <div className="bw-empty">The buyer's progress will appear here as escrow moves.</div>
              : (
                <ul style={{ listStyle: "none", margin: 0, padding: 0 }} aria-label="Buyer progress" aria-live="polite">
                  {deal.dealHealth.milestones.map((m) => (
                    <li className="bw-ms" key={m.id}>
                      <span className={`bw-ms-ic ${m.state}`}><Icon name={MS_ICON[m.state]} size={12} /></span>
                      <div className="bw-ms-l">{m.label}{m.detail && <div className="bw-ms-detail">{m.detail}</div>}</div>
                    </li>
                  ))}
                </ul>
              )}
          </section>

          {/* The home they're selling — framed for leaving it, not falling for it */}
          <SellerHomeSection ws={ws} />

          {/* Disclosures — the seller's spine */}
          <section id="sw-disclosures" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
            <h2>Your disclosure obligations</h2>
            <p className="muted" style={{ margin: "-.3rem 0 .8rem", fontSize: 13 }}>
              California requires you to disclose what you know about the home. Delivering these fully and on time protects you after the sale.
            </p>
            {deal.disclosures.length === 0
              ? <div className="bw-empty">Your required disclosures will be listed here.</div>
              : deal.disclosures.map((d) => (
                  <DisclosureCard key={d.id} d={d} papi={papi} reload={reload} />
                ))}
          </section>

          {/* Net proceeds — the seller's money core */}
          {deal.netSheet && (
            <section id="sw-proceeds" className="bw-sec" style={{ scrollMarginTop: 72 }}>
              <NetProceeds net={deal.netSheet} escrowPhone={escrowPhone} papi={papi} reload={reload} />
            </section>
          )}

          {/* Requests — the seller's high-stakes decisions */}
          <section id="sw-requests" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
            <h2>Requests from the buyer</h2>
            {deal.requests.length === 0
              ? <div className="bw-empty">No requests from the buyer yet. If they ask for repairs or a credit after their inspection, it will appear here with its impact on your proceeds.</div>
              : deal.requests.map((r) => (
                  <RequestCard key={r.id} r={r} currentProceeds={deal.netSheet?.estimatedNetProceedsCents ?? 0} />
                ))}
          </section>

          {/* Move-out runway — the seller's endpoint: walkthrough, closing, keys */}
          <MoveOutSection moveOut={moveOut} possessionTerms={ws.fields.possession_date ?? null} />

          {/* Tasks */}
          <section className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
            <h2>Just your to-dos</h2>
            {ws.my_tasks.length === 0
              ? <div className="bw-empty">Nothing needs you right now.</div>
              : ws.my_tasks.map((t) => <SellerTaskRow key={t.id} t={t} busy={busy} cycle={cycle} />)}
          </section>
        </main>

        <aside className="bw-aside" aria-label="Your team and activity">
          <div className="bw-card">
            <h2>Your team</h2>
            <p className="muted" style={{ margin: "-.3rem 0 .5rem", fontSize: 12.5 }}>The people working for you on this sale.</p>
            {myTeam.length === 0
              ? <div className="bw-empty">Your team will appear here.</div>
              : myTeam.map((m, i) => (
                  <div className="bw-member" key={m.id ?? i}>
                    <span className="bw-member-ava">{initials(m.name, m.role)}</span>
                    <div style={{ minWidth: 0 }}>
                      <div className="bw-member-name">{m.name ?? humanize(m.role)}</div>
                      <div className="bw-member-role">{humanize(m.role)}</div>
                    </div>
                    {m.phone && <a className="bw-call" href={`tel:${m.phone}`}><Icon name="phone" size={12} /> Call</a>}
                  </div>
                ))}
            {others.length > 0 && (
              <>
                <div className="bw-team-sub">Also on this deal</div>
                {others.map((m, i) => (
                  <div className="bw-member quiet" key={m.id ?? `o${i}`}>
                    <span className="bw-member-ava">{initials(m.name, m.role)}</span>
                    <div style={{ minWidth: 0 }}>
                      <div className="bw-member-name">{m.name ?? humanize(m.role)}</div>
                      <div className="bw-member-role">{humanize(m.role)}</div>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
          <div className="bw-card">
            <h2>Recent activity</h2>
            {deal.activity.length === 0
              ? <div className="bw-empty">Updates on your sale will show up here.</div>
              : (
                <ul className="bw-activity" aria-live="polite">
                  {deal.activity.map((a) => (
                    <li key={a.id}><span className="bw-act-dot" /><div>{a.text}{a.occurredAt && <time>{fmtDate(a.occurredAt)}</time>}</div></li>
                  ))}
                </ul>
              )}
          </div>
        </aside>
      </div>

      <nav className="bw-botnav" aria-label="Sections">
        {nav.map((n) => (
          <button key={n.id} type="button" className={active === n.id ? "on" : ""} onClick={() => goTo(n.id)}>
            <Icon name={n.icon} size={18} /> {n.label}
          </button>
        ))}
      </nav>
    </div>
  );
}

function StatusLine({ level, detail }: { level: "on_track" | "action_soon" | "at_risk"; detail: string }) {
  const meta: Record<string, { icon: IconName; head: string }> = {
    on_track: { icon: "shield", head: "On track to close" },
    action_soon: { icon: "clock", head: "Something needs you" },
    at_risk: { icon: "warning", head: "The deal needs attention" },
  };
  const m = meta[level];
  return (
    <div className={`bw-status ${level}`} role="status">
      <span className="bw-status-ic"><Icon name={m.icon} size={18} /></span>
      <span><b>{m.head}</b> · {detail}</span>
    </div>
  );
}

function PhaseTimeline({ phase }: { phase: SellerPhase }) {
  const cur = PHASES.findIndex((p) => p.key === phase);
  return (
    <div className="bw-phases" role="list">
      {PHASES.map((p, i) => (
        <div key={p.key} className={`bw-phase ${i < cur ? "done" : i === cur ? "current" : "future"}`} role="listitem">
          <span className="bw-phase-dot">{i < cur ? <Icon name="check" size={12} /> : i + 1}</span>
          <span className="bw-phase-lbl">{p.label}</span>
        </div>
      ))}
    </div>
  );
}

function SellerTaskRow({ t, busy, cycle }: { t: Task; busy: boolean; cycle: (t: Task) => void }) {
  const done = isDone(t.status);
  const n = daysTo(t.due_date);
  const urg = done ? "later" : n != null && n <= 2 ? "now" : n != null && n <= 7 ? "soon" : "later";
  return (
    <div className={`bw-task ${done ? "done" : ""}`}>
      <button type="button" className={`bw-check ${done ? "done" : ""}`} disabled={busy} aria-pressed={done}
        aria-label={done ? `Mark "${t.title}" not done` : `Mark "${t.title}" done`} onClick={() => cycle(t)}>
        {done && <Icon name="check" size={13} />}
      </button>
      <div className="bw-task-l">
        {t.title}
        {t.due_date && <div className="bw-task-due">Due {fmtDate(t.due_date)}{n != null && !done ? ` · ${countdown(n)}` : ""}</div>}
      </div>
      {!done && urg !== "later" && <span className={`bw-urg ${urg}`}>{urg === "now" ? "Soon" : "This week"}</span>}
    </div>
  );
}

function DisclosureCard({ d, papi, reload }: { d: Disclosure; papi: Props["papi"]; reload: Props["reload"] }) {
  const [open, setOpen] = useState(false);
  const [attesting, setAttesting] = useState(false);
  const [checked, setChecked] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const delivered = d.state === "delivered" || d.state === "acknowledged";
  const pill = DISCLOSURE_PILL[d.state];

  async function confirm() {
    setSaving(true); setErr(null);
    try {
      await papi("/party/disclosure/attest", { method: "POST", body: JSON.stringify({ kind: d.kind }) });
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save that. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={`bw-cont ${open ? "open" : ""}`}>
      <button type="button" className="bw-cont-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="bw-cont-ic"><Icon name="doc" size={16} /></span>
        <span className="bw-cont-name">{d.title}</span>
        <span className={`bw-cont-pill ${pill.cls}`}>{pill.text}{!delivered && d.dueDate ? ` · ${fmtDate(d.dueDate)}` : ""}</span>
        <span className="bw-chev"><Icon name="chevron" size={16} /></span>
      </button>
      {open && (
        <div className="bw-cont-body">
          <p>{d.explanation}</p>
          {!delivered && d.dueDate && <p className="muted" style={{ fontSize: 13 }}>Deliver to the buyer by <b>{fmtDate(d.dueDate)}</b>.</p>}
          <div className="bw-cont-stakes"><b>Why it matters:</b> {d.stakes}</div>
          <p style={{ fontSize: 13, margin: ".6rem 0 0" }}>
            The words here: {DISCLOSURE_TERMS[d.kind].map((term, i) => (
              <span key={term}>{i > 0 ? " · " : ""}<Define>{term}</Define></span>
            ))}
          </p>

          {delivered ? (
            <p className="bw-req-state" style={{ marginTop: ".7rem" }}><Icon name="checkCircle" size={16} /> You marked this delivered to the buyer.</p>
          ) : !attesting ? (
            <div className="bw-money-actions" style={{ marginTop: ".7rem" }}>
              <button type="button" className="bw-btn bw-btn-p" onClick={() => setAttesting(true)}><Icon name="check" size={14} /> Complete & mark delivered</button>
            </div>
          ) : (
            <div className="bw-warn" role="alertdialog" aria-label="Confirm disclosure attestation" style={{ marginTop: ".7rem" }}>
              <div className="bw-warn-h"><Icon name="warning" size={16} /> You're signing an attestation</div>
              <p style={{ fontSize: 13, margin: ".4rem 0 0" }}>
                By marking the <b>{d.title}</b> delivered, you attest it's accurate and complete. Incomplete disclosure can create liability that <b>survives closing</b>. When in doubt, disclose.
              </p>
              <label style={{ display: "flex", gap: ".5rem", alignItems: "flex-start", marginTop: ".6rem", fontSize: 13 }}>
                <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
                <span>I attest this disclosure is accurate and complete.</span>
              </label>
              {err && <p style={{ color: "#7c3623", fontSize: 13, margin: ".4rem 0 0" }}>{err}</p>}
              <div className="bw-money-actions">
                <button type="button" className="bw-btn bw-btn-p" disabled={!checked || saving} onClick={() => void confirm()}>{saving ? "Saving…" : "Confirm & mark delivered"}</button>
                <button type="button" className="bw-btn bw-btn-g" onClick={() => { setAttesting(false); setChecked(false); }}>Not yet</button>
              </div>
            </div>
          )}
          <p className="bw-legal">Plain-language orientation, not legal advice. Talk to your agent about your disclosure obligations.</p>
        </div>
      )}
    </div>
  );
}

function NetProceeds({ net, escrowPhone, papi, reload }: { net: NetSheet; escrowPhone: string | null; papi: Props["papi"]; reload: Props["reload"] }) {
  const [openLines, setOpenLines] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [called, setCalled] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirm() {
    setSaving(true); setErr(null);
    try {
      await papi("/party/disbursement/verify", { method: "POST" });
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save that. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bw-money">
      <h2>What you'll walk away with</h2>
      <div className="bw-money-amt">{usd(net.estimatedNetProceedsCents)}</div>
      <div className="bw-money-meta"><b>Estimated</b>{net.beforeMortgagePayoff ? ", before your mortgage payoff" : ""}. A live estimate, not a guaranteed figure.</div>
      <div className="bw-money-meta" style={{ marginTop: 4 }}>Once the sale records, <Define>escrow</Define> typically sends your proceeds the same or next business day.</div>

      <button type="button" className={`bw-net-toggle ${openLines ? "open" : ""}`} aria-expanded={openLines} onClick={() => setOpenLines((o) => !o)}>
        {openLines ? "Hide" : "Show"} the numbers <span className="bw-chev"><Icon name="chevron" size={14} /></span>
      </button>
      {openLines && (
        <div className="bw-net-lines">
          {net.lines.map((l, i) => (
            <div className={`bw-net-line ${l.kind}`} key={i}>
              <span>{l.label}</span>
              <span className="amt">{l.kind === "debit" ? "−" : ""}{usd(l.amountCents)}</span>
            </div>
          ))}
          <div className="bw-net-line total">
            <span>Estimated net proceeds</span>
            <span className="amt">{usd(net.estimatedNetProceedsCents)}</span>
          </div>
          {net.beforeMortgagePayoff && (
            <p className="bw-net-note">This estimate doesn't include your existing <Define>mortgage payoff</Define>; only your lender has that exact figure. Ask them for a payoff quote.</p>
          )}
        </div>
      )}

      <div style={{ marginTop: ".9rem", borderTop: "1px solid var(--amber-line)", paddingTop: ".8rem" }}>
        {net.disbursementVerified ? (
          <div className="bw-verified"><Icon name="checkCircle" size={18} /> You've confirmed your proceeds-disbursement account.</div>
        ) : !verifying ? (
          <div className="bw-money-actions">
            <button type="button" className="bw-btn bw-btn-p" onClick={() => setVerifying(true)}><Icon name="shield" size={15} /> Verify where your proceeds go</button>
          </div>
        ) : (
          <div className="bw-warn" role="alertdialog" aria-label="Verify your disbursement account">
            <div className="bw-warn-h"><Icon name="warning" size={16} /> Confirm your payoff account by phone</div>
            <ul>
              <li>Wire fraud targets sellers too. Criminals send fake "updated" disbursement instructions that look real.</li>
              <li>Escrow will <b>never</b> email or message you a change to where your proceeds go.</li>
              <li>Call escrow at a number <b>you</b> look up or already trust and confirm your account by voice.</li>
            </ul>
            <div className="bw-money-actions">
              {escrowPhone
                ? <a className="bw-btn bw-btn-g" href={`tel:${escrowPhone}`}><Icon name="phone" size={14} /> Call escrow · {escrowPhone}</a>
                : <span className="muted" style={{ fontSize: 13 }}>Ask your agent for escrow's verified phone number.</span>}
            </div>
            <label style={{ display: "flex", gap: ".5rem", alignItems: "flex-start", marginTop: ".7rem", fontSize: 13 }}>
              <input type="checkbox" checked={called} onChange={(e) => setCalled(e.target.checked)} />
              <span>I called escrow and confirmed my disbursement account by voice.</span>
            </label>
            {err && <p style={{ color: "#7c3623", fontSize: 13, margin: ".4rem 0 0" }}>{err}</p>}
            <div className="bw-money-actions">
              <button type="button" className="bw-btn bw-btn-p" disabled={!called || saving} onClick={() => void confirm()}>{saving ? "Saving…" : "I've verified my account"}</button>
              <button type="button" className="bw-btn bw-btn-g" onClick={() => { setVerifying(false); setCalled(false); }}>Not yet</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function RequestCard({ r, currentProceeds }: { r: import("./types").BuyerRequest; currentProceeds: number }) {
  const [confirming, setConfirming] = useState(false);
  const resolved = r.state !== "pending";
  return (
    <div className="bw-req">
      <div className="bw-req-h"><Icon name="inbox" size={16} /> {r.kind === "credit" ? "Credit request" : "Repair request"} · {r.summary}</div>
      {r.amountCents != null && <div className="bw-req-amt">{usd(r.amountCents)}</div>}
      <div className="bw-req-impact">
        Accepting reduces your estimated net proceeds from <b>{usd(currentProceeds)}</b> to <b>{usd(r.proceedsAfterAcceptCents)}</b>.
      </div>
      {resolved ? (
        <div className="bw-req-state"><Icon name="check" size={15} /> {r.state === "accepted" ? "Accepted. Amendment sent to your agent for signature." : humanize(r.state)}</div>
      ) : !confirming ? (
        <div className="bw-req-actions">
          <button type="button" className="bw-btn bw-btn-p" onClick={() => setConfirming(true)}>Accept</button>
          <button type="button" className="bw-btn bw-btn-g">Counter</button>
          <button type="button" className="bw-btn bw-btn-g">Decline</button>
        </div>
      ) : (
        <div className="bw-warn" role="alertdialog" aria-label="Confirm accepting the request">
          <div className="bw-warn-h"><Icon name="warning" size={16} /> This reduces your proceeds</div>
          <p style={{ fontSize: 13, margin: ".4rem 0" }}>
            Accepting brings your estimated net proceeds to <b>{usd(r.proceedsAfterAcceptCents)}</b>. Once your agent countersigns the amendment, this can't be undone.
          </p>
          <div className="bw-req-actions">
            <button type="button" className="bw-btn bw-btn-p">Confirm and prepare the amendment</button>
            <button type="button" className="bw-btn bw-btn-g" onClick={() => setConfirming(false)}>Go back</button>
          </div>
        </div>
      )}
    </div>
  );
}

// The seller's service team; buyers and the buyer's agent are counterparties.
const SELLER_TEAM_ROLES = new Set(["listing_agent", "broker", "escrow", "title", "attorney"]);

// Narrate the machine per phase, seller-voiced. Static CA copy.
const SELLER_NOW: Record<SellerPhase, JSX.Element> = {
  offer: <>The offer is signed and <Define>escrow</Define> is being opened. Your side's next job is the disclosure paperwork.</>,
  escrow_open: <><Define>Escrow</Define> is open and holding the buyer's deposit. Your disclosures are the main thing moving right now.</>,
  disclosures: <>Your <Define>disclosure</Define> paperwork is the main thing moving right now. The buyer's clock starts when they receive it.</>,
  buyer_contingencies: <>The buyer is doing their checking: inspections, loan, and <Define>appraisal</Define>. Most of this happens on their side.</>,
  closing: <>The finish line: the buyer's final <Define>walkthrough</Define>, signing, funding, and recording. Keep packing.</>,
  closed: <>Recorded and complete. The sale is done.</>,
};

function SellerHomeSection({ ws }: { ws: import("../types").Workspace }) {
  const prop = ws.property;
  const [look, setLook] = useState<"street" | "map">("street");
  if (!prop) return null;
  const d = prop.details ?? {};
  const fmtN = (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-US") : String(v));
  const facts: [string, unknown][] = [
    ["beds", d.beds], ["baths", d.baths], ["sq ft", d.sqft], ["built", d.year_built], ["sq ft lot", d.lot_size],
  ];
  const shown = facts.filter(([, v]) => v != null && v !== "");
  const embeds = prop.embeds ?? {};
  const hasEmbeds = !!(embeds.street || embeds.map);
  const leaving = prop.included_items || ws.fields.items_included || null;
  const taking = prop.excluded_items || ws.fields.items_excluded || null;
  const links = prop.deep_links ?? {};

  return (
    <section id="sw-home" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
      <h2>Your home</h2>
      {shown.length > 0 && (
        <div className="bw-facts" role="list" aria-label="Home facts">
          {shown.map(([label, v]) => (
            <div key={label} className="bw-fact" role="listitem">
              <span className="bw-fact-n">{fmtN(v)}</span>
              <span className="bw-fact-l">{label}</span>
            </div>
          ))}
          {d.property_type && <div className="bw-fact"><span className="bw-fact-n type">{String(d.property_type)}</span></div>}
        </div>
      )}

      {(leaving || taking) && (
        <div className="bw-stays">
          <div className="bw-stays-h">What stays · what goes with you</div>
          {leaving && (
            <div className="bw-stays-row ok">
              <Icon name="check" size={14} />
              <span><b>Stays with the home:</b> {leaving}</span>
            </div>
          )}
          {taking && (
            <div className="bw-stays-row not">
              <Icon name="key" size={14} />
              <span><b>Goes with you:</b> {taking}. Remember these on moving day.</span>
            </div>
          )}
        </div>
      )}

      {hasEmbeds && (
        <div className="bw-look">
          <div className="bw-look-tabs" role="tablist" aria-label="Look around">
            {embeds.street && (
              <button type="button" role="tab" aria-selected={look === "street"}
                className={`bw-look-tab ${look === "street" ? "on" : ""}`} onClick={() => setLook("street")}>
                <Icon name="pin" size={13} /> Street view
              </button>
            )}
            {embeds.map && (
              <button type="button" role="tab" aria-selected={look === "map"}
                className={`bw-look-tab ${look === "map" ? "on" : ""}`} onClick={() => setLook("map")}>
                <Icon name="board" size={13} /> Satellite
              </button>
            )}
          </div>
          <iframe
            key={look}
            className="bw-look-frame"
            src={look === "street" ? (embeds.street ?? embeds.map) : (embeds.map ?? embeds.street)}
            title={look === "street" ? "Street view of your home" : "Satellite view of your home"}
            loading="lazy"
            allowFullScreen
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>
      )}

      {links.zillow && (
        <div className="bw-links">
          <a className="bw-btn bw-btn-g" href={links.zillow} target="_blank" rel="noreferrer">
            <Icon name="external" size={13} /> See your home the way buyers see it
          </a>
        </div>
      )}
    </section>
  );
}

function MoveOutSection({
  moveOut, possessionTerms,
}: {
  moveOut: { walkthrough: { name: string; due_date: string } | null; close: { name: string; due_date: string } | null; possession: { name: string; due_date: string } | null };
  possessionTerms: string | null;
}) {
  const steps = [
    moveOut.walkthrough && {
      date: moveOut.walkthrough.due_date, label: "Buyer's final walkthrough",
      note: "The home should match the contract: agreed repairs done, included items in place.",
    },
    moveOut.close && {
      date: moveOut.close.due_date, label: "Closing & recording",
      note: "Signing, funding, and the county recording the sale. This is the day it becomes official.",
    },
    moveOut.possession && {
      date: moveOut.possession.due_date, label: "Keys handed over",
      note: possessionTerms ? `Per your contract: ${possessionTerms}.` : "Possession transfers to the buyer.",
    },
  ].filter(Boolean) as { date: string; label: string; note: string }[];

  return (
    <section id="sw-moveout" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
      <h2>Your move-out</h2>
      <p className="muted" style={{ margin: "-.3rem 0 .8rem", fontSize: 13 }}>
        The last three dates of this sale.
      </p>
      {steps.length === 0 ? (
        <div className="bw-empty">Your closing dates will appear here once the timeline is set.</div>
      ) : (
        steps.map((st, i) => (
          <div className="bw-move" key={i}>
            <span className="bw-move-date tnum">{fmtDate(st.date).replace(/, \d{4}$/, "")}</span>
            <div className="bw-move-main">
              <div className="bw-move-l">{st.label}</div>
              <div className="bw-move-n">{st.note}</div>
            </div>
          </div>
        ))
      )}
    </section>
  );
}
