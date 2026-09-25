import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { api, AttentionData, AttentionItem, DealSummary, InboxItem, OpenTask } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";
import { DealPeek } from "./DealPeek";

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

/** Home — the decision queue as a split pane (P-A/B/D, docs/ui-redesign.md):
 *  queue left with a persistent keyboard cursor, the selected row's deal in a
 *  context panel right. j/k move · Enter acts · d dismisses · o opens the deal.
 *  Rule-3 review (recipient + why + full body) happens in the panel; the queue
 *  never unmounts, so approving advances to the next decision. */
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
  const [loadFailed, setLoadFailed] = useState(false);
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [inboxCount, setInboxCount] = useState(0);
  const [tasks, setTasks] = useState<OpenTask[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const rowsRef = useRef<HTMLDivElement>(null);

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
      setLoadFailed(true);
      toast(err instanceof Error ? err.message : "Failed to load", { error: true });
    }
    try {
      const items = await api.get<InboxItem[]>("/ingestion/inbox");
      setInboxCount(items.length);
    } catch {
      setInboxCount(0);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const items = (att?.items ?? []).filter((i) => filter === "all" || i.kind === filter);
  const selIdx = Math.min(sel, Math.max(0, items.length - 1));
  const selected = items[selIdx] ?? null;

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast(ok);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Something went wrong. Try again from the deal page.", { error: true });
    } finally {
      setBusy(false);
    }
  }
  const approveDraft = (it: AttentionItem, edited?: { subject?: string; body?: string }) =>
    act(() => api.post(`/transactions/${it.dealId}/messages/${it.id}/approve-and-send`, edited ?? {}), "Approved and sent.");
  const dismissReminder = (it: AttentionItem) =>
    it.kind === "risk"
      ? resolveRisk(it)
      : act(() => api.del(`/transactions/${it.dealId}/reminders/${it.id}`), "Dismissed");
  const draftChase = (it: AttentionItem) =>
    act(() => api.post(`/transactions/${it.dealId}/messages/${it.messageId}/draft-chase`, {}), "Follow-up drafted. See the Drafts filter.");
  const resolveRisk = (it: AttentionItem) =>
    act(() => api.post(`/transactions/${it.dealId}/risk-flags/${it.id}/resolve`, {}), "Resolved");

  const primary = useCallback((it: AttentionItem | null) => {
    if (!it || busy) return;
    if (it.kind === "draft") void approveDraft(it); // as-drafted; edited bodies approve from the panel
    else if (it.kind === "reminder") { if (it.messageId) void draftChase(it); }
    else if (it.kind === "gate") onOpenDeal(it.dealId);
    else void resolveRisk(it);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, onOpenDeal]);

  // P-B: keyboard triage. Single letters act only outside inputs; ⌘K stays App's.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
      else if (e.key === "Enter" || e.key === "e") { e.preventDefault(); primary(selected); }
      else if (e.key === "d") { e.preventDefault(); if (selected && !busy) void dismissReminder(selected); }
      else if (e.key === "o") { e.preventDefault(); if (selected) onOpenDeal(selected.dealId); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length, selected, busy, primary, onOpenDeal]);

  // keep the cursor row in view
  useEffect(() => {
    rowsRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [selIdx, filter]);

  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const active = deals.filter((d) => d.stage !== "closed");
  const closingWk = active.filter((d) => { const n = daysTo(d.coe_date); return n != null && n >= 0 && n <= 7; }).length;
  const counts = att?.counts ?? { drafts: 0, remindersDue: 0, gateBlockedDeals: 0, riskFlags: 0 };
  const totalDecisions = (att?.total ?? 0) + inboxCount;
  const horizon = att?.horizon ?? [];

  return (
    <div className="hm hm-splitwrap">
      <div className="hm-left">
        <div className="hm-topline">
          <div>
            <h1>{greet}</h1>
            <div className="hm-sub">
              {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
              {" · "}{active.length} active deal{active.length === 1 ? "" : "s"} · {closingWk} closing this week ·{" "}
              <b>{totalDecisions} decision{totalDecisions === 1 ? "" : "s"} waiting</b>
            </div>
          </div>
          {onOpenRail && (
            <button className="kbtn" onClick={onOpenRail} title="Terra recommendations">
              <Icon name="sparkle" size={13} /> Recommendations
            </button>
          )}
        </div>

        <div className="hm-triage">
          <TriageChip label="Inbox" n={inboxCount} tone="gold" onClick={onOpenInbox} />
          <TriageChip label="Drafts" n={counts.drafts} tone="gold" on={filter === "draft"} onClick={() => { setFilter(filter === "draft" ? "all" : "draft"); setSel(0); }} />
          <TriageChip label="No reply" n={counts.remindersDue} tone="amber" on={filter === "reminder"} onClick={() => { setFilter(filter === "reminder" ? "all" : "reminder"); setSel(0); }} />
          <TriageChip label="Blocked" n={counts.gateBlockedDeals} tone="amber" on={filter === "gate"} onClick={() => { setFilter(filter === "gate" ? "all" : "gate"); setSel(0); }} />
          <TriageChip label="Risks" n={counts.riskFlags} tone="red" on={filter === "risk"} onClick={() => { setFilter(filter === "risk" ? "all" : "risk"); setSel(0); }} />
        </div>

        <div className="hm-section hm-queue">
          <div className="hm-sh">
            <span className="hm-st">{filter === "all" ? "Decision queue" : `Queue · ${KIND_META[filter as AttentionItem["kind"]]?.label ?? filter}`}</span>
            <span className="hm-sc">{items.length}</span>
          </div>
          <div className="hm-list" ref={rowsRef} role="listbox" aria-label="Decisions">
            {items.length === 0 ? (
              <Empty>
                {att
                  ? filter === "all" ? "Queue clear." : "Nothing in this bucket."
                  : loadFailed ? "Couldn't load your queue. Refresh to retry." : "Loading your queue…"}
              </Empty>
            ) : (
              items.map((it, i) => (
                <div
                  key={`${it.kind}-${it.id}`}
                  className={`hm-row hm-qrow ${i === selIdx ? "sel" : ""}`}
                  role="option"
                  aria-selected={i === selIdx}
                  tabIndex={i === selIdx ? 0 : -1}
                  onClick={() => setSel(i)}
                  onDoubleClick={() => onOpenDeal(it.dealId)}
                  onKeyDown={(e) => { if (e.key === " ") { e.preventDefault(); setSel(i); } }}
                >
                  <span className={`hm-qic ${it.kind}`}><Icon name={KIND_META[it.kind].icon} size={14} /></span>
                  <span className="hm-qaddr">{addr(it.address)}</span>
                  <span className="hm-qtitle">{it.title}</span>
                  {it.date && <span className={`${URG_PILL[it.urgency] ?? "pill-plain"} tnum`}>{countdown(daysTo(it.date))}</span>}
                </div>
              ))
            )}
          </div>
          <div className="hm-keys">
            <span><b>j/k</b> move</span><span><b>↵</b> act</span><span><b>d</b> dismiss</span>
            <span><b>o</b> open deal</span><span><b>⌘K</b> jump</span>
            <span className="muted" style={{ marginLeft: "auto" }}>edited drafts approve from the panel</span>
          </div>
        </div>

        <Section title="Deadline horizon" count={horizon.length}>
          {horizon.length === 0 ? (
            <Empty>No deadlines through {att ? short(att.horizonCutoff) : "next week"}.</Empty>
          ) : (
            horizon.slice(0, 8).map((d, i) => (
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
            <Empty>No open tasks.</Empty>
          ) : (
            [...tasks]
              .sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"))
              .slice(0, 6)
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

      <div className="hm-right">
        <DealPeek
          item={selected}
          busy={busy}
          onApprove={approveDraft}
          onDismiss={dismissReminder}
          onResolve={resolveRisk}
          onChase={draftChase}
          onOpenDeal={onOpenDeal}
          onReviewFields={onOpenDeal}
        />
      </div>
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
