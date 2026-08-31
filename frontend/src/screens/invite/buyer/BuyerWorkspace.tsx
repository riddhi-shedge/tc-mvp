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

// "What's happening now" — narrate the machine even when the buyer has nothing
// to do (an inert page reads as "something's wrong" to an anxious first-timer).
// Static CA copy, jargon tap-to-definable.
const PHASE_NOW: Record<DealPhase, JSX.Element> = {
  offer: <>Your offer is accepted and the paperwork is being opened. Nothing is needed from you today.</>,
  escrow_open: <><Define>Escrow</Define> is holding the deal together while your lender works on the loan. Nothing is needed from you today unless a task appears above.</>,
  contingencies: <>This is the checking period — inspections and the loan get finished, and your <Define>contingencies</Define> protect you while they do.</>,
  closing: <>The finish line: final <Define>walkthrough</Define>, signing, and funding. Your team will tell you exactly where to be and when.</>,
  keys: <>Closing is complete — the home is yours. Anything left here is wrap-up.</>,
};

// The buyer's service team (callable); principals and the listing side appear
// separately under "Also on this deal" — they're parties, not your team.
const TEAM_ROLES = new Set([
  "buyer_agent", "broker", "escrow", "title", "lender", "loan_officer",
  "inspector_general", "inspector_termite", "inspector_roof", "inspector_sewer", "appraiser",
]);

// Buyer-relevant upload types (subset of the shared DOC_TYPES).
const BUYER_DOC_TYPES = [
  { v: "proof_of_funds", label: "Proof of funds" },
  { v: "disclosure", label: "Signed disclosure" },
  { v: "other", label: "Other document" },
];

