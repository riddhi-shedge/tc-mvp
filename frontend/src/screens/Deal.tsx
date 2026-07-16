import { useCallback, useEffect, useState } from "react";
import { api, FullState, Message } from "../lib/api";

/** The deal screen: extraction review → confirm → timeline → risk flags →
 *  lender contact → real lender draft (editable) → Approve & Send (guarded). */
export function Deal({ id, onBack }: { id: string; onBack: () => void }) {
  const [state, setState] = useState<FullState | null>(null);
  const [draftWhy, setDraftWhy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lenderName, setLenderName] = useState("");
  const [lenderEmail, setLenderEmail] = useState("");
  // TC edits to a draft before approval: messageId -> {subject, body}
  const [edits, setEdits] = useState<Record<string, { subject: string; body: string }>>({});

  const refresh = useCallback(async () => {
    try {
      setState(await api.get<FullState>(`/transactions/${id}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load deal");
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  if (!state) return <p className="muted">Loading deal…</p>;

  const fields = state.extracted_fields;
  const unconfirmed = fields.filter((f) => !f.confirmed);
  const unconfirmedDeadline = unconfirmed.filter((f) => f.deadline_driving);
  const drafts: Message[] = state.messages.filter((m) => m.status === "draft");
  const approved: Message[] = state.messages.filter((m) => m.status === "approved");
  const sent = state.messages.filter((m) => m.status === "sent");
  const lender = state.parties.find((p) => p.role === "lender" || p.role === "loan_officer");

  return (
    <>
      <div className="topbar">
        <div>
          <h1>{state.property?.address ?? "(no property)"}</h1>
          <span className="muted">
            deal {state.transaction.id.slice(0, 8)} · {state.transaction.status}
          </span>
        </div>
        <button className="secondary" onClick={onBack}>
          ← Inbox
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h2>Documents</h2>
        {state.documents.length === 0 && <p className="muted">No documents yet.</p>}
        {state.documents.length > 0 && (
          <table>
            <tbody>
              {state.documents.map((d) => (
                <tr key={d.id}>
                  <td>{d.doc_type ?? "unknown"}</td>
                  <td className="muted">{d.external_ref}</td>
                  <td>
                    <span className="badge">{d.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Extraction review (Claude — §5 fields with per-field confidence)</h2>
        {fields.length === 0 && <p className="muted">No extracted fields yet.</p>}
        {fields.length > 0 && (
          <>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th>Confidence</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.id}>
                    <td>
                      {f.name}
                      {f.deadline_driving && <span className="badge draft"> deadline</span>}
                    </td>
                    <td>{f.value}</td>
                    <td>
                      <span className={`conf ${f.confidence >= 0.7 ? "high" : "low"}`}>
                        {Math.round(f.confidence * 100)}%
                      </span>
                    </td>
                    <td>{f.confirmed ? "✓ confirmed" : "pending"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {unconfirmed.length > 0 && (
              <div style={{ marginTop: "0.75rem" }}>
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      api.post(`/transactions/${id}/fields/confirm`, {
                        field_ids: unconfirmed.map((f) => f.id),
                      }),
                    )
                  }
                >
                  Confirm {unconfirmed.length} field{unconfirmed.length > 1 ? "s" : ""}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2>Timeline (hardcoded stub — real CA rules arrive in Phase 5)</h2>
        {unconfirmedDeadline.length > 0 && (
          <div className="why" style={{ borderLeftColor: "#b35c00" }}>
            Timeline BLOCKED: {unconfirmedDeadline.length} deadline-driving field
            {unconfirmedDeadline.length > 1 ? "s" : ""} unconfirmed (
            {unconfirmedDeadline.map((f) => f.name).join(", ")}). Confirm them above first.
          </div>
        )}
        {state.deadlines.length === 0 ? (
          <button
            className="secondary"
            disabled={busy || unconfirmedDeadline.length > 0 || fields.length === 0}
            onClick={() => void run(() => api.post(`/transactions/${id}/timeline/stub`))}
          >
            Generate stub timeline
          </button>
        ) : (
          <table>
            <tbody>
              {state.deadlines.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td>{d.due_date}</td>
                  <td className="muted">
                    {state.tasks.find((t) => t.deadline_id === d.id)?.title}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {state.deadlines.length === 0 && unconfirmed.length > 0 && (
          <p className="muted">Confirm the extracted fields first.</p>
        )}
      </div>

      {state.risk_flags.length > 0 && (
        <div className="card">
          <h2>Risk flags (compliance service)</h2>
          <ul className="audit">
            {state.risk_flags.map((f) => (
              <li key={f.id}>
                <span className="badge draft">{f.severity}</span> {f.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <h2>Lender contact</h2>
        {lender ? (
          <p className="muted">
            {lender.name} &lt;{lender.email ?? "no email"}&gt;
          </p>
        ) : (
          <div className="row">
            <div>
              <input
                placeholder="Lender / loan officer name"
                value={lenderName}
                onChange={(e) => setLenderName(e.target.value)}
              />
            </div>
            <div>
              <input
                placeholder="lender email"
                value={lenderEmail}
                onChange={(e) => setLenderEmail(e.target.value)}
              />
            </div>
            <div style={{ flex: "0 0 auto" }}>
              <button
                disabled={busy || !lenderName || !lenderEmail}
                onClick={() =>
                  void run(async () => {
                    await api.post(`/transactions/${id}/parties`, {
                      name: lenderName,
                      role: "lender",
                      email: lenderEmail,
                    });
                    setLenderName("");
                    setLenderEmail("");
                  })
                }
              >
                Add lender
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Lender follow-up — draft, edit, then Approve &amp; Send (Rule 3)</h2>
        {drafts.length === 0 && sent.length === 0 && (
          <button
            className="secondary"
            disabled={busy || !lender}
            title={!lender ? "Add a lender contact first" : undefined}
            onClick={() =>
              void run(async () => {
                const r = await api.post<{ why: string }>(
                  `/transactions/${id}/messages/draft-lender`,
                );
                setDraftWhy(r.why);
              })
            }
          >
            Draft lender follow-up (Claude)
          </button>
        )}
        {drafts.map((draft) => {
          const edit = edits[draft.id] ?? {
            subject: draft.subject ?? "",
            body: draft.body ?? "",
          };
          return (
            <div key={draft.id} style={{ marginBottom: "1rem" }}>
              <span className="badge draft">draft</span>
              {draftWhy && <div className="why">WHY: {draftWhy}</div>}
              <label>Subject</label>
              <input
                value={edit.subject}
                onChange={(e) =>
                  setEdits({ ...edits, [draft.id]: { ...edit, subject: e.target.value } })
                }
              />
              <label>Body (edit before sending)</label>
              <textarea
                rows={6}
                value={edit.body}
                onChange={(e) =>
                  setEdits({ ...edits, [draft.id]: { ...edit, body: e.target.value } })
                }
              />
              <div style={{ marginTop: "0.5rem" }}>
                <button
                  className="danger-ish"
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      api.post(`/transactions/${id}/messages/${draft.id}/approve-and-send`, {
                        subject: edit.subject,
                        body: edit.body,
                      }),
                    )
                  }
                >
                  Approve &amp; Send
                </button>
              </div>
            </div>
          );
        })}
        {approved.map((m) => (
          <div key={m.id} style={{ marginBottom: "0.75rem" }}>
            <strong>{m.subject}</strong>{" "}
            <span className="badge draft">approved — not sent</span>
            <div className="muted">
              Approved but the send didn't go through (sending disabled, recipient not
              allow-listed, or a provider error). Retry when ready.
            </div>
            <button
              className="danger-ish"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  api.post(`/transactions/${id}/messages/${m.id}/approve-and-send`),
                )
              }
            >
              Retry send
            </button>
          </div>
        ))}
        {sent.map((m) => (
          <p key={m.id}>
            <strong>{m.subject}</strong> <span className="badge sent">sent</span>{" "}
            <span className="muted">{m.sent_at}</span>
          </p>
        ))}
      </div>

      <div className="card">
        <h2>Audit trail</h2>
        <ul className="audit">
          {[...state.audit_log].reverse().map((a, i) => (
            <li key={i}>
              <code>{a.action}</code> — {a.actor}{" "}
              <span className="muted">{a.created_at}</span>
              {a.details["fake"] === true && <span className="badge">fake</span>}
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
