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
  Task,
} from "../lib/api";
import { Ring, toast } from "../lib/ui";
import { fmtDate } from "../lib/format";
import { Icon, IconName } from "../lib/icons";
import { PartyOrbit } from "./PartyOrbit";

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
  const [taskForm, setTaskForm] = useState({ desc: "", due: "", priority: "normal" });
  const [taskFormOpen, setTaskFormOpen] = useState(false);
  // Drag-to-assign (task → an orbiting party) + party peek popover
  const [dragTaskId, setDragTaskId] = useState<string | null>(null);
  const [peek, setPeek] = useState<DashboardPartyView | null>(null);
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
  const parties: DealParty[] = state.parties;

  // Two non-overlapping lists. "My tasks" = unassigned tasks with no natural
  // external owner (the TC's own coordination work + anything they add). "To
  // assign" = unassigned tasks that route to a party (inspection→inspector,
  // loan→lender, …) — shown next to the orbit to drag onto someone. Once a
  // to-assign task is given an owner it leaves both lists and lives on the party.
  const byDue = (a: Task, b: Task) => {
    const da = state.deadlines.find((d) => d.id === a.deadline_id)?.due_date ?? "9999";
    const db = state.deadlines.find((d) => d.id === b.deadline_id)?.due_date ?? "9999";
    return da.localeCompare(db);
  };
  const myTasks: Task[] = state.tasks
    .filter((t) => t.assigned_party_id === null && routeFor(t.title).roles.length === 0)
    .sort(byDue);
  const toAssign: Task[] = state.tasks
    .filter((t) => t.assigned_party_id === null && routeFor(t.title).roles.length > 0)
    .sort(byDue);

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
  function addTask() {
    const title = newTask.trim();
    if (!title) return;
    void run(async () => {
      await api.post(`/transactions/${id}/tasks`, {
        title,
        description: taskForm.desc.trim() || null,
        due_date: taskForm.due || null,
        priority: taskForm.priority,
      });
      setNewTask("");
      setTaskForm({ desc: "", due: "", priority: "normal" });
      setTaskFormOpen(false);
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

        </aside>

        <div className="il-main">
      {/* ---- My tasks — the TC's own work, with Attention pinned on top ---- */}
      <div className="card">
        <div className="between" style={{ marginBottom: "0.6rem" }}>
          <h2 style={{ margin: 0 }}><Icon name="checkCircle" size={17} /> My tasks</h2>
          <span className="assign-hint">
            {myTasks.filter((t) => !["done", "complete"].includes(t.status)).length} open · what you handle yourself
          </span>
        </div>

        {dash.risk_alerts.length > 0 && (
          <div className="attn">
            <div className="attn-head"><Icon name="warning" size={15} /> Needs attention · {dash.risk_alerts.length}</div>
            {dash.risk_alerts.map((f) => (
              <div key={f.id} className={`attn-item ${f.severity}`}>
                <div className="attn-ic"><Icon name={riskIcon(f)} size={14} /></div>
                <div style={{ minWidth: 0 }}>
                  <div className="attn-title">
                    {titleize(f.case_key)}
                    <span className={`badge ${f.severity === "warning" ? "warn" : "danger"}`}>{f.severity}</span>
                  </div>
                  <div className="attn-desc">{f.description}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="tc-composer">
          <div className="tc-row">
            <input
              placeholder="Add a task for yourself…"
              value={newTask}
              onChange={(e) => setNewTask(e.target.value)}
              onFocus={() => setTaskFormOpen(true)}
              onKeyDown={(e) => { if (e.key === "Enter" && newTask.trim()) addTask(); }}
            />
            <button className="secondary sm" onClick={() => setTaskFormOpen((o) => !o)} title="More options">
              <Icon name={taskFormOpen ? "chevron" : "plus"} size={14} />
            </button>
            <button className="gold" disabled={busy || !newTask.trim()} onClick={addTask}>Add</button>
          </div>
          {taskFormOpen && (
            <div className="tc-more">
              <textarea
                placeholder="Description (optional)…"
                rows={2}
                value={taskForm.desc}
                onChange={(e) => setTaskForm({ ...taskForm, desc: e.target.value })}
              />
              <div className="tc-meta">
                <label className="tc-field">
                  <span><Icon name="calendar" size={12} /> Due date</span>
                  <input type="date" value={taskForm.due} onChange={(e) => setTaskForm({ ...taskForm, due: e.target.value })} />
                </label>
                <label className="tc-field">
                  <span><Icon name="flag" size={12} /> Priority</span>
                  <select value={taskForm.priority} onChange={(e) => setTaskForm({ ...taskForm, priority: e.target.value })}>
                    <option value="low">Low</option>
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </label>
              </div>
            </div>
          )}
        </div>
        {myTasks.length === 0 && (
          <div className="empty"><span className="empty-ic"><Icon name="clipboard" size={26} /></span>Nothing on your own plate — add a task, or assign deadline tasks to parties below.</div>
        )}
        <div className="stack">
          {myTasks.map((t) => {
            const done = ["done", "complete"].includes(t.status);
            const due =
              t.due_date ??
              (t.deadline_id ? state.deadlines.find((d) => d.id === t.deadline_id)?.due_date ?? null : null);
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
            const pr = t.priority && t.priority !== "normal" ? t.priority : null;
            return (
              <div key={t.id} className={`task-row ${done ? "done" : ""} ${pr ? `pr-${pr}` : ""}`}>
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
                  {t.description && <div className="task-desc">{t.description}</div>}
                  {due && (
                    <div className="task-meta">
                      <span style={{ color: dueColor, fontWeight: daysLeft != null && daysLeft <= 5 ? 600 : 400 }}>
                        <Icon name="calendar" size={12} /> {fmtDate(due)}
                        {daysLeft != null &&
                          (daysLeft < 0
                            ? ` · ${-daysLeft}d overdue`
                            : daysLeft === 0
                              ? " · today"
                              : ` · ${daysLeft}d`)}
                      </span>
                    </div>
                  )}
                </div>
                {pr && <span className={`pri-badge ${pr}`}>{pr}</span>}
                <span className={`badge ${done ? "ok" : "draft"}`}>{t.status.replace(/_/g, " ")}</span>
              </div>
            );
          })}
        </div>
      </div>

      </div>
      </div>

      {/* ---- Parties · orbital deal system (always on, full width) ---- */}
      <div className="card parties-orbit">
        <div className="pv-head" style={{ padding: "1.15rem 1.3rem 0.2rem" }}>
          <h2><Icon name="users" size={17} /> Parties</h2>
          <span className="muted" style={{ marginLeft: "auto", fontSize: "0.8rem" }}>
            {dragTaskId ? "Drop the task on a person to assign it" : "Hover to pause · click a person · badge = open tasks"}
          </span>
        </div>
        <div className="po-split">
        <div className="po-orbit">
        <PartyOrbit
          views={dash.parties}
          onSelect={(pv) => setPeek(pv)}
          onAddRole={(role) => startAdd(role)}
          dragging={dragTaskId !== null}
          onDropTask={(party) => { if (dragTaskId) assignTo(dragTaskId, party); setDragTaskId(null); }}
        />
        <div className="orb-legend">
          <span><i style={{ background: "#5257ea" }} /> Buyer</span>
          <span><i style={{ background: "#0e9488" }} /> Seller</span>
          <span><i style={{ background: "#c07512" }} /> Agent</span>
          <span><i style={{ background: "#5b6472" }} /> Escrow · Title · Lender</span>
          <span><i style={{ background: "#8457d6" }} /> Inspection</span>
        </div>
        </div>

        <aside className="po-dock">
        {/* ---- To assign: deadline tasks that belong to a party ---- */}
        <div className="to-assign">
          <div className="ta-head">
            <h3><Icon name="pin" size={15} /> To assign · {toAssign.length}</h3>
            <span className="muted">
              {dragTaskId ? "Drop it on a person in the orbit" : "Drag a card onto a person, or tap the suggestion"}
            </span>
          </div>
          {toAssign.length === 0 ? (
            <div className="ta-empty"><Icon name="checkCircle" size={15} /> Every deadline task has an owner — nice.</div>
          ) : (
            <div className="ta-grid">
              {toAssign.map((t) => {
                const r = routeFor(t.title);
                const suggested = r.roles.map((role) => parties.find((pp) => pp.role === role)).find((pp) => pp);
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
                  void run(() => api.post(`/transactions/${id}/tasks/${t.id}/assign`, { party_id: partyId }), "Task assigned");
                return (
                  <div
                    key={t.id}
                    className={`ta-card ${dragTaskId === t.id ? "dragging" : ""}`}
                    draggable
                    onDragStart={() => setDragTaskId(t.id)}
                    onDragEnd={() => setDragTaskId(null)}
                  >
                    <span className="task-grip" title="Drag onto a person in the orbit to assign">⠿</span>
                    <div className="ta-ic"><Icon name={r.icon} size={15} /></div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="ta-title">{t.title}</div>
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
                    {suggested ? (
                      <button className="gold sm" disabled={busy} onClick={() => assign(suggested.id)} title={`Assign to ${suggested.name ?? suggested.role}`}>
                        → {suggested.name?.split(" ")[0] ?? suggested.role}
                      </button>
                    ) : r.roles.length > 0 ? (
                      <span className="route-need">no {ROLE_SHORT[r.roles[0]] ?? r.roles[0]} yet</span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>
        </aside>
        </div>

        {adding !== null && (
          <div style={{ padding: "0 1.3rem 1.3rem", maxWidth: 440 }}>
            {contactForm(() => {
              void run(async () => {
                await api.post(`/transactions/${id}/parties`, { role: adding, ...contactPayload() });
                cancelForm();
              }, `${PARTY_ROLE_LABEL[adding] ?? adding} added`);
            }, `Add ${PARTY_ROLE_LABEL[adding] ?? adding}`)}
          </div>
        )}
      </div>

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
                    Nothing assigned yet — drag a task from “To assign” onto this person.
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