export function BuyerWorkspace({ ws, papi, reload, busy, cycle }: Props) {
  const deal = useMemo(() => buildBuyerDeal(ws), [ws]);
  const hasMoney = !!deal.deposit;
  const nav = useMemo(
    () => [
      { id: "bw-overview", label: "Overview", icon: "board" as IconName },
      { id: "bw-home", label: "The home", icon: "home" as IconName },
      { id: "bw-timeline", label: "Timeline", icon: "flag" as IconName },
      { id: "bw-tasks", label: "Your tasks", icon: "checkCircle" as IconName },
      { id: "bw-contingencies", label: "Protections", icon: "shield" as IconName },
      { id: "bw-docs", label: "Documents", icon: "doc" as IconName },
      ...(hasMoney ? [{ id: "bw-money", label: "Your deposit", icon: "money" as IconName }] : []),
    ],
    [hasMoney],
  );
  const [active, setActive] = useState(nav[0].id);
  const [docType, setDocType] = useState("proof_of_funds");
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setUploadMsg(null);
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const b64 = (reader.result as string).split(",", 2)[1] ?? "";
        await papi("/party/documents", { method: "POST", body: JSON.stringify({ filename: file.name, content_base64: b64, doc_type: docType }) });
        setUploadMsg("Received — your coordinator has it.");
        await reload();
      } catch (err) {
        setUploadMsg(err instanceof Error ? err.message : "Upload failed — try again.");
      } finally {
        setUploading(false);
      }
    };
    reader.readAsDataURL(file);
  }

  // Team split (finding #4): callable service roles vs everyone else; hide self.
  const team = deal.team.filter((m) => TEAM_ROLES.has(m.role));
  const others = deal.team.filter(
    (m) => !TEAM_ROLES.has(m.role) && !(m.name === ws.me.name && m.role === ws.me.role),
  );

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
              {s.photoCount > 1 && <span className="bw-photos">{s.photoCount} photos</span>}
              <div className="bw-hero-scrim" />
              <div className="bw-hero-cap">
                <div>
                  <div className="bw-hero-eyebrow">Your future home</div>
                  <div className="bw-hero-addr">{s.propertyAddress}</div>
                </div>
                {s.daysToKeys != null && s.daysToKeys >= 0 ? (
                  <div className="bw-keys">
                    <div className="bw-keys-n">{s.daysToKeys}</div>
                    <div className="bw-keys-l">{s.daysToKeys === 1 ? "day to keys" : "days to keys"}</div>
                  </div>
                ) : s.phase === "keys" ? (
                  <div className="bw-keys">
                    <div className="bw-keys-n date">🎉</div>
                    <div className="bw-keys-l">closing complete</div>
                  </div>
                ) : s.estimatedKeysDate ? (
                  <div className="bw-keys">
                    <div className="bw-keys-n date">{fmtDate(s.estimatedKeysDate).replace(/, \d{4}$/, "")}</div>
                    <div className="bw-keys-l">est. keys — date passed, ask your agent</div>
                  </div>
                ) : null}
              </div>
            </div>

            <StatusLine level={s.status.level} detail={s.status.nextActionLabel} />

            {/* The three-question loop, made literal: one answer each, one tap to
                the section that backs it up. Always above the fold. */}
            <div className="bw-answers" aria-label="Your three answers">
              <button type="button" className="bw-ans" onClick={() => goTo("bw-timeline")}>
                <span className="bw-ans-k">Where are we?</span>
                <span className="bw-ans-v">{PHASES.find((p) => p.key === s.phase)?.label ?? "In progress"}</span>
              </button>
              <button type="button" className="bw-ans" onClick={() => goTo("bw-tasks")}>
                <span className="bw-ans-k">What do I owe?</span>
                <span className="bw-ans-v">
                  {deal.tasks.filter((t) => !t.done).length > 0
                    ? `${deal.tasks.filter((t) => !t.done).length} thing${deal.tasks.filter((t) => !t.done).length > 1 ? "s" : ""} need${deal.tasks.filter((t) => !t.done).length > 1 ? "" : "s"} you`
                    : "Nothing right now"}
                </span>
              </button>
              <button type="button" className="bw-ans" onClick={() => goTo(hasMoney ? "bw-money" : "bw-timeline")}>
                <span className="bw-ans-k">Is my money safe?</span>
                <span className="bw-ans-v">
                  {deal.deposit
                    ? deal.deposit.verifiedByBuyer
                      ? <><Icon name="checkCircle" size={13} /> {deal.deposit.amountLabel} verified</>
                      : `${deal.deposit.amountLabel} — verify by phone`
                    : "No deposit on file"}
                </span>
              </button>
            </div>
          </section>

          {/* The home itself — the buyer's emotional center: walk the street,
              count the rooms, know what stays, know who fixes what breaks. */}
          <HomeSection ws={ws} />

          {/* Timeline — read-only, must not look tappable */}
          <section id="bw-timeline" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }} aria-label="Where your deal stands">
            <h2>Where your deal stands</h2>
            <PhaseTimeline phase={s.phase} />
            <p className="bw-now">{PHASE_NOW[s.phase]}</p>
            {s.estimatedKeysDate && (
              <p className="muted" style={{ marginTop: ".4rem", fontSize: 13 }}>
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

          {/* Documents — the buyer can deliver what's asked of them (finding #3) */}
          <section id="bw-docs" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
            <h2>Your documents</h2>
            <p className="muted" style={{ margin: "-.3rem 0 .8rem", fontSize: 13 }}>
              Anything you send goes only to your coordinator — other parties never see it.
            </p>
            {ws.my_documents.length > 0 && (
              <div style={{ marginBottom: ".8rem" }}>
                {ws.my_documents.map((d) => (
                  <div className="bw-doc" key={d.id}>
                    <span className="bw-doc-ic"><Icon name="doc" size={15} /></span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600 }}>{humanize(d.doc_type ?? "document")}</div>
                      {d.created_at && <div className="muted" style={{ fontSize: 12 }}>Sent {fmtDate(d.created_at)}</div>}
                    </div>
                    <span className="bw-cont-pill done">Received</span>
                  </div>
                ))}
              </div>
            )}
            <div className="bw-upload">
              <select value={docType} onChange={(e) => setDocType(e.target.value)} aria-label="Document type">
                {BUYER_DOC_TYPES.map((d) => <option key={d.v} value={d.v}>{d.label}</option>)}
              </select>
              <label className={`bw-btn bw-btn-g ${uploading ? "off" : ""}`}>
                <Icon name="attach" size={14} /> {uploading ? "Sending…" : "Send a document"}
                <input type="file" hidden disabled={uploading} onChange={onFile} />
              </label>
            </div>
            {uploadMsg && <p className="muted" style={{ fontSize: 13, marginTop: ".5rem" }}>{uploadMsg}</p>}
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
            <p className="muted" style={{ margin: "-.3rem 0 .5rem", fontSize: 12.5 }}>The people working for you on this purchase.</p>
            {team.length === 0
              ? <div className="bw-empty">Your team will appear here.</div>
              : team.map((m, i) => (
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
        Your <Define>earnest money</Define>{deposit.payeeLabel ? <> is held in <Define>escrow</Define> by <b>{deposit.payeeLabel}</b>.</> : " goes to escrow."}
        {deposit.dueDate ? <> Due by <b>{fmtDate(deposit.dueDate)}</b>.</> : null}
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


function HomeSection({ ws }: { ws: Workspace }) {
  const prop = ws.property;
  const [look, setLook] = useState<"street" | "map">("street");
  if (!prop) return null;
  const d = prop.details ?? {};
  const fmtN = (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-US") : String(v));
  const facts: [string, unknown][] = [
    ["beds", d.beds], ["baths", d.baths], ["sq ft", d.sqft],
    ["built", d.year_built], ["sq ft lot", d.lot_size],
  ];
  const shown = facts.filter(([, v]) => v != null && v !== "");
  const embeds = prop.embeds ?? {};
  const hasEmbeds = !!(embeds.street || embeds.map);
  const warrantyBy = ws.fields.home_warranty_issued_by;
  const warrantyPaid = ws.fields.home_warranty_paid_by;
  const links = prop.deep_links ?? {};
  // The property row's included/excluded columns are often empty; the extracted
  // contract fields carry the real list — prefer whichever has content.
  const included = prop.included_items || ws.fields.items_included || null;
  const excluded = prop.excluded_items || ws.fields.items_excluded || null;

  return (
    <section id="bw-home" className="bw-sec bw-card" style={{ scrollMarginTop: 72 }}>
      <h2>The home</h2>

      {shown.length > 0 ? (
        <div className="bw-facts" role="list" aria-label="Home facts">
          {shown.map(([label, v]) => (
            <div key={label} className="bw-fact" role="listitem">
              <span className="bw-fact-n">{fmtN(v)}</span>
              <span className="bw-fact-l">{label}</span>
            </div>
          ))}
          {d.property_type && <div className="bw-fact"><span className="bw-fact-n type">{String(d.property_type)}</span></div>}
        </div>
      ) : (
        <p className="muted" style={{ margin: "0 0 .8rem", fontSize: 13 }}>
          Bed, bath, and size details for this home will appear here soon.
        </p>
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
          <p className="muted" style={{ margin: ".4rem 0 0", fontSize: 12 }}>
            Drag to look around{look === "street" ? " — this is the view from your street" : ""}.
          </p>
        </div>
      )}

      {(included || excluded) && (
        <div className="bw-stays">
          <div className="bw-stays-h">What stays with the home</div>
          {included && (
            <div className="bw-stays-row ok">
              <Icon name="check" size={14} />
              <span>{included}</span>
            </div>
          )}
          {excluded && (
            <div className="bw-stays-row not">
              <Icon name="x" size={14} />
              <span>Not included: {excluded}</span>
            </div>
          )}
        </div>
      )}

      {warrantyBy && (
        <div className="bw-warranty">
          <Icon name="shield" size={15} />
          <span>
            You&apos;re covered by a <Define>home warranty</Define> from <b>{warrantyBy}</b>
            {warrantyPaid === "seller" ? " — the seller is paying for it" : ""}.
          </span>
        </div>
      )}

      {(links.zillow || links.maps) && (
        <div className="bw-links">
          {links.zillow && <a className="bw-btn bw-btn-g" href={links.zillow} target="_blank" rel="noreferrer"><Icon name="external" size={13} /> See it on Zillow</a>}
          {links.maps && <a className="bw-btn bw-btn-g" href={links.maps} target="_blank" rel="noreferrer"><Icon name="pin" size={13} /> Open in Maps</a>}
        </div>
      )}
    </section>
  );
}
