import { useCallback, useEffect, useState } from "react";
import {
  api,
  Dashboard,
  DealParty,
  DealRiskFlag,
  FullState,
  isReceivingEnd,
  PartyAccessToken,
  Task,
} from "../lib/api";
import { Ring, toast } from "../lib/ui";
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

      {/* ---- Party roster ---- */}
      <div className="card">
        <h2>👥 Parties</h2>
        {dash.parties.length === 0 && (
          <div className="empty"><span className="emoji">🤝</span>No parties on the deal yet.</div>
        )}
        <motion.div className="roster" initial="hidden" animate="visible" variants={listStagger}>
          {dash.parties.map((pv) => (
            <motion.div key={pv.party.id} className="party-card" variants={itemUp}>
              <div className="party-top">
                <div className="avatar" style={{ background: avatarColor(pv.party.role) }}>
                  {initials(pv.party.name, pv.party.role)}
                </div>
                <div>
                  <div className="party-name">{pv.party.name ?? "(unnamed)"}</div>
                  <div className="party-role">{pv.party.role.replace(/_/g, " ")}</div>
                </div>
              </div>
              <div className="party-meta">
                <span className="badge navy">{pv.open_tasks.length} open</span>
                <span className="badge ok">{pv.done_tasks.length} done</span>
                {pv.last_message_status && (
                  <span className="badge gold">✉ {pv.last_message_status}</span>
                )}
              </div>
              {isReceivingEnd(pv.party) && (
                <div className="party-actions">
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const r = await api.post<PartyAccessToken>(
                          `/transactions/${id}/parties/${pv.party.id}/access-token`,
                        );
                        setTokens((t) => ({ ...t, [pv.party.id]: r.access_token }));
                      }, "Access link generated")
                    }
                  >
                    🔗 Generate access link
                  </button>
                </div>
              )}
              {tokens[pv.party.id] && (
                <div className="token-box">
                  <textarea readOnly rows={2} value={tokens[pv.party.id]} />
                  <p className="muted">Scoped to their own task only — enforced by the database.</p>
                </div>
              )}
            </motion.div>
          ))}
        </motion.div>
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
                    <span className="badge sent">sent · {m.sent_at}</span>
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
