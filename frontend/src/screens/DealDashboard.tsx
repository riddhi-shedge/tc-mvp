import { useCallback, useEffect, useState } from "react";
import {
  api,
  Dashboard,
  DashboardPartyView,
  DealParty,
  DealRiskFlag,
  FullState,
  isCollaborator,
  isInvitable,
  PartyAccessToken,
  PARTY_ROLE_LABEL,
  PARTY_ROSTER,
  Task,
} from "../lib/api";
import { Ring, toast } from "../lib/ui";
import { fmtDate } from "../lib/format";
import { Icon, IconName } from "../lib/icons";
import { PartyOrbit } from "./PartyOrbit";
import { motion } from "framer-motion";

const listStagger = { visible: { transition: { staggerChildren: 0.055 } } };
const itemIn = { hidden: { opacity: 0, x: -10 }, visible: { opacity: 1, x: 0 } };

const AVATAR_COLORS = ["#2c4a7c", "#9a6b1e", "#2f7d5b", "#a3352f", "#3a5e97", "#b3842f"];
function avatarColor(seed: string): string {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}
function initials(name: string | null, role: string): string {
  const s = (name || role || "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}
function riskIcon(f: DealRiskFlag): IconName {
  const c = (f.case_key ?? "").toLowerCase();
  if (c.includes("inspection")) return "search";
  if (c.includes("appraisal")) return "tag";
  if (c.includes("loan")) return "bank";
  if (c.includes("escrow")) return "key";
  if (c.includes("earnest") || c.includes("deposit")) return "pin";
  if (c.includes("disclosure")) return "clipboard";
  if (c.includes("closing")) return "clock";
  return "warning";
}
function titleize(s: string | null): string {
  return (s ?? "Attention").replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

// Smart routing: a task's wording implies who should own it. First matching
// rule wins; `roles` is the party-role preference order for the suggestion.
const TASK_ROUTES: { match: RegExp; icon: IconName; roles: string[]; ctx: string }[] = [
  { match: /walk-?through/i, icon: "user", roles: ["buyer_agent"], ctx: "final walk-through" },
  { match: /inspection/i, icon: "search", roles: ["inspector_general", "buyer_agent"], ctx: "inspection contingency" },
  { match: /appraisal/i, icon: "tag", roles: ["appraiser", "lender"], ctx: "appraisal contingency" },
  { match: /loan/i, icon: "bank", roles: ["lender", "loan_officer"], ctx: "loan contingency" },
  { match: /earnest|deposit|\bemd\b/i, icon: "pin", roles: ["escrow"], ctx: "earnest money" },
  { match: /verification of funds|proof of funds/i, icon: "money", roles: ["buyer_agent"], ctx: "verification of funds" },
  { match: /disclosure/i, icon: "clipboard", roles: ["listing_agent"], ctx: "seller disclosures" },
  { match: /warranty/i, icon: "shield", roles: ["buyer_agent", "listing_agent"], ctx: "home warranty" },
  { match: /escrow|closing|close of escrow/i, icon: "key", roles: ["escrow"], ctx: "closing" },
  { match: /possession/i, icon: "key", roles: ["buyer_agent"], ctx: "possession" },
  { match: /insurance/i, icon: "shield", roles: ["buyer_agent"], ctx: "insurance contingency" },
];
function routeFor(title: string): { icon: IconName; roles: string[]; ctx: string } {
  return TASK_ROUTES.find((r) => r.match.test(title)) ?? { icon: "clipboard", roles: [], ctx: "" };
}
const ROLE_SHORT: Record<string, string> = {
  lender: "lender", loan_officer: "loan officer", escrow: "escrow", appraiser: "appraiser",
  inspector_general: "inspector", listing_agent: "listing agent", buyer_agent: "buyer's agent",
};

export function DealDashboard({
  id,
  state,
  onChanged,
}: {
  id: string;
  state: FullState;
  onChanged: () => Promise<void>;
}) {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState(false);
  const [tokens, setTokens] = useState<Record<string, string>>({});
  const [newTask, setNewTask] = useState("");
  // Drag-to-assign + party peek popover (Pass 2 interactivity)
  const [dragTaskId, setDragTaskId] = useState<string | null>(null);
  const [dropParty, setDropParty] = useState<string | null>(null);
  const [peek, setPeek] = useState<DashboardPartyView | null>(null);
  const [orbitOpen, setOrbitOpen] = useState(false);
  // Party editing / adding: which party id is open for edit, or which role is
  // being added, plus the in-progress contact fields.
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [pForm, setPForm] = useState<{
    name: string;
    company: string;
    phone: string;
    email: string;
  }>({ name: "", company: "", phone: "", email: "" });

  const refresh = useCallback(async () => {
    try {
      setDash(await api.get<Dashboard>(`/transactions/${id}/dashboard`));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load dashboard", { error: true });
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setBusy(true);
    try {
      await fn();
      await refresh();
      await onChanged();
      if (ok) toast(ok);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Request failed", { error: true });
    } finally {
      setBusy(false);
    }
  }

  if (!dash) {
    return (
      <div className="bento">
        <div className="card b-2 skeleton" style={{ height: 140 }} />
        <div className="card skeleton" style={{ height: 140 }} />
        <div className="card skeleton" style={{ height: 140 }} />
      </div>
    );
  }

  const doneTasks = state.tasks.filter((t) => ["done", "complete"].includes(t.status)).length;
  const totalTasks = state.tasks.length;
  const completion = totalTasks ? doneTasks / totalTasks : 0;
  const p = dash.party_progress;
  const unassigned: Task[] = state.tasks.filter((t) => t.assigned_party_id === null);
  const parties: DealParty[] = state.parties;

  const rosterRoles = new Set(PARTY_ROSTER.flatMap((g) => g.roles.map((r) => r.role)));
  const otherParties = dash.parties.filter((v) => !rosterRoles.has(v.party.role));

  function contactPayload(): Record<string, string> {
    const out: Record<string, string> = {};
    if (pForm.name.trim()) out.name = pForm.name.trim();
    if (pForm.company.trim()) out.company = pForm.company.trim();
    if (pForm.phone.trim()) out.phone = pForm.phone.trim();
    if (pForm.email.trim()) out.email = pForm.email.trim();
    return out;
  }
  function startEdit(pt: DealParty) {
    setAdding(null);
    setEditing(pt.id);
    setPForm({
      name: pt.name ?? "",
      company: pt.company ?? "",
      phone: pt.phone ?? "",
      email: pt.email ?? "",
    });
  }
  function startAdd(role: string) {
    setEditing(null);
    setAdding(role);
    setPForm({ name: "", company: "", phone: "", email: "" });
  }
  function cancelForm() {
    setEditing(null);
    setAdding(null);
  }
  function contactForm(onSave: () => void, saveLabel: string) {
    return (
      <div className="pform">
        <input placeholder="Name" value={pForm.name} onChange={(e) => setPForm({ ...pForm, name: e.target.value })} />
        <input placeholder="Company / brokerage" value={pForm.company} onChange={(e) => setPForm({ ...pForm, company: e.target.value })} />
        <input placeholder="Phone" value={pForm.phone} onChange={(e) => setPForm({ ...pForm, phone: e.target.value })} />
        <input placeholder="Email" value={pForm.email} onChange={(e) => setPForm({ ...pForm, email: e.target.value })} />
        <div className="pform-actions">
          <button className="gold" disabled={busy || !pForm.name.trim()} onClick={onSave}>{saveLabel}</button>
          <button className="secondary" disabled={busy} onClick={cancelForm}>Cancel</button>
        </div>
      </div>
    );
  }
  function assignTo(taskId: string, pt: DealParty) {
    void run(
      () => api.post(`/transactions/${id}/tasks/${taskId}/assign`, { party_id: pt.id }),
      `Assigned to ${pt.name ?? PARTY_ROLE_LABEL[pt.role] ?? pt.role}`,
    );
  }
  // Compact party row for the info-rail (avatar · name · role · open-task badge).
  // Doubles as a drop target for drag-to-assign; click opens the peek popover.
  function partyRowCompact(pv: DashboardPartyView) {
    const pt = pv.party;
    const dropping = dragTaskId !== null;
    return (
      <div
        key={pt.id}
        className={`prow ${dropping ? "droppable" : ""} ${dropParty === pt.id ? "drop-on" : ""}`}
        onClick={() => setPeek(pv)}
        title="View details"
        onDragOver={dropping ? (e) => { e.preventDefault(); setDropParty(pt.id); } : undefined}
        onDragLeave={() => setDropParty((d) => (d === pt.id ? null : d))}
        onDrop={
          dropping
            ? (e) => { e.preventDefault(); if (dragTaskId) assignTo(dragTaskId, pt); setDragTaskId(null); setDropParty(null); }
            : undefined
        }
      >
        <div className="prow-ava" style={{ background: avatarColor(pt.role) }}>{initials(pt.name, pt.role)}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="prow-name">{pt.name ?? "(unnamed)"}</div>
          <div className="prow-role">{PARTY_ROLE_LABEL[pt.role] ?? pt.role.replace(/_/g, " ")}</div>
        </div>
        {pv.open_tasks.length > 0 && <span className="prow-badge">{pv.open_tasks.length}</span>}
      </div>
    );
  }

  function addTask() {
    const title = newTask.trim();
    if (!title) return;
    void run(async () => {
      await api.post(`/transactions/${id}/tasks`, { title });
      setNewTask("");
    }, "Task added");
  }

  return (
    <>
      <div className="il">
        <aside className="il-rail">
          {/* ---- Deal facts (always-visible reference) ---- */}
          <div className="card il-facts">
            <div className="ring-wrap-sm">
              <Ring value={completion}>
                <div>
                  <div className="rc-num">{Math.round(completion * 100)}%</div>
                  <div className="rc-sub">done</div>
                </div>
              </Ring>
            </div>
            <div className="facts">
              <div className="fact"><span>Tasks</span><b>{doneTasks}/{totalTasks}</b></div>
              <div className="fact"><span>Deadlines</span><b>{state.deadlines.length}</b></div>
              <div className="fact"><span>Open risks</span><b className={dash.risk_alerts.length ? "hot" : ""}>{dash.risk_alerts.length}</b></div>
              <div className="fact"><span>Proof of funds</span><b>{p.proof_of_funds_confirmed}/{p.buyers_total}</b></div>
              <div className="fact"><span>Disclosures</span><b>{p.disclosures_confirmed}</b></div>
            </div>
          </div>

          {/* ---- Parties (compact roster; pop out to the orbit) ---- */}
          <div className="card il-parties">
            <div className="pv-head">
              <h2><Icon name="users" size={16} /> Parties</h2>
              <button className="secondary sm" onClick={() => setOrbitOpen(true)} title="Open the orbital view">◎ Orbit</button>
            </div>
            {PARTY_ROSTER.map((grp) => {
              const groupRoles = grp.roles.map((r) => r.role);
              const cards = dash.parties.filter((v) => groupRoles.includes(v.party.role));
              const missing = grp.roles.filter((r) => !dash.parties.some((v) => v.party.role === r.role));
              return (
                <div key={grp.group} className="pgroup-c">
                  <div className="pgroup-label">{grp.group}</div>
                  {cards.map((pv) => partyRowCompact(pv))}
                  {missing.map((r) => (
                    <button key={r.role} className="prow-add" disabled={busy} onClick={() => startAdd(r.role)}>
                      ＋ {r.label}
                    </button>
                  ))}
                  {adding !== null && groupRoles.includes(adding) &&
                    contactForm(() => {
                      void run(async () => {
                        await api.post(`/transactions/${id}/parties`, { role: adding, ...contactPayload() });
                        cancelForm();
                      }, `${PARTY_ROLE_LABEL[adding] ?? adding} added`);
                    }, "Add party")}
                </div>
              );
            })}
            {otherParties.length > 0 && (
              <div className="pgroup-c">
                <div className="pgroup-label">Other</div>
                {otherParties.map((pv) => partyRowCompact(pv))}
              </div>
            )}
          </div>
        </aside>

        <div className="il-main">
      {/* ---- Risk attention feed ---- */}
      <div className="card">
        <h2><Icon name="warning" size={17} /> Attention</h2>
        {dash.risk_alerts.length === 0 && (
          <div className="empty"><span className="empty-ic"><Icon name="checkCircle" size={26} /></span>No open risk alerts — nicely on track.</div>
        )}
        <motion.div className="risk-feed" initial="hidden" animate="visible" variants={listStagger}>
          {dash.risk_alerts.map((f) => (
            <motion.div key={f.id} className={`risk-card ${f.severity}`} variants={itemIn}>
              <div className="risk-ic"><Icon name={riskIcon(f)} size={16} /></div>
              <div className="risk-body">
                <div className="risk-title">
                  {titleize(f.case_key)}
                  <span className={`badge ${f.severity === "warning" ? "warn" : "danger"}`}>{f.severity}</span>
                </div>
                <div className="risk-desc">{f.description}</div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>

      {/* ---- Tasks (compliance + the TC's own) ---- */}
      <div className="card">
        <div className="between" style={{ marginBottom: "0.6rem" }}>
          <h2 style={{ margin: 0 }}><Icon name="checkCircle" size={17} /> Tasks</h2>
          <span className="assign-hint">
            {state.tasks.filter((t) => !["done", "complete"].includes(t.status)).length} open
            {parties.length > 0 && " · drag a task onto a party to assign"}
          </span>
        </div>
        <div className="row" style={{ gap: "0.5rem", marginBottom: "0.7rem" }}>
          <input
            placeholder="Add your own task…"
            value={newTask}
            onChange={(e) => setNewTask(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newTask.trim()) addTask();
            }}
          />
          <button className="gold" disabled={busy || !newTask.trim()} onClick={addTask}>
            ＋ Add task
          </button>
        </div>
        {state.tasks.length === 0 && (
          <div className="empty"><span className="empty-ic"><Icon name="clipboard" size={26} /></span>No tasks yet.</div>
        )}
        <div className="stack">
          {[...state.tasks]
            .sort((a, b) => {
              const da = state.deadlines.find((d) => d.id === a.deadline_id)?.due_date ?? "9999";
              const db = state.deadlines.find((d) => d.id === b.deadline_id)?.due_date ?? "9999";
              return da.localeCompare(db);
            })
            .map((t) => {
            const done = ["done", "complete"].includes(t.status);
            const who = t.assigned_party_id
              ? parties.find((p) => p.id === t.assigned_party_id)?.name ?? "assigned"
              : null;
            const due = t.deadline_id
              ? state.deadlines.find((d) => d.id === t.deadline_id)?.due_date ?? null
              : null;
            const daysLeft =
              due && !done
                ? Math.round((new Date(due + "T00:00:00").getTime() - Date.now()) / 86_400_000)
                : null;
            const dueColor =
              daysLeft == null
                ? undefined
                : daysLeft < 0
                  ? "var(--red-600)"
                  : daysLeft <= 5
                    ? "var(--gold-700)"
                    : "var(--muted)";
            return (
              <div
                key={t.id}
                className={`task-row ${done ? "done" : ""} ${dragTaskId === t.id ? "dragging" : ""}`}
                draggable={!done && parties.length > 0}
                onDragStart={() => setDragTaskId(t.id)}
                onDragEnd={() => { setDragTaskId(null); setDropParty(null); }}
              >
                <span className="task-grip" title="Drag onto a party to assign">⠿</span>
                <button
                  className="task-check"
                  disabled={busy}
                  title={done ? "Reopen" : "Mark done"}
                  onClick={() =>
                    void run(
                      () =>
                        api.patch(`/transactions/${id}/tasks/${t.id}`, {
                          status: done ? "pending" : "done",
                        }),
                      done ? "Reopened" : "Task done",
                    )
                  }
                >
                  {done ? "✓" : ""}
                </button>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="task-title">{t.title}</div>
                  {(due || who) && (
                    <div className="task-meta">
                      {due && (
                        <span style={{ color: dueColor, fontWeight: daysLeft != null && daysLeft <= 5 ? 600 : 400 }}>
                          <Icon name="calendar" size={12} /> {fmtDate(due)}
                          {daysLeft != null &&
                            (daysLeft < 0
                              ? ` · ${-daysLeft}d overdue`
                              : daysLeft === 0
                                ? " · today"
                                : ` · ${daysLeft}d`)}
                        </span>
                      )}
                      {due && who && <span className="muted"> · </span>}
                      {who && <span className="muted">→ {who}</span>}
                    </div>
                  )}
                </div>
                <span className={`badge ${done ? "ok" : "draft"}`}>{t.status.replace(/_/g, " ")}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* ---- Needs an owner (smart routing) ---- */}
      {unassigned.length > 0 && (
        <div className="card">
          <div className="between" style={{ marginBottom: "0.7rem" }}>
            <h2 style={{ margin: 0 }}><Icon name="pin" size={17} /> Needs an owner</h2>
            <span className="muted">{unassigned.length} unassigned · sorted by urgency</span>
          </div>
          <div className="stack">
            {[...unassigned]
              .sort((a, b) => {
                const da = state.deadlines.find((d) => d.id === a.deadline_id)?.due_date ?? "9999";
                const db = state.deadlines.find((d) => d.id === b.deadline_id)?.due_date ?? "9999";
                return da.localeCompare(db);
              })
              .map((t) => {
                const r = routeFor(t.title);
                const suggested = r.roles
                  .map((role) => parties.find((p) => p.role === role))
                  .find((p) => p);
                const due = t.deadline_id
                  ? state.deadlines.find((d) => d.id === t.deadline_id)?.due_date ?? null
                  : null;
                const daysLeft = due
                  ? Math.round((new Date(due + "T00:00:00").getTime() - Date.now()) / 86_400_000)
                  : null;
                const dueColor =
                  daysLeft == null ? "var(--muted)"
                    : daysLeft < 0 ? "var(--red-600)"
                    : daysLeft <= 5 ? "var(--gold-700)"
                    : "var(--muted)";
                const assign = (partyId: string) =>
                  void run(
                    () => api.post(`/transactions/${id}/tasks/${t.id}/assign`, { party_id: partyId }),
                    "Task assigned",
                  );
                return (
                  <div key={t.id} className="route-row">
                    <div className="route-ic"><Icon name={r.icon} size={15} /></div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="route-title">{t.title}</div>
                      <div className="route-meta">
                        {due && (
                          <span style={{ color: dueColor, fontWeight: daysLeft != null && daysLeft <= 5 ? 600 : 400 }}>
                            <Icon name="calendar" size={12} /> {fmtDate(due)}
                            {daysLeft != null && (daysLeft < 0 ? ` · ${-daysLeft}d overdue` : daysLeft === 0 ? " · today" : ` · ${daysLeft}d`)}
                          </span>
                        )}
                        {due && r.ctx && <span className="muted"> · </span>}
                        {r.ctx && <span className="muted">{r.ctx}</span>}
                      </div>
                    </div>
                    <div className="route-act">
                      {suggested ? (
                        <button className="gold sm" disabled={busy} onClick={() => assign(suggested.id)}>
                          → {suggested.name ?? suggested.role} · Assign
                        </button>
                      ) : r.roles.length > 0 ? (
                        <span className="route-need">no {ROLE_SHORT[r.roles[0]] ?? r.roles[0]} yet</span>
                      ) : null}
                      {parties.length > 0 && (
                        <select
                          className="route-sel"
                          value=""
                          disabled={busy}
                          onChange={(e) => e.target.value && assign(e.target.value)}
                          title="Assign to someone else"
                        >
                          <option value="">{suggested ? "or…" : "assign to…"}</option>
                          {parties.map((pp) => (
                            <option key={pp.id} value={pp.id}>
                              {pp.name ?? pp.role} · {(pp.role ?? "").replace(/_/g, " ")}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}
      </div>
      </div>

      {orbitOpen && (
        <div className="orbit-modal-back" onClick={() => setOrbitOpen(false)}>
          <div className="orbit-modal" onClick={(e) => e.stopPropagation()}>
            <div className="pv-head">
              <h2><Icon name="users" size={17} /> Parties · orbit</h2>
              <button className="peek-x" onClick={() => setOrbitOpen(false)} title="Close"><Icon name="x" size={15} /></button>
            </div>
            <PartyOrbit
              views={dash.parties}
              onSelect={(pv) => { setOrbitOpen(false); setPeek(pv); }}
              onAddRole={(role) => { setOrbitOpen(false); startAdd(role); }}
            />
            <div className="orb-legend">
              <span><i style={{ background: "#5257ea" }} /> Buyer</span>
              <span><i style={{ background: "#0e9488" }} /> Seller</span>
              <span><i style={{ background: "#c07512" }} /> Agent</span>
              <span><i style={{ background: "#5b6472" }} /> Escrow · Title · Lender</span>
              <span><i style={{ background: "#8457d6" }} /> Inspection</span>
              <span style={{ marginLeft: "auto" }}>Hover to pause · click a person · badge = open tasks</span>
            </div>
          </div>
        </div>
      )}

      {peek && (
        <div className="peek-backdrop" onClick={() => setPeek(null)}>
          <div className="peek-card" onClick={(e) => e.stopPropagation()}>
            <div className="peek-head">
              <div className="avatar" style={{ background: avatarColor(peek.party.role) }}>
                {initials(peek.party.name, peek.party.role)}
              </div>
              <div style={{ minWidth: 0 }}>
                <div className="party-name">{peek.party.name ?? "(unnamed)"}</div>
                <div className="party-role">{PARTY_ROLE_LABEL[peek.party.role] ?? peek.party.role.replace(/_/g, " ")}</div>
              </div>
              <button className="peek-x" onClick={() => setPeek(null)} title="Close"><Icon name="x" size={15} /></button>
            </div>

            <div className="peek-contact">
              {peek.party.company && <span><Icon name="bank" size={13} /> {peek.party.company}</span>}
              <span><Icon name="mail" size={13} /> {peek.party.email || "no email on file"}</span>
              <span><Icon name="phone" size={13} /> {peek.party.phone || "no phone on file"}</span>
            </div>

            {editing === peek.party.id ? (
              contactForm(() => {
                void run(async () => {
                  await api.patch(`/transactions/${id}/parties/${peek.party.id}`, contactPayload());
                  cancelForm();
                }, "Party updated");
              }, "Save")
            ) : (
              <>
                <div className="peek-sec">Assigned tasks · {peek.open_tasks.length} open</div>
                {peek.open_tasks.length === 0 && peek.done_tasks.length === 0 ? (
                  <div className="muted" style={{ fontSize: "0.85rem" }}>
                    Nothing assigned yet — drag a task onto this person, or use “Needs an owner”.
                  </div>
                ) : (
                  <>
                    {peek.open_tasks.map((t) => (
                      <div key={t.id} className="peek-task"><Icon name="clipboard" size={13} /> {t.title}</div>
                    ))}
                    {peek.done_tasks.map((t) => (
                      <div key={t.id} className="peek-task done" style={{ opacity: 0.6 }}>
                        <Icon name="checkCircle" size={13} /> {t.title}
                      </div>
                    ))}
                  </>
                )}

                <div className="pform-actions" style={{ marginTop: "1.1rem", flexWrap: "wrap" }}>
                  <button className="secondary" disabled={busy} onClick={() => startEdit(peek.party)}>Edit contact</button>
                  {isInvitable(peek.party) && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const r = await api.post<PartyAccessToken>(`/transactions/${id}/parties/${peek.party.id}/access-token`);
                          const link = `${window.location.origin}${window.location.pathname}#invite=${encodeURIComponent(r.access_token)}`;
                          setTokens((t) => ({ ...t, [peek.party.id]: link }));
                        }, "Invite link ready")
                      }
                    >
                      <Icon name="key" size={13} /> Invite link
                    </button>
                  )}
                  {isInvitable(peek.party) && peek.party.email && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const r = await api.post<{ sent: boolean; to?: string; link?: string; detail?: string }>(
                            `/transactions/${id}/parties/${peek.party.id}/invite-email`,
                            { base_url: `${window.location.origin}${window.location.pathname}` },
                          );
                          if (r.sent) toast(`Invite emailed to ${r.to}`);
                          else {
                            if (r.link) await navigator.clipboard?.writeText(r.link);
                            toast(`${r.detail ?? "Email sending isn't enabled yet"} — link copied instead`);
                          }
                        })
                      }
                    >
                      <Icon name="mail" size={13} /> Email invite
                    </button>
                  )}
                  <button className="secondary" onClick={() => setPeek(null)}>Close</button>
                </div>

                {tokens[peek.party.id] && (
                  <div className="token-box">
                    <div className="between" style={{ marginBottom: "0.4rem" }}>
                      <span className="muted" style={{ fontSize: "0.76rem" }}>
                        {isCollaborator(peek.party)
                          ? "Read-only view of this deal — no other party's private info."
                          : "Scoped to their own task only — enforced by the database."}
                      </span>
                      <button
                        className="secondary sm"
                        onClick={() => { void navigator.clipboard?.writeText(tokens[peek.party.id]); toast("Link copied"); }}
                      >
                        Copy
                      </button>
                    </div>
                    <textarea readOnly rows={2} value={tokens[peek.party.id]} onFocus={(e) => e.target.select()} />
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
