import { ReactNode, useCallback, useEffect, useState } from "react";
import { api, AttentionData, AttentionItem, DealSummary, InboxItem, OpenTask } from "../lib/api";
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
function countdown(n: number | null): string {
  if (n == null) return "—";
  return n < 0 ? `${-n}d ago` : n === 0 ? "today" : `${n}d`;
}
type Filter = "all" | "draft" | "reminder" | "gate" | "risk";

const KIND_META: Record<AttentionItem["kind"], { icon: Parameters<typeof Icon>[0]["name"]; label: string }> = {
  draft: { icon: "mail", label: "Draft to approve" },
  reminder: { icon: "hourglass", label: "No reply" },
  gate: { icon: "clipboard", label: "Blocked timeline" },
  risk: { icon: "warning", label: "Risk" },
};
const URG_PILL: Record<string, string> = { overdue: "pill-red", today: "pill-red", soon: "pill-amber", later: "pill-plain" };

/** Home — the TC's decision queue (P1). The SOR generates decisions; this screen
 *  is where they get cleared: drafts awaiting approval (full recipient + body
 *  before send, Rule 3), due follow-ups, timeline-gate blockers, and risk flags,
 *  across every deal — plus the CA-business-day deadline horizon. */
export function Home({
  onOpenDeal,
  onOpenRail,
  onOpenInbox,
}: {
  onOpenDeal: (id: string) => void;
  onOpenRail?: () => void;
  onOpenInbox?: () => void;
}) {
  const [att, setAtt] = useState<AttentionData | null>(null);
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [inboxCount, setInboxCount] = useState(0);
  const [tasks, setTasks] = useState<OpenTask[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, b, t] = await Promise.all([
        api.get<AttentionData>("/transactions/attention"),
        api.get<DealSummary[]>("/transactions/board"),
        api.get<OpenTask[]>("/transactions/tasks"),
      ]);
      setAtt(a);
      setDeals(b);
      setTasks(t);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load", { error: true });
    }
    // Inbox count comes from the ingestion side; its absence must not break Home.
    try {
      const items = await api.get<InboxItem[]>("/ingestion/inbox");
      setInboxCount(items.length);
    } catch {
      setInboxCount(0);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast(ok);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "That didn't stick — try from the deal.", { error: true });
    } finally {
      setBusy(false);
    }
  }

  const approveDraft = (it: AttentionItem, edited?: { subject?: string; body?: string }) =>
    act(
      () => api.post(`/transactions/${it.dealId}/messages/${it.id}/approve-and-send`, edited ?? {}),
      "Approved & sent — logged to the deal",
    );
  const dismissReminder = (it: AttentionItem) =>
    act(() => api.del(`/transactions/${it.dealId}/reminders/${it.id}`), "Dismissed");
  const resolveRisk = (it: AttentionItem) =>
    act(() => api.post(`/transactions/${it.dealId}/risk-flags/${it.id}/resolve`, {}), "Resolved");

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const active = deals.filter((d) => d.stage !== "closed");
  const closingWk = active.filter((d) => {
    const n = daysTo(d.coe_date);
    return n != null && n >= 0 && n <= 7;
  }).length;

  const counts = att?.counts ?? { drafts: 0, remindersDue: 0, gateBlockedDeals: 0, riskFlags: 0 };
  const totalDecisions = (att?.total ?? 0) + inboxCount;
  const items = (att?.items ?? []).filter((i) => filter === "all" || i.kind === filter);
  const horizon = att?.horizon ?? [];

  return (
    <div className="hm">
      <div>
        <h1>{greet}</h1>
        <div className="hm-sub">
          {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          {" · "}
          {active.length} active deal{active.length === 1 ? "" : "s"} · {closingWk} closing this week ·{" "}
          <b>{totalDecisions} decision{totalDecisions === 1 ? "" : "s"} waiting</b>
        </div>
      </div>

      {/* Triage strip — each count filters the queue; inbox jumps to ingestion review. */}
      <div className="hm-triage">
        <TriageChip label="Inbox" n={inboxCount} tone="gold" onClick={onOpenInbox} />
        <TriageChip label="Drafts to approve" n={counts.drafts} tone="gold" on={filter === "draft"} onClick={() => setFilter(filter === "draft" ? "all" : "draft")} />
        <TriageChip label="No reply" n={counts.remindersDue} tone="amber" on={filter === "reminder"} onClick={() => setFilter(filter === "reminder" ? "all" : "reminder")} />
        <TriageChip label="Blocked timelines" n={counts.gateBlockedDeals} tone="amber" on={filter === "gate"} onClick={() => setFilter(filter === "gate" ? "all" : "gate")} />
        <TriageChip label="Risks" n={counts.riskFlags} tone="red" on={filter === "risk"} onClick={() => setFilter(filter === "risk" ? "all" : "risk")} />
      </div>

      <FieldNote total={totalDecisions} counts={counts} inboxCount={inboxCount} active={active} onOpenRail={onOpenRail} />

      <div className="hm-cols">
        <div>
          <Section title={filter === "all" ? "Decision queue" : `Decision queue · ${KIND_META[filter as AttentionItem["kind"]]?.label ?? filter}`} count={items.length}>
            {items.length === 0 ? (
              <Empty>
                {filter === "all"
                  ? (att ? "Queue clear — nothing is waiting on you." : "Loading your queue…")
                  : "Nothing in this bucket."}
              </Empty>
            ) : (
              items.map((it) => (
                <DecisionRow
                  key={`${it.kind}-${it.id}`}
                  it={it}
                  busy={busy}
                  onOpenDeal={onOpenDeal}
                  onApprove={approveDraft}
                  onDismiss={dismissReminder}
                  onResolve={resolveRisk}
                />
              ))
            )}
          </Section>
        </div>

        <div>
          <Section title="Deadline horizon" count={horizon.length}>
            {horizon.length === 0 ? (
              <Empty>No deadlines through {att ? short(att.horizonCutoff) : "the next week"}.</Empty>
            ) : (
              horizon.slice(0, 10).map((d, i) => (
                <div key={i} className="hm-row" onClick={() => onOpenDeal(d.dealId)}>
                  <span className="hm-date tnum">{short(d.date)}</span>
                  <div className="hm-main">
                    <div className="hm-title">{(d.label ?? "").replace(/ (ends|due|delivery).*$/i, "")}</div>
                    <div className="hm-rsub">{addr(d.address)}</div>
                  </div>
                  <span className={URG_PILL[d.urgency] ?? "pill-plain"}>{countdown(d.days)}</span>
                </div>
              ))
            )}
          </Section>

          <Section title="Work queue" count={tasks.length}>
            {tasks.length === 0 ? (
              <Empty>No open tasks — you're all caught up.</Empty>
            ) : (
              [...tasks]
                .sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"))
                .slice(0, 8)
                .map((t) => (
                  <div key={t.id} className="hm-row" onClick={() => onOpenDeal(t.transaction_id)}>
                    <span className="hm-ck" />
                    <div className="hm-main">
                      <div className="hm-title">{t.title}</div>
                      <div className="hm-rsub">{addr(t.property_address)}{t.due_date ? ` · due ${short(t.due_date)}` : ""}</div>
                    </div>
                  </div>
                ))
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

function DecisionRow({
  it, busy, onOpenDeal, onApprove, onDismiss, onResolve,
}: {
  it: AttentionItem;
  busy: boolean;
  onOpenDeal: (id: string) => void;
  onApprove: (it: AttentionItem, edited?: { subject?: string; body?: string }) => void;
  onDismiss: (it: AttentionItem) => void;
  onResolve: (it: AttentionItem) => void;
}) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState(it.body ?? "");
  const meta = KIND_META[it.kind];
  return (
    <div className={`hm-q ${it.urgency === "overdue" || it.urgency === "today" ? "hot" : ""}`}>
      <div className="hm-row" style={{ cursor: it.kind === "draft" ? "default" : "pointer" }}
        onClick={() => (it.kind === "draft" ? setOpen((o) => !o) : onOpenDeal(it.dealId))}>
        <span className={`hm-qic ${it.kind}`}><Icon name={meta.icon} size={14} /></span>
        <div className="hm-main">
          <div className="hm-title">{it.title}</div>
          <div className="hm-rsub">{addr(it.address)} · {it.detail}</div>
        </div>
        {it.date && <span className={URG_PILL[it.urgency] ?? "pill-plain"}>{countdown(daysTo(it.date))}</span>}
        <div className="hm-qact" onClick={(e) => e.stopPropagation()}>
          {it.kind === "draft" && (
            <button className="kbtn" disabled={busy} onClick={() => setOpen((o) => !o)}>
              {open ? "Hide" : "Review"}
            </button>
          )}
          {it.kind === "reminder" && (
            <button className="kbtn" disabled={busy} onClick={() => onDismiss(it)}>Dismiss</button>
          )}
          {it.kind === "risk" && (
            <button className="kbtn" disabled={busy} onClick={() => onResolve(it)}>Resolve</button>
          )}
          {it.kind === "gate" && (
            <button className="kbtn" onClick={() => onOpenDeal(it.dealId)}>Review fields</button>
          )}
          <button className="kbtn icon" title="Open deal" onClick={() => onOpenDeal(it.dealId)}>
            <Icon name="chevron" size={13} style={{ transform: "rotate(-90deg)" }} />
          </button>
        </div>
      </div>

      {/* Rule 3: the exact recipient and full (editable) body, right in the queue,
          before anything can be approved. */}
      {it.kind === "draft" && open && (
        <div className="hm-qx">
          <div className="hm-qxto">
            To <b>{it.recipientName ?? "recipient"}</b>
            {it.recipientRole ? ` · ${it.recipientRole.replace(/_/g, " ")}` : ""} · email
          </div>
          <textarea className="hm-qxbody" value={body} rows={7} onChange={(e) => setBody(e.target.value)} aria-label="Draft body" />
          <div className="hm-qact" style={{ marginTop: 8 }}>
            <button className="kbtn pri" disabled={busy}
              onClick={() => onApprove(it, body !== it.body ? { body } : undefined)}>
              <Icon name="check" size={13} /> Approve &amp; send
            </button>
            <button className="kbtn" onClick={() => onOpenDeal(it.dealId)}>Open deal</button>
          </div>
        </div>
      )}
    </div>
  );
}

function TriageChip({ label, n, tone, on, onClick }: { label: string; n: number; tone: "gold" | "amber" | "red"; on?: boolean; onClick?: () => void }) {
  return (
    <button className={`hm-tchip ${on ? "on" : ""} ${n > 0 ? tone : ""}`} onClick={onClick} disabled={!onClick}>
      <span className="hm-tn tnum">{n}</span> {label}
    </button>
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

function FieldNote({
  total, counts, inboxCount, active, onOpenRail,
}: {
  total: number;
  counts: AttentionData["counts"];
  inboxCount: number;
  active: DealSummary[];
  onOpenRail?: () => void;
}) {
  const time = new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  const atRisk = active.filter((d) => d.risk_count > 0).length;
  const headline =
    total > 0
      ? `${total} decision${total > 1 ? "s" : ""} waiting on you.`
      : "Queue clear — nothing is waiting on you.";
  const bits = [
    counts.drafts > 0 && `${counts.drafts} draft${counts.drafts > 1 ? "s" : ""} to approve`,
    counts.remindersDue > 0 && `${counts.remindersDue} unanswered follow-up${counts.remindersDue > 1 ? "s" : ""}`,
    counts.gateBlockedDeals > 0 && `${counts.gateBlockedDeals} timeline${counts.gateBlockedDeals > 1 ? "s" : ""} blocked on deal terms`,
    inboxCount > 0 && `${inboxCount} inbound item${inboxCount > 1 ? "s" : ""} to review`,
  ].filter(Boolean);
  const summary =
    total > 0
      ? `${bits.join(", ")}. Clear them here — each row shows exactly what would go out before you approve.`
      : `${active.length} active deal${active.length === 1 ? "" : "s"}, ${atRisk} with open risks. Terra is watching the deadlines.`;

  return (
    <div className="fieldnote">
      <svg className="fn-contour" viewBox="0 0 240 140" fill="none" stroke="currentColor" strokeWidth={1} aria-hidden>
        {Array.from({ length: 6 }, (_, i) => (
          <path key={i} d={`M-10 ${28 + i * 20}C50 ${8 + i * 20} 100 ${58 + i * 20} 160 ${34 + i * 20} 220 ${14 + i * 20} 260 ${48 + i * 20} 300 ${28 + i * 20}`} opacity={0.5 - i * 0.05} />
        ))}
      </svg>
      <div className="fn-lab">
        <span className="fn-chip">◆ Field Note</span>
        <span className="fn-time tnum">{time}</span>
      </div>
      <h3 className="fn-head">{headline}</h3>
      <p className="fn-p">{summary}</p>
      {onOpenRail && (
        <button className="fn-cta" onClick={onOpenRail}>
          Review recommendations <Icon name="chevron" size={14} />
        </button>
      )}
    </div>
  );
}
