import { useCallback, useEffect, useState } from "react";
import { api, FullState, Message } from "../lib/api";
import { DealDashboard } from "./DealDashboard";
import { DealTimeline } from "./DealTimeline";
import { AnimatedTabs, CountUp, toast } from "../lib/ui";

function docIcon(t: string | null): string {
  const s = (t ?? "").toLowerCase();
  if (s.includes("purchase")) return "🏡";
  if (s.includes("proof")) return "💵";
  if (s.includes("disclosure")) return "📋";
  if (s.includes("inspection")) return "🔍";
  return "📄";
}
function actionIcon(a: string): string {
  if (a.includes("created")) return "✨";
  if (a.includes("payload") || a.includes("extract")) return "🔎";
  if (a.includes("confirm")) return "✓";
  if (a.includes("message")) return "✉️";
  if (a.includes("party")) return "👤";
  if (a.includes("task")) return "📌";
  if (a.includes("compliance") || a.includes("timeline") || a.includes("deadline")) return "🗓️";
  if (a.includes("token")) return "🔗";
  return "•";
}
function humanize(s: string): string {
  return s.replace(/[._]/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
/** A short hint for hand-entering a missing deadline-driving field. */
function fieldHint(name: string): string {
  if (name.endsWith("_date")) return "e.g. 2026-07-10 (YYYY-MM-DD)";
  if (name.endsWith("_days")) return "number of days (or 'waived')";
  if (name === "close_of_escrow") return "a date, or days after acceptance";
  if (name === "possession_date") return "date/time terms as written";
  return "value as written on the agreement";
}

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
  // TC entries for deadline-driving fields the extraction missed: name -> value
  const [fieldVals, setFieldVals] = useState<Record<string, string>>({});

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

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
      if (ok) toast(ok);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setError(msg);
      toast(msg, { error: true });
    } finally {
      setBusy(false);
    }
  }

  if (!state) return <p className="muted">Loading deal…</p>;

  const fields = state.extracted_fields;
  const unconfirmed = fields.filter((f) => !f.confirmed);
  const gate = state.timeline_gate;
  const blocking = gate ? gate.missing_fields.length + gate.unconfirmed_fields.length : 0;
  const drafts: Message[] = state.messages.filter((m) => m.status === "draft");
  const approved: Message[] = state.messages.filter((m) => m.status === "approved");
  const sent = state.messages.filter((m) => m.status === "sent");
  const lender = state.parties.find((p) => p.role === "lender" || p.role === "loan_officer");

  const coe = state.deadlines.find((d) => d.name.toLowerCase().includes("escrow"));
  const coeDays =
    coe != null ? Math.round((new Date(coe.due_date).getTime() - Date.now()) / 86_400_000) : null;
  const openTasks = state.tasks.filter((t) => !["done", "complete"].includes(t.status)).length;
  const unresolvedRisks = state.risk_flags.filter((f) => !f.resolved).length;

  return (
    <>
      <button className="secondary" onClick={onBack} style={{ marginBottom: "1rem" }}>
        ← Inbox &amp; Deals
      </button>
      <div className="deal-header">
        <div className="between">
          <div>
            <h1>{state.property?.address ?? "(no property on file)"}</h1>
            <div className="addr-sub">
              Deal {state.transaction.id.slice(0, 8)} · California residential
            </div>
          </div>
          <span className="badge ok" style={{ background: "rgba(255,255,255,.12)", color: "#eef2f9" }}>
            <span className="dot open" /> {state.transaction.status}
          </span>
        </div>
        <div className="kpis">
          <div className="kpi">
            <div className="k-label">Close of escrow</div>
            <div className="k-value accent">
              {coe ? coe.due_date : "—"}
            </div>
          </div>
          <div className="kpi">
            <div className="k-label">COE countdown</div>
            <div className="k-value">{coeDays != null ? <CountUp value={coeDays} suffix="d" /> : "—"}</div>
          </div>
          <div className="kpi">
            <div className="k-label">Open tasks</div>
            <div className="k-value"><CountUp value={openTasks} /></div>
          </div>
          <div className="kpi">
            <div className="k-label">Risk alerts</div>
            <div className="k-value"><CountUp value={unresolvedRisks} /></div>
          </div>
        </div>
      </div>
      {error && <p className="error">{error}</p>}

      {gate && !gate.ready && (
        <div className="card gate-card">
          <div className="gate-head">
            <span className="gate-ic">🗓️</span>
            <div>
              <h2 style={{ margin: 0 }}>Finish the timeline</h2>
              <p className="muted" style={{ margin: "3px 0 0" }}>
                {blocking} deadline-driving field{blocking > 1 ? "s" : ""} still needed before the
                CA deadlines can compute.
              </p>
            </div>
          </div>

          {gate.missing_fields.length > 0 && (
            <div className="gate-sec">
              <div className="gate-sec-label">
                Missing — enter from the purchase agreement
              </div>
              {gate.missing_fields.map((name) => (
                <div key={name} className="gate-row">
                  <label className="gate-fname">{humanize(name)}</label>
                  <input
                    value={fieldVals[name] ?? ""}
                    placeholder={fieldHint(name)}
                    onChange={(e) => setFieldVals({ ...fieldVals, [name]: e.target.value })}
                  />
                  <button
                    className="gold"
                    disabled={busy || !(fieldVals[name] ?? "").trim()}
                    onClick={() =>
                      void run(async () => {
                        await api.post(`/transactions/${id}/fields`, {
                          name,
                          value: (fieldVals[name] ?? "").trim(),
                        });
                        setFieldVals((v) => ({ ...v, [name]: "" }));
                      }, `${humanize(name)} added`)
                    }
                  >
                    Add
                  </button>
                </div>
              ))}
            </div>
          )}

          {gate.unconfirmed_fields.length > 0 && (
            <div className="gate-sec">
              <div className="gate-sec-label">Extracted — confirm to lock in</div>
              <div className="gate-chips">
                {gate.unconfirmed_fields.map((name) => (
                  <span key={name} className="gate-chip">
                    {humanize(name)}
                  </span>
                ))}
              </div>
              <button
                className="gold"
                disabled={busy}
                style={{ marginTop: "0.75rem" }}
                onClick={() =>
                  void run(
                    () =>
                      api.post(`/transactions/${id}/fields/confirm`, {
                        field_ids: fields
                          .filter((f) => gate.unconfirmed_fields.includes(f.name))
                          .map((f) => f.id),
                      }),
                    "Deadline fields confirmed",
                  )
                }
              >
                ✓ Confirm {gate.unconfirmed_fields.length} deadline field
                {gate.unconfirmed_fields.length > 1 ? "s" : ""}
              </button>
            </div>
          )}
        </div>
      )}

      {gate?.ready && fields.length > 0 && state.deadlines.length === 0 && (
        <div className="card gate-card ready">
          <div className="gate-head">
            <span className="gate-ic">✅</span>
            <div>
              <h2 style={{ margin: 0 }}>Ready to build</h2>
              <p className="muted" style={{ margin: "3px 0 0" }}>
                Every deadline-driving field is in and confirmed — build the CA timeline.
              </p>
            </div>
          </div>
          <button
            className="gold"
            disabled={busy}
            style={{ marginTop: "0.9rem" }}
            onClick={() =>
              void run(
                () => api.post(`/transactions/${id}/build-timeline`),
                "Timeline built",
              )
            }
          >
            {busy ? "Building…" : "🗓️ Build timeline"}
          </button>
        </div>
      )}

      {state.deadlines.length > 0 && (
        <DealTimeline
          deadlines={state.deadlines}
          acceptanceDate={fields.find((f) => f.name === "acceptance_date")?.value ?? null}
        />
      )}

      <AnimatedTabs
        tabs={[
          {
            id: "overview",
            label: "Overview",
            icon: "◧",
            content: <DealDashboard id={id} state={state} onChanged={refresh} />,
          },
          {
            id: "documents",
            label: "Documents",
            icon: "📄",
            content: (
              <>
      <div className="card">
        <h2>📄 Documents</h2>
        {state.documents.length === 0 && (
          <div className="empty"><span className="emoji">📄</span>No documents yet.</div>
        )}
        {state.documents.length > 0 && (
          <div className="doc-grid">
            {state.documents.map((d) => (
              <div key={d.id} className="doc-card">
                <div className="doc-ic">{docIcon(d.doc_type)}</div>
                <div style={{ minWidth: 0 }}>
                  <div className="doc-name">{(d.doc_type ?? "unknown").replace(/_/g, " ")}</div>
                  <span className={`badge ${d.status === "confirmed" ? "ok" : "draft"}`}>
                    {d.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="between" style={{ marginBottom: "0.9rem" }}>
          <h2 style={{ margin: 0 }}>🔎 Extraction review</h2>
          <span className="muted">Claude · §5 fields, per-field confidence</span>
        </div>
        {fields.length === 0 && (
          <div className="empty"><span className="emoji">🔎</span>No extracted fields yet.</div>
        )}
        {fields.length > 0 && (
          <>
            <div className="field-grid">
              {fields.map((f) => {
                const pct = Math.round(f.confidence * 100);
                return (
                  <div key={f.id} className={`field-card ${f.confirmed ? "confirmed" : ""}`}>
                    {f.confirmed && <span className="fc-check">✓</span>}
                    <div className="fc-label">
                      {f.name.replace(/_/g, " ")}
                      {f.deadline_driving && <span className="badge gold">deadline</span>}
                    </div>
                    <div className="fc-value">{f.value}</div>
                    <div className="fc-bar">
                      <span className={f.confidence >= 0.7 ? "high" : "low"} style={{ width: `${pct}%` }} />
                    </div>
                    <div className="fc-foot">
                      <span className="muted">{pct}% confidence</span>
                      <span className={f.confirmed ? "" : "muted"} style={f.confirmed ? { color: "var(--green-700)", fontWeight: 600 } : undefined}>
                        {f.confirmed ? "confirmed" : "pending"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
            {unconfirmed.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <button
                  className="gold"
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () =>
                        api.post(`/transactions/${id}/fields/confirm`, {
                          field_ids: unconfirmed.map((f) => f.id),
                        }),
                      `${unconfirmed.length} field${unconfirmed.length > 1 ? "s" : ""} confirmed`,
                    )
                  }
                >
                  ✓ Confirm {unconfirmed.length} field{unconfirmed.length > 1 ? "s" : ""}
                </button>
              </div>
            )}
          </>
        )}
      </div>

              </>
            ),
          },
          {
            id: "lender",
            label: "Lender",
            icon: "🏦",
            content: (
              <>
      <div className="card">
        <h2>🏦 Lender contact</h2>
        {lender ? (
          <div className="party-top">
            <div className="avatar" style={{ background: "#2f7d5b" }}>
              {(lender.name ?? "L").slice(0, 2).toUpperCase()}
            </div>
            <div>
              <div className="party-name">{lender.name}</div>
              <div className="party-role" style={{ textTransform: "none" }}>
                {lender.email ?? "no email on file"}
              </div>
            </div>
          </div>
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
        <h2>✉️ Lender follow-up</h2>
        <p className="muted" style={{ margin: "-0.4rem 0 0.85rem" }}>
          Claude drafts it · you review the WHY, edit, and approve. Nothing sends without your tap (Rule 3).
        </p>
        {drafts.length === 0 && sent.length === 0 && approved.length === 0 && (
          <button
            className="gold"
            disabled={busy || !lender}
            title={!lender ? "Add a lender contact first" : undefined}
            onClick={() =>
              void run(async () => {
                const r = await api.post<{ why: string }>(
                  `/transactions/${id}/messages/draft-lender`,
                );
                setDraftWhy(r.why);
              }, "Draft ready for review")
            }
          >
            ✨ Draft with Claude
          </button>
        )}
        {drafts.map((draft) => {
          const edit = edits[draft.id] ?? { subject: draft.subject ?? "", body: draft.body ?? "" };
          return (
            <div key={draft.id} className="mailcard">
              <div className="mailcard-head">
                <span className="mailcard-to">
                  To: {lender?.name ?? "lender"} &lt;{lender?.email ?? "—"}&gt;
                </span>
                <span className="badge draft">draft</span>
              </div>
              <div className="mailcard-body">
                {draftWhy && (
                  <div className="why">
                    <strong>Why this draft:</strong> {draftWhy}
                  </div>
                )}
                <label>Subject</label>
                <input
                  value={edit.subject}
                  onChange={(e) =>
                    setEdits({ ...edits, [draft.id]: { ...edit, subject: e.target.value } })
                  }
                />
                <label>Body — edit before sending</label>
                <textarea
                  rows={6}
                  value={edit.body}
                  onChange={(e) =>
                    setEdits({ ...edits, [draft.id]: { ...edit, body: e.target.value } })
                  }
                />
                <div style={{ marginTop: "0.7rem" }}>
                  <button
                    className="danger-ish"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () =>
                          api.post(`/transactions/${id}/messages/${draft.id}/approve-and-send`, {
                            subject: edit.subject,
                            body: edit.body,
                          }),
                        "Approved & sent",
                      )
                    }
                  >
                    ✓ Approve &amp; Send
                  </button>
                </div>
              </div>
            </div>
          );
        })}
        {approved.map((m) => (
          <div key={m.id} className="mailcard">
            <div className="mailcard-head">
              <span className="mailcard-to">{m.subject}</span>
              <span className="badge draft">approved · not sent</span>
            </div>
            <div className="mailcard-body">
              <p className="muted" style={{ marginTop: 0 }}>
                Approved, but the send didn't go through (sending disabled, recipient not
                allow-listed, or a provider error). Retry when ready.
              </p>
              <button
                className="danger-ish"
                disabled={busy}
                onClick={() =>
                  void run(
                    () => api.post(`/transactions/${id}/messages/${m.id}/approve-and-send`),
                    "Retried",
                  )
                }
              >
                Retry send
              </button>
            </div>
          </div>
        ))}
        {sent.map((m) => (
          <div key={m.id} className="mailcard">
            <div className="mailcard-head">
              <span className="mailcard-to">{m.subject}</span>
              <span className="badge sent">✓ sent · {m.sent_at}</span>
            </div>
          </div>
        ))}
      </div>

              </>
            ),
          },
          {
            id: "activity",
            label: "Activity",
            icon: "🧾",
            content: (
      <div className="card">
        <h2>🧾 Activity</h2>
        <ul className="feed">
          {[...state.audit_log].reverse().map((a, i) => (
            <li key={i}>
              <div className="fd-ic">{actionIcon(a.action)}</div>
              <div>
                <div className="fd-title">{humanize(a.action)}</div>
                <div className="fd-actor">
                  {a.actor} · {new Date(a.created_at).toLocaleString()}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
            ),
          },
        ]}
      />
    </>
  );
}
