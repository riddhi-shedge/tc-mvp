import { useCallback, useEffect, useState } from "react";
import {
  api,
  Dashboard,
  DealParty,
  FullState,
  isReceivingEnd,
  PartyAccessToken,
  Task,
} from "../lib/api";

/** Prompt 7 dashboard: per-party drill-down of outstanding items, role-count
 *  progress, prioritized risk alerts, and a communication center. Assigning a
 *  task and generating a receiving-end access link happen here; the link's
 *  permissions are enforced by the database (RLS), not this screen. */
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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tokens, setTokens] = useState<Record<string, string>>({});
  // Which party each unassigned task is about to be assigned to.
  const [assignTo, setAssignTo] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      setDash(await api.get<Dashboard>(`/transactions/${id}/dashboard`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  if (!dash) return <p className="muted">Loading dashboard…</p>;

  const assignableParties: DealParty[] = state.parties;
  const unassignedTasks: Task[] = state.tasks.filter((t) => t.assigned_party_id === null);
  const progress = dash.party_progress;

  return (
    <>
      <div className="card">
        <h2>Deal dashboard — parties &amp; progress</h2>

        <p className="muted">
          {progress.buyers_total} buyer{progress.buyers_total === 1 ? "" : "s"} on file ·{" "}
          {progress.proof_of_funds_confirmed} proof-of-funds document
          {progress.proof_of_funds_confirmed === 1 ? "" : "s"} confirmed ·{" "}
          {progress.disclosures_confirmed} disclosure
          {progress.disclosures_confirmed === 1 ? "" : "s"} confirmed
        </p>
        {error && <p className="error">{error}</p>}

        {dash.parties.length === 0 && <p className="muted">No parties yet.</p>}
        {dash.parties.map((pv) => (
          <div key={pv.party.id} style={{ marginBottom: "1rem" }}>
            <strong>{pv.party.name ?? "(unnamed)"}</strong>{" "}
            <span className="badge">{pv.party.role}</span>{" "}
            <span className="muted">
              {pv.open_tasks.length} open · {pv.done_tasks.length} done
              {pv.last_message_status ? ` · last message ${pv.last_message_status}` : ""}
            </span>
            {pv.open_tasks.length > 0 && (
              <ul className="audit">
                {pv.open_tasks.map((t) => (
                  <li key={t.id}>
                    {t.title} <span className="badge draft">{t.status}</span>
                  </li>
                ))}
              </ul>
            )}
            {isReceivingEnd(pv.party) && (
              <div style={{ marginTop: "0.35rem" }}>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const r = await api.post<PartyAccessToken>(
                        `/transactions/${id}/parties/${pv.party.id}/access-token`,
                      );
                      setTokens((t) => ({ ...t, [pv.party.id]: r.access_token }));
                    })
                  }
                >
                  Generate access link
                </button>
                {tokens[pv.party.id] && (
                  <>
                    <label>Scoped access token (their magic-link credential)</label>
                    <textarea readOnly rows={3} value={tokens[pv.party.id]} />
                    <p className="muted">
                      This grants only their own task (mark done) — nothing else. Enforced by
                      the database.
                    </p>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {unassignedTasks.length > 0 && (
        <div className="card">
          <h2>Unassigned tasks</h2>
          <table>
            <tbody>
              {unassignedTasks.map((t) => (
                <tr key={t.id}>
                  <td>{t.title}</td>
                  <td>
                    <select
                      value={assignTo[t.id] ?? ""}
                      onChange={(e) => setAssignTo((a) => ({ ...a, [t.id]: e.target.value }))}
                    >
                      <option value="">— assign to —</option>
                      {assignableParties.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name ?? p.role} ({p.role})
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      disabled={busy || !assignTo[t.id]}
                      onClick={() =>
                        void run(() =>
                          api.post(`/transactions/${id}/tasks/${t.id}/assign`, {
                            party_id: assignTo[t.id],
                          }),
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

      <div className="card">
        <h2>Risk alerts (prioritized)</h2>
        {dash.risk_alerts.length === 0 && <p className="muted">No unresolved alerts.</p>}
        <ul className="audit">
          {dash.risk_alerts.map((f) => (
            <li key={f.id}>
              <span className="badge draft">{f.severity}</span> {f.description}
            </li>
          ))}
        </ul>
      </div>

      <div className="card">
        <h2>Communication center</h2>
        <h3 className="muted">Pending ({dash.communication.pending.length})</h3>
        {dash.communication.pending.length === 0 && <p className="muted">Nothing pending.</p>}
        <ul className="audit">
          {dash.communication.pending.map((m) => (
            <li key={m.id}>
              <span className="badge draft">{m.status}</span> {m.subject ?? "(no subject)"}
            </li>
          ))}
        </ul>
        <h3 className="muted">Sent ({dash.communication.sent.length})</h3>
        <ul className="audit">
          {dash.communication.sent.map((m) => (
            <li key={m.id}>
              <span className="badge sent">sent</span> {m.subject ?? "(no subject)"}{" "}
              <span className="muted">{m.sent_at}</span>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
