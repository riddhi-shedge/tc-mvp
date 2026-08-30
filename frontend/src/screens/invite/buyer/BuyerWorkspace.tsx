import { useEffect, useMemo, useState } from "react";
import { fmtDate } from "../../../lib/format";
import { Icon, IconName } from "../../../lib/icons";
import { countdown, daysTo, humanize, initials, isDone } from "../helpers";
import { Task, Workspace } from "../types";
import "./buyer.css";
import { Define } from "./TapToDefine";
import { Contingency, ContingencyKind, DealPhase } from "./types";
import { buildBuyerDeal } from "./useBuyerDeal";

type Props = {
  ws: Workspace;
  papi: <T,>(path: string, init?: RequestInit) => Promise<T>;
  reload: () => Promise<void> | void;
  busy: boolean;
  cycle: (t: Task) => void;
};

const PHASES: { key: DealPhase; label: string }[] = [
  { key: "offer", label: "Offer accepted" },
  { key: "escrow_open", label: "Escrow opened" },
  { key: "contingencies", label: "Contingencies" },
  { key: "closing", label: "Closing" },
  { key: "keys", label: "Keys" },
];
const CONT_ICON: Record<ContingencyKind, IconName> = { inspection: "shield", loan: "money", appraisal: "receipt", other: "clipboard" };
const CONT_TERMS: Record<ContingencyKind, string[]> = {
  inspection: ["contingency", "contingency removal"], loan: ["underwriting", "contingency removal"],
  appraisal: ["appraisal", "contingency removal"], other: ["contingency"],
};
const prefersReduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export function BuyerWorkspace({ ws, papi, reload, busy, cycle }: Props) {
  const deal = useMemo(() => buildBuyerDeal(ws), [ws]);
  const hasMoney = !!deal.deposit;
  const nav = useMemo(
    () => [
      { id: "bw-overview", label: "Overview", icon: "home" as IconName },
      { id: "bw-timeline", label: "Timeline", icon: "flag" as IconName },
      { id: "bw-tasks", label: "Your tasks", icon: "checkCircle" as IconName },
      { id: "bw-contingencies", label: "Protections", icon: "shield" as IconName },
      ...(hasMoney ? [{ id: "bw-money", label: "Your deposit", icon: "money" as IconName }] : []),
    ],
    [hasMoney],
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

  const s = deal.summary;

  return (
    <div className="bw">
      <header className="bw-topbar">
        {s.heroPhotoUrl
          ? <img className="bw-home-thumb" src={s.heroPhotoUrl} alt="" />
          : <span className="bw-home-thumb"><Icon name="home" size={18} /></span>}
        <span className="bw-top-addr">{s.propertyAddress}</span>
        <span className="bw-top-sp" />
        <span className="bw-avatar" title={ws.me.name ?? "You"}>{initials(ws.me.name, ws.me.role)}</span>
      </header>

      <div className="bw-main">
        <nav className="bw-rail" aria-label="Sections">
          <div className="bw-rail-group">
            <div className="section-label">Your home</div>
            {nav.map((n) => (
              <button key={n.id} type="button" className={`bw-nav ${active === n.id ? "on" : ""}`} onClick={() => goTo(n.id)}>
                <Icon name={n.icon} size={17} /> <span className="bw-nav-label">{n.label}</span>
              </button>
            ))}
          </div>
        </nav>

        <main className="bw-canvas">
          {/* Overview — answers "where are we" at a glance */}
          <section id="bw-overview" className="bw-sec" style={{ scrollMarginTop: 72 }}>
            <div
              className="bw-hero"
              style={s.heroPhotoUrl ? { backgroundImage: `url(${s.heroPhotoUrl})` } : undefined}
            >
              {!s.heroPhotoUrl && <div className="bw-hero-ph"><Icon name="home" size={34} /></div>}
              {s.photoCount > 0 && <span className="bw-photos">{s.photoCount} photo{s.photoCount === 1 ? "" : "s"}</span>}
              <div className="bw-hero-scrim" />
              <div className="bw-hero-cap">
                <div>
                  <div className="bw-hero-eyebrow">Your future home</div>
                  <div className="bw-hero-addr">{s.propertyAddress}</div>
                </div>
                {s.daysToKeys != null && s.daysToKeys >= 0 && (
                  <div className="bw-keys">
                    <div className="bw-keys-n">{s.daysToKeys}</div>
                    <div className="bw-keys-l">{s.daysToKeys === 1 ? "day to keys" : "days to keys"}</div>
                  </div>
                )}
              </div>
            </div>

            <StatusLine level={s.status.level} detail={s.status.nextActionLabel} />
          </section>

          {/* Timeline — read-only, must not look tappable */}
          <section id="bw-timeline" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }} aria-label="Where your deal stands">
            <h2>Where your deal stands</h2>
            <PhaseTimeline phase={s.phase} />
            {s.estimatedKeysDate && (
              <p className="muted" style={{ marginTop: ".7rem", fontSize: 13 }}>
                Estimated keys on <b>{fmtDate(s.estimatedKeysDate)}</b>. Dates can shift — your team will keep this current.
              </p>
            )}
          </section>

          {/* Tasks — the only truly interactive list */}
          <section id="bw-tasks" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
            <h2>What needs you</h2>
            {ws.my_tasks.length === 0
              ? <div className="bw-empty">Nothing needs you right now. We'll surface the next step here when it's time.</div>
              : ws.my_tasks.map((t) => <BuyerTaskRow key={t.id} t={t} busy={busy} cycle={cycle} />)}
          </section>

          {/* Contingencies — plain-language protections, never advises removal */}
          <section id="bw-contingencies" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
            <h2>Your protections</h2>
            <p className="muted" style={{ margin: "-.3rem 0 .8rem", fontSize: 13 }}>
              <Define>Contingencies</Define> are conditions that protect you. In California they don't lapse on their own — removing one is a step you take with your team.
            </p>
            {deal.contingencies.length === 0
              ? <div className="bw-empty">No active contingencies are on file for your deal yet.</div>
              : deal.contingencies.map((c) => <ContingencyCard key={c.id} c={c} />)}
          </section>

          {/* Money — verification only, wire-fraud friction */}
          {deal.deposit && (
            <section id="bw-money" className="bw-sec" style={{ scrollMarginTop: 72 }}>
              <MoneyStep deposit={deal.deposit} papi={papi} reload={reload} />
            </section>
          )}
        </main>

        <aside className="bw-aside" aria-label="Your team and activity">
          <div className="bw-card">
            <h2>Your team</h2>
            {deal.team.length === 0
              ? <div className="bw-empty">Your team will appear here.</div>
              : deal.team.map((m, i) => (
                  <div className="bw-member" key={m.id ?? i}>
                    <span className="bw-member-ava">{initials(m.name, m.role)}</span>
                    <div style={{ minWidth: 0 }}>
                      <div className="bw-member-name">{m.name ?? humanize(m.role)}</div>
                      <div className="bw-member-role">{humanize(m.role)}</div>
                    </div>
                    {m.phone && (
                      <a className="bw-call" href={`tel:${m.phone}`}><Icon name="phone" size={12} /> Call</a>
                    )}
                  </div>
                ))}
          </div>

          <div className="bw-card">
            <h2>Recent activity</h2>
            {deal.activity.length === 0
              ? <div className="bw-empty">Updates on your deal will show up here.</div>
              : (
                <ul className="bw-activity" aria-live="polite">
                  {deal.activity.map((a) => (
                    <li key={a.id}>
                      <span className="bw-act-dot" />
                      <div>{a.text}{a.occurredAt && <time>{fmtDate(a.occurredAt)}</time>}</div>
                    </li>
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
    on_track: { icon: "shield", head: "You're on track" },
    action_soon: { icon: "clock", head: "One thing coming up" },
    at_risk: { icon: "warning", head: "Needs your attention" },
  };
  const m = meta[level];
  return (
    <div className={`bw-status ${level}`} role="status">
      <span className="bw-status-ic"><Icon name={m.icon} size={18} /></span>
      <span><b>{m.head}</b> · {detail}</span>
    </div>
  );
}

function PhaseTimeline({ phase }: { phase: DealPhase }) {
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

function BuyerTaskRow({ t, busy, cycle }: { t: Task; busy: boolean; cycle: (t: Task) => void }) {
  const done = isDone(t.status);
  const n = daysTo(t.due_date);
  const urg = done ? "later" : n != null && n <= 2 ? "now" : n != null && n <= 7 ? "soon" : "later";
  return (
    <div className={`bw-task ${done ? "done" : ""}`}>
      <button
        type="button"
        className={`bw-check ${done ? "done" : ""}`}
        disabled={busy}
        aria-pressed={done}
        aria-label={done ? `Mark "${t.title}" not done` : `Mark "${t.title}" done`}
        onClick={() => cycle(t)}
      >
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

function ContingencyCard({ c }: { c: Contingency }) {
  const [open, setOpen] = useState(false);
  const removed = c.status === "removed";
  const pill = removed
    ? { cls: "done", text: "Waived" }
    : c.daysLeft != null && c.daysLeft <= 7
      ? { cls: "warn", text: `Removes in ${countdown(c.daysLeft)}` }
      : { cls: "", text: "Active" };
  return (
    <div className={`bw-cont ${open ? "open" : ""}`}>
      <button type="button" className="bw-cont-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="bw-cont-ic"><Icon name={CONT_ICON[c.kind]} size={16} /></span>
        <span className="bw-cont-name">{c.title}</span>
        <span className={`bw-cont-pill ${pill.cls}`}>{pill.text}</span>
        <span className="bw-chev"><Icon name="chevron" size={16} /></span>
      </button>
      {open && (
        <div className="bw-cont-body">
          {removed && (
            <p style={{ margin: ".2rem 0 .5rem", color: "var(--ink)" }}>
              You <b>waived</b> this protection when your offer was accepted — a common move in a competitive market. Here's what it would have covered:
            </p>
          )}
          <p>{c.explanation}</p>
          {!removed && c.removalDate && (
            <p className="muted" style={{ fontSize: 13 }}>
              Scheduled to remove on <b>{fmtDate(c.removalDate)}</b>.
            </p>
          )}
          {!removed && <div className="bw-cont-stakes"><b>If it's removed:</b> {c.stakes}</div>}
          <p style={{ fontSize: 13, margin: ".6rem 0 0" }}>
            The words here: {CONT_TERMS[c.kind].map((term, i) => (
              <span key={term}>{i > 0 ? " · " : ""}<Define>{term}</Define></span>
            ))}
          </p>
          <p className="bw-legal">Plain-language orientation, not legal advice. Talk to your agent before removing any contingency.</p>
        </div>
      )}
    </div>
  );
}

function MoneyStep({ deposit, papi, reload }: { deposit: NonNullable<ReturnType<typeof buildBuyerDeal>["deposit"]>; papi: Props["papi"]; reload: Props["reload"] }) {
  const [step, setStep] = useState<"idle" | "verify">("idle");
  const [called, setCalled] = useState(false);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function confirm() {
    setSending(true); setErr(null);
    try {
      await papi("/party/deposit/verify", { method: "POST" });
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save that. Please try again.");
    } finally {
      setSending(false);
    }
  }

  if (deposit.verifiedByBuyer) {
    return (
      <div className="bw-money">
        <h2>Your deposit</h2>
        <div className="bw-verified"><Icon name="checkCircle" size={18} /> You've confirmed your earnest-money deposit is sent.</div>
        <p className="bw-money-meta" style={{ marginTop: ".4rem" }}>
          {deposit.amountLabel}{deposit.payeeLabel ? ` to ${deposit.payeeLabel}` : ""}. Escrow will confirm receipt on their end.
        </p>
      </div>
    );
  }

  return (
    <div className="bw-money">
      <h2>Your earnest-money deposit</h2>
      <div className="bw-money-amt">{deposit.amountLabel}</div>
      <div className="bw-money-meta">
        {deposit.payeeLabel ? <>Held by <b>{deposit.payeeLabel}</b>. </> : null}
        {deposit.dueDate ? <>Due by <b>{fmtDate(deposit.dueDate)}</b>.</> : null}
      </div>

      {step === "idle" ? (
        <div className="bw-money-actions">
          <button type="button" className="bw-btn bw-btn-p" onClick={() => setStep("verify")}>
            <Icon name="shield" size={15} /> I'm ready to send my deposit
          </button>
        </div>
      ) : (
        <div className="bw-warn" role="alertdialog" aria-label="Protect yourself from wire fraud">
          <div className="bw-warn-h"><Icon name="warning" size={16} /> Before you send a cent</div>
          <ul>
            <li>Wire fraud is the #1 scam in home sales. Criminals send fake "updated" instructions that look real.</li>
            <li>We will <b>never</b> email or message you wiring changes. No one on your team will rush you.</li>
            <li>Call escrow at a number <b>you</b> look up or already trust — not one from an email — and confirm the instructions by voice before sending.</li>
          </ul>
          <div className="bw-money-actions">
            {deposit.escrowPhone
              ? <a className="bw-btn bw-btn-g" href={`tel:${deposit.escrowPhone}`}><Icon name="phone" size={14} /> Call escrow · {deposit.escrowPhone}</a>
              : <span className="muted" style={{ fontSize: 13 }}>Ask your agent for escrow's verified phone number.</span>}
          </div>
          <label style={{ display: "flex", gap: ".5rem", alignItems: "flex-start", marginTop: ".7rem", fontSize: 13 }}>
            <input type="checkbox" checked={called} onChange={(e) => setCalled(e.target.checked)} />
            <span>I called escrow and confirmed the wire instructions by voice myself.</span>
          </label>
          {err && <p style={{ color: "#7c3623", fontSize: 13, margin: ".4rem 0 0" }}>{err}</p>}
          <div className="bw-money-actions">
            <button type="button" className="bw-btn bw-btn-p" disabled={!called || sending} onClick={() => void confirm()}>
              {sending ? "Saving…" : "I've verified and sent it"}
            </button>
            <button type="button" className="bw-btn bw-btn-g" onClick={() => { setStep("idle"); setCalled(false); }}>Not yet</button>
          </div>
        </div>
      )}
    </div>
  );
}
