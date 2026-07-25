import { useCallback, useEffect, useState } from "react";
import {
  api,
  Dashboard,
  DashboardPartyView,
  DealParty,
  DealRiskFlag,
  FullState,
  isReceivingEnd,
  PartyAccessToken,
  PARTY_ROLE_LABEL,
  PARTY_ROSTER,
  Task,
} from "../lib/api";
import { Ring, toast } from "../lib/ui";
import { fmtDateTime } from "../lib/format";
import { motion } from "framer-motion";

const listStagger = { visible: { transition: { staggerChildren: 0.055 } } };
const itemUp = { hidden: { opacity: 0, y: 14 }, visible: { opacity: 1, y: 0 } };
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
function riskIcon(f: DealRiskFlag): string {
  const c = (f.case_key ?? "").toLowerCase();
  if (c.includes("inspection")) return "🔍";
  if (c.includes("appraisal")) return "🏷️";
  if (c.includes("loan")) return "🏦";
  if (c.includes("escrow")) return "🔑";
  if (c.includes("earnest") || c.includes("deposit")) return "📌";
  if (c.includes("disclosure")) return "📄";
  if (c.includes("closing")) return "⏰";
  return f.severity === "critical" || f.severity === "high" ? "⚠️" : "❕";
}
function titleize(s: string | null): string {
  return (s ?? "Attention").replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

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
  const [assignTo, setAssignTo] = useState<Record<string, string>>({});
  const [newTask, setNewTask] = useState("");
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
  const buyers = Math.max(p.buyers_total, 1);
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
  function partyCard(pv: DashboardPartyView) {
    const pt = pv.party;
    return (
      <motion.div key={pt.id} className="party-card" variants={itemUp}>
        <div className="party-top">
          <div className="avatar" style={{ background: avatarColor(pt.role) }}>{initials(pt.name, pt.role)}</div>
          <div style={{ minWidth: 0 }}>
            <div className="party-name">{pt.name ?? "(unnamed)"}</div>
            <div className="party-role">{PARTY_ROLE_LABEL[pt.role] ?? pt.role.replace(/_/g, " ")}</div>
          </div>
        </div>
        {(pt.company || pt.phone || pt.email) && (
          <div className="party-contact">
            {pt.company && <div>🏢 {pt.company}</div>}
            {pt.phone && <div>📞 {pt.phone}</div>}
            {pt.email && <div>✉️ {pt.email}</div>}
          </div>
        )}
        <div className="party-meta">
          <span className="badge navy">{pv.open_tasks.length} open</span>
          <span className="badge ok">{pv.done_tasks.length} done</span>
          {pv.last_message_status && <span className="badge gold">✉ {pv.last_message_status}</span>}
        </div>
        <div className="party-actions">
          <button className="secondary sm" disabled={busy} onClick={() => startEdit(pt)}>✎ Edit</button>
          {isReceivingEnd(pt) && (
            <button
              className="secondary sm"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const r = await api.post<PartyAccessToken>(
                    `/transactions/${id}/parties/${pt.id}/access-token`,
                  );
                  setTokens((t) => ({ ...t, [pt.id]: r.access_token }));
                }, "Access link generated")
              }
            >
              🔗 Access link
            </button>
          )}
        </div>
        {editing === pt.id &&
          contactForm(() => {
            void run(async () => {
              await api.patch(`/transactions/${id}/parties/${pt.id}`, contactPayload());
              cancelForm();
            }, "Party updated");
          }, "Save")}
        {tokens[pt.id] && (
          <div className="token-box">
            <textarea readOnly rows={2} value={tokens[pt.id]} />
            <p className="muted">Scoped to their own task only — enforced by the database.</p>
          </div>
        )}
      </motion.div>
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
      {/* ---- Bento overview ---- */}
      <div className="bento">
        <div className="card lift b-2">
          <h3>Deal health</h3>
          <div className="ring-wrap">
            <Ring value={completion}>
              <div>
                <div className="rc-num">{Math.round(completion * 100)}%</div>
                <div className="rc-sub">tasks done</div>
              </div>
            </Ring>
            <div className="stack" style={{ gap: "0.35rem" }}>
              <div><strong>{doneTasks}</strong> <span className="muted">of {totalTasks} tasks complete</span></div>
              <div><strong>{state.deadlines.length}</strong> <span className="muted">deadlines tracked</span></div>
              <div><strong>{dash.risk_alerts.length}</strong> <span className="muted">open risk alerts</span></div>
            </div>
          </div>
        </div>

        <div className="card lift stat-tile">
          <div className="st-label">Proof of funds</div>
          <div className="st-value">
            {p.proof_of_funds_confirmed}<span className="st-of"> / {p.buyers_total}</span>
          </div>
          <div className="prog-seg">
            {Array.from({ length: buyers }).map((_, i) => (
              <span key={i} className={i < p.proof_of_funds_confirmed ? "on" : ""} />
            ))}
          </div>
        </div>

        <div className="card lift stat-tile">
          <div className="st-label">Disclosures</div>
          <div className="st-value">{p.disclosures_confirmed}</div>
          <div className="muted">confirmed on file</div>
        </div>
      </div>

      {/* ---- Risk attention feed ---- */}
      <div className="card">
        <h2>🚨 Attention</h2>
        {dash.risk_alerts.length === 0 && (
          <div className="empty"><span className="emoji">✅</span>No open risk alerts — nicely on track.</div>
        )}
        <motion.div className="risk-feed" initial="hidden" animate="visible" variants={listStagger}>
          {dash.risk_alerts.map((f) => (
            <motion.div key={f.id} className={`risk-card ${f.severity}`} variants={itemIn}>
              <div className="risk-ic">{riskIcon(f)}</div>
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

      {/* ---- Party roster (grouped; auto-filled from the contract) ---- */}
      <div className="card">
        <div className="between" style={{ marginBottom: "0.2rem" }}>
          <h2 style={{ margin: 0 }}>👥 Parties</h2>
          <span className="muted">Auto-filled from the contract · complete the rest</span>
        </div>

        {PARTY_ROSTER.map((grp) => {
          const groupRoles = grp.roles.map((r) => r.role);
          const cards = dash.parties.filter((v) => groupRoles.includes(v.party.role));
          return (
            <div key={grp.group} className="pgroup">
              <div className="pgroup-label">{grp.group}</div>
              {cards.length > 0 && (
                <motion.div
                  className="roster"
                  initial="hidden"
                  animate="visible"
                  variants={listStagger}
                >
                  {cards.map((pv) => partyCard(pv))}
                </motion.div>
              )}
              <div className="pslots">
                {grp.roles.map((r) => {
                  const has = dash.parties.some((v) => v.party.role === r.role);
                  return (
                    <button
                      key={r.role}
                      className={`pslot ${has ? "" : "empty"}`}
                      disabled={busy}
                      onClick={() => startAdd(r.role)}
                    >
                      ＋ {has ? `add ${r.label.toLowerCase()}` : r.label}
                    </button>
                  );
                })}
              </div>
              {adding !== null &&
                groupRoles.includes(adding) &&
                contactForm(() => {
                  void run(async () => {
                    await api.post(`/transactions/${id}/parties`, {
                      role: adding,
                      ...contactPayload(),
                    });
                    cancelForm();
                  }, `${PARTY_ROLE_LABEL[adding] ?? adding} added`);
                }, "Add party")}
            </div>
          );
        })}

        {otherParties.length > 0 && (
          <div className="pgroup">
            <div className="pgroup-label">Other</div>
            <motion.div className="roster" initial="hidden" animate="visible" variants={listStagger}>
              {otherParties.map((pv) => partyCard(pv))}
            </motion.div>
          </div>
        )}
      </div>

      {/* ---- Tasks (compliance + the TC's own) ---- */}
      <div className="card">
        <div className="between" style={{ marginBottom: "0.6rem" }}>
          <h2 style={{ margin: 0 }}>✅ Tasks</h2>
          <span className="muted">
            {state.tasks.filter((t) => !["done", "complete"].includes(t.status)).length} open
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
          <div className="empty"><span className="emoji">📋</span>No tasks yet.</div>
        )}
        <div className="stack">
          {state.tasks.map((t) => {
            const done = ["done", "complete"].includes(t.status);
            const who = t.assigned_party_id
              ? parties.find((p) => p.id === t.assigned_party_id)?.name ?? "assigned"
              : null;
            return (
              <div key={t.id} className={`task-row ${done ? "done" : ""}`}>
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
                  {who && (
                    <div className="muted" style={{ fontSize: "0.78rem" }}>→ {who}</div>
                  )}
                </div>
                <span className={`badge ${done ? "ok" : "draft"}`}>{t.status.replace(/_/g, " ")}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* ---- Unassigned tasks ---- */}
      {unassigned.length > 0 && (
        <div className="card">
          <h2>Unassigned tasks</h2>
          <table>
            <tbody>
              {unassigned.map((t) => (
                <tr key={t.id}>
                  <td>{t.title}</td>
                  <td style={{ width: 200 }}>
                    <select
                      value={assignTo[t.id] ?? ""}
                      onChange={(e) => setAssignTo((a) => ({ ...a, [t.id]: e.target.value }))}
                    >
                      <option value="">— assign to —</option>
                      {parties.map((pp) => (
                        <option key={pp.id} value={pp.id}>
                          {pp.name ?? pp.role} ({pp.role})
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={{ width: 90, textAlign: "right" }}>
                    <button
                      disabled={busy || !assignTo[t.id]}
                      onClick={() =>
                        void run(
                          () =>
                            api.post(`/transactions/${id}/tasks/${t.id}/assign`, {
                              party_id: assignTo[t.id],
                            }),
                          "Task assigned",
                        )
                      }
                    >
                      Assign
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ---- Communication center ---- */}
      <div className="card">
        <h2>💬 Communication</h2>
        <h3>Pending ({dash.communication.pending.length})</h3>
        {dash.communication.pending.length === 0 && (
          <div className="empty" style={{ padding: "1rem" }}><span className="emoji">📭</span>Nothing pending.</div>
        )}
        <div className="stack">
          {dash.communication.pending.map((m) => (
            <div key={m.id} className="doc-card">
              <div className="doc-ic">✉️</div>
              <div style={{ minWidth: 0, flex: 1 }} className="between">
                <span style={{ color: "var(--ink)" }}>{m.subject ?? "(no subject)"}</span>
                <span className={`badge ${m.status === "approved" ? "ok" : "draft"}`}>{m.status}</span>
              </div>
            </div>
          ))}
        </div>
        {dash.communication.sent.length > 0 && (
          <>
            <h3>Sent ({dash.communication.sent.length})</h3>
            <div className="stack">
              {dash.communication.sent.map((m) => (
                <div key={m.id} className="doc-card">
                  <div className="doc-ic">📤</div>
                  <div style={{ minWidth: 0, flex: 1 }} className="between">
                    <span style={{ color: "var(--ink)" }}>{m.subject ?? "(no subject)"}</span>
                    <span className="badge sent">sent · {fmtDateTime(m.sent_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
