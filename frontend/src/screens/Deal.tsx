import { useCallback, useEffect, useState } from "react";
import { api, AuditRow, FullState, Message } from "../lib/api";
import { fmtDate, fmtDateTime } from "../lib/format";
import { ExtractionReview } from "./ExtractionReview";
import { DealDashboard } from "./DealDashboard";
import { DealTimeline } from "./DealTimeline";
import { AnimatedTabs, CountUp, toast } from "../lib/ui";
import { Icon, IconName } from "../lib/icons";

function docIcon(t: string | null): IconName {
  const s = (t ?? "").toLowerCase();
  if (s.includes("purchase")) return "contract";
  if (s.includes("proof")) return "money";
  if (s.includes("disclosure")) return "clipboard";
  if (s.includes("inspection")) return "search";
  return "doc";
}
// A distinct tint per document type so the icon reads at a glance.
function docTint(t: string | null): string {
  const s = (t ?? "").toLowerCase();
  if (s.includes("purchase")) return "#5257ea";
  if (s.includes("proof")) return "#0e9488";
  if (s.includes("disclosure")) return "#c07512";
  if (s.includes("inspection")) return "#8457d6";
  return "#5b6472";
}
function actionIcon(a: string): IconName {
  if (a.includes("created")) return "sparkle";
  if (a.includes("payload") || a.includes("extract")) return "search";
  if (a.includes("confirm")) return "check";
  if (a.includes("message")) return "mail";
  if (a.includes("party")) return "user";
  if (a.includes("task")) return "pin";
  if (a.includes("compliance") || a.includes("timeline") || a.includes("deadline")) return "calendar";
  if (a.includes("token")) return "key";
  return "chevron";
}
function humanize(s: string): string {
  return s.replace(/[._]/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
/** A short hint for hand-entering a missing deadline-driving field. */
function fieldHint(name: string): string {
  if (name === "possession_date") return "defaults to close of escrow if unspecified";
  if (name.endsWith("_date")) return "e.g. 2026-07-10 (YYYY-MM-DD)";
  if (name.endsWith("_days")) return "number of days (or 'waived')";
  if (name === "close_of_escrow") return "a date, or days after acceptance";
  return "value as written on the agreement";
}
/** Pre-filled value the TC confirms/edits — the RPA's default when the box is
 *  blank. Non-silent: it's shown for confirmation, never auto-applied. */
function fieldSuggestion(name: string): string {
  if (name === "possession_date") return "at close of escrow";
  return "";
}

// Email purposes the drafter personalizes to the deal (mirror of drafting.PURPOSES).
const MESSAGE_PURPOSES: { value: string; label: string }[] = [
  { value: "lender_status", label: "Lender status request" },
  { value: "appraisal_status", label: "Appraisal status" },
  { value: "inspection_schedule", label: "Schedule inspection" },
  { value: "disclosure_reminder", label: "Disclosure reminder" },
  { value: "escrow_checkin", label: "Escrow check-in" },
  { value: "intro", label: "Intro / point of contact" },
  { value: "general", label: "General check-in" },
];

// Recipient avatar tint by role (mirrors the parties palette).
const MSG_TINT: Record<string, string> = {
  buyer: "#5257ea", seller: "#0e9488", buyer_agent: "#c07512", listing_agent: "#c07512",
  escrow: "#5b6472", title: "#5b6472", lender: "#5b6472",
};
const msgTint = (role: string | undefined) => (role && MSG_TINT[role]) || "#5b6472";
function msgInitials(name: string | null, role: string): string {
  const s = (name || role || "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}
const snippet = (body: string | null) => (body ?? "").replace(/\s+/g, " ").trim().slice(0, 72);

/** The deal screen: extraction review → confirm → timeline → risk flags →
 *  lender contact → real lender draft (editable) → Approve & Send (guarded). */
export function Deal({ id, onBack }: { id: string; onBack: () => void }) {
  const [state, setState] = useState<FullState | null>(null);
  const [draftWhy, setDraftWhy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recipientId, setRecipientId] = useState("");
  const [purpose, setPurpose] = useState("lender_status");
  // TC edits to a draft before approval: messageId -> {subject, body}
  const [edits, setEdits] = useState<Record<string, { subject: string; body: string }>>({});
  // Split-inbox selection ("new" = composer) + which message the last WHY belongs to
  const [selMsg, setSelMsg] = useState<string | null>(null);
  const [draftWhyFor, setDraftWhyFor] = useState<string | null>(null);
  // TC entries for deadline-driving fields the extraction missed: name -> value
  const [fieldVals, setFieldVals] = useState<Record<string, string>>({});
  // Deal Q&A chat (grounded on this deal's records).
  const [chat, setChat] = useState<{ role: "you" | "ai"; text: string }[]>([]);
  const [chatQ, setChatQ] = useState("");
  const [chatBusy, setChatBusy] = useState(false);

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

  // Open a stored document in a new tab via a short-lived signed URL. Open one
  // blank tab synchronously (so the popup isn't blocked) and keep the handle —
  // NOT with `noopener`, which makes window.open return null and caused a second
  // tab to open. Then navigate that same tab once the URL resolves.
  function openDoc(docId: string) {
    const tab = window.open("about:blank", "_blank");
    void (async () => {
      try {
        const { url } = await api.get<{ url: string }>(
          `/transactions/${id}/documents/${docId}/signed-url`,
        );
        if (tab) {
          tab.opener = null; // sever the opener for security, without a 2nd tab
          tab.location.replace(url);
        } else {
          // Only reached if the synchronous open was popup-blocked.
          window.open(url, "_blank", "noopener");
        }
      } catch (e) {
        tab?.close();
        toast(e instanceof Error ? e.message : "Couldn't open document", { error: true });
      }
    })();
  }

  // Grounded Q&A: ask the assistant a question about this deal.
  function ask(q: string) {
    const question = q.trim();
    if (!question || chatBusy) return;
    setChat((c) => [...c, { role: "you", text: question }]);
    setChatQ("");
    setChatBusy(true);
    void (async () => {
      try {
        const r = await api.post<{ answer: string }>(`/transactions/${id}/ask`, { question });
        setChat((c) => [...c, { role: "ai", text: r.answer }]);
      } catch (e) {
        setChat((c) => [...c, { role: "ai", text: e instanceof Error ? e.message : "Couldn't answer right now." }]);
      } finally {
        setChatBusy(false);
      }
    })();
  }

  if (!state) return <p className="muted">Loading deal…</p>;

  const fields = state.extracted_fields;
  const unconfirmed = fields.filter((f) => !f.confirmed);
  const gate = state.timeline_gate;
  const blocking = gate ? gate.missing_fields.length + gate.unconfirmed_fields.length : 0;

  const drafts: Message[] = state.messages.filter((m) => m.status === "draft");
  const approved: Message[] = state.messages.filter((m) => m.status === "approved");
  const sent = state.messages.filter((m) => m.status === "sent");
  const recipients = state.parties.filter((p) => p.email);

  // Split-inbox ordering: action-needed first (drafts, then approved-not-sent), then sent.
  const allMsgs: Message[] = [...drafts, ...approved, ...sent];
  const sel = selMsg ?? (allMsgs[0]?.id ?? "new");
  const selMessage = sel === "new" ? null : allMsgs.find((m) => m.id === sel) ?? null;
  const msgPartyOf = (m: Message) => state.parties.find((p) => p.id === m.party_id);

  // Follow-up reminders that have come due with no logged reply (Feature B).
  const dueReminders = (state.reminders ?? [])
    .filter((r) => new Date(r.remind_at).getTime() <= Date.now())
    .map((r) => {
      const m = r.message_id ? state.messages.find((x) => x.id === r.message_id) ?? null : null;
      const party = m?.party_id ? state.parties.find((p) => p.id === m.party_id) ?? null : null;
      return { r, m, party };
    });

  // --- Log: resolve entity ids to human names for a readable audit table ---
  const taskTitleById = (tid?: string | null) => state.tasks.find((t) => t.id === tid)?.title;
  const partyById = (pid?: string | null) => state.parties.find((p) => p.id === pid);
  const msgSubjectById = (mid?: string | null) => state.messages.find((m) => m.id === mid)?.subject;
  const deadlineNameById = (did?: string | null) => state.deadlines.find((d) => d.id === did)?.name;

  function auditTarget(a: AuditRow): string {
    const id = a.entity_id;
    switch (a.entity_type) {
      case "task": { const t = taskTitleById(id); return t ? `Task · ${t}` : "Task"; }
      case "party": { const p = partyById(id); return p ? `${p.name ?? humanize(p.role)} · ${humanize(p.role)}` : "Party"; }
      case "message": { const s = msgSubjectById(id); return s ? `Message · ${s}` : "Message"; }
      case "deadline": return deadlineNameById(id) ?? "Deadline";
      case "transaction": return "Deal";
      case "extracted_field":
      case "field": return "Field";
      case "risk_flag": return "Risk flag";
      case "reminder": return "Reminder";
      case "payload": return "Document";
      default: return a.entity_type ? humanize(a.entity_type) : "—";
    }
  }

  function auditDetails(a: AuditRow): string {
    if (!a.details) return "";
    const out: string[] = [];
    const partyName = (v: unknown) => partyById(String(v))?.name ?? "someone";
    for (const [k, v] of Object.entries(a.details)) {
      if (v == null || v === "" || k === "provider_message_id") continue;
      if (k === "party_id" || k === "assigned_party_id") out.push(`→ ${partyName(v)}`);
      else if (k === "task_id") out.push(`task “${taskTitleById(String(v)) ?? "…"}”`);
      else if (k === "message_id") out.push(`re “${msgSubjectById(String(v)) ?? "…"}”`);
      else if (k === "field") out.push(`field: ${humanize(String(v))}`);
      else if (k === "kind") out.push(`purpose: ${humanize(String(v))}`);
      else if (k === "source") out.push(v === "tc" ? "added by the TC" : `source: ${v}`);
      else if (k === "status") out.push(`status: ${humanize(String(v))}`);
      else if (k === "stage") out.push(`stage: ${humanize(String(v))}`);
      else if (k === "reason" && v) out.push(`reason: ${v}`);
      else if (k === "old" || k === "new") out.push(`${k}: ${v}`);
      else out.push(`${humanize(k)}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
    }
    return out.join(" · ");
  }

  const coe = state.deadlines.find((d) => d.name.toLowerCase().includes("escrow"));
  const coeDays =
    coe != null ? Math.round((new Date(coe.due_date).getTime() - Date.now()) / 86_400_000) : null;
  const openTasks = state.tasks.filter((t) => !["done", "complete"].includes(t.status)).length;
  const unresolvedRisks = state.risk_flags.filter((f) => !f.resolved).length;

  return (
    <>
      <div className="between" style={{ marginBottom: "1rem" }}>
        <button className="secondary" onClick={onBack}>← Deals</button>
        <div className="row" style={{ gap: "0.5rem" }}>
          {state.transaction.status === "canceled" ? (
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void run(() => api.post(`/transactions/${id}/reactivate`), "Deal reactivated")}
            >
              Reactivate deal
            </button>
          ) : (
            <button
              className="secondary"
              disabled={busy}
              onClick={() => {
                const reason = window.prompt(
                  "Mark this deal as fallen through / canceled (e.g. buyer backed out during inspection). Optional reason:",
                  "",
                );
                if (reason === null) return;
                void run(() => api.post(`/transactions/${id}/cancel`, { reason }), "Deal marked fell through");
              }}
            >
              Mark fell through
            </button>
          )}
          <button
            className="secondary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.post(`/transactions/${id}/archive`);
                toast("Deal archived");
                onBack();
              } catch (e) {
                toast(e instanceof Error ? e.message : "Failed to archive", { error: true });
                setBusy(false);
              }
            }}
          >
            Archive
          </button>
          <button
            className="danger-ish"
            disabled={busy}
            onClick={async () => {
              if (
                !window.confirm(
                  "Permanently delete this deal and everything under it (parties, timeline, tasks, messages, audit log)? This cannot be undone.",
                )
              )
                return;
              setBusy(true);
              try {
                await api.del(`/transactions/${id}`);
                toast("Deal deleted");
                onBack();
              } catch (e) {
                toast(e instanceof Error ? e.message : "Failed to delete", { error: true });
                setBusy(false);
              }
            }}
          >
            Delete
          </button>
        </div>
      </div>
      {state.transaction.status === "canceled" && (
        <div className="deal-canceled">
          <Icon name="warning" size={16} /> This deal fell through / was canceled — kept for your records. Use
          “Reactivate deal” to resume it.
        </div>
      )}
      <div className="deal-header">
        <div className="between">
          <div>
            <h1>{state.property?.address ?? "(no property on file)"}</h1>
            <div className="addr-sub">
              Deal {state.transaction.id.slice(0, 8)} · California residential
            </div>
          </div>
          <span className={`badge ${state.transaction.status === "canceled" ? "danger" : "ok"}`}>
            <span className={`dot ${state.transaction.status === "canceled" ? "danger" : "open"}`} />{" "}
            {state.transaction.status === "canceled" ? "fell through" : state.transaction.status}
          </span>
        </div>
        <div className="kpis">
          <div className="kpi">
            <div className="k-label">Close of escrow</div>
            <div className="k-value accent">
              {coe ? fmtDate(coe.due_date) : "—"}
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
            <span className="gate-ic"><Icon name="calendar" size={20} /></span>
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
              {gate.missing_fields.map((name) => {
                const val = fieldVals[name] ?? fieldSuggestion(name);
                return (
                  <div key={name} className="gate-row">
                    <label className="gate-fname">{humanize(name)}</label>
                    <input
                      value={val}
                      placeholder={fieldHint(name)}
                      onChange={(e) => setFieldVals({ ...fieldVals, [name]: e.target.value })}
                    />
                    <button
                      className="gold"
                      disabled={busy || !val.trim()}
                      onClick={() =>
                        void run(async () => {
                          await api.post(`/transactions/${id}/fields`, { name, value: val.trim() });
                          setFieldVals((v) => ({ ...v, [name]: "" }));
                        }, `${humanize(name)} added`)
                      }
                    >
                      Add
                    </button>
                  </div>
                );
              })}
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
                <Icon name="check" size={14} /> Confirm {gate.unconfirmed_fields.length} deadline field
                {gate.unconfirmed_fields.length > 1 ? "s" : ""}
              </button>
            </div>
          )}
        </div>
      )}

      {gate?.ready && fields.length > 0 && state.deadlines.length === 0 && (
        <div className="card gate-card ready">
          <div className="gate-head">
            <span className="gate-ic"><Icon name="checkCircle" size={20} /></span>
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
            {busy ? "Building…" : <><Icon name="calendar" size={14} /> Build timeline</>}
          </button>
        </div>
      )}

      {state.deadlines.length > 0 && (
        <DealTimeline
          id={id}
          deadlines={state.deadlines}
          tasks={state.tasks}
          acceptanceDate={fields.find((f) => f.name === "acceptance_date")?.value ?? null}
          onChanged={refresh}
        />
      )}

      <AnimatedTabs
        tabs={[
          {
            id: "overview",
            label: "Overview",
            icon: <Icon name="board" size={14} />,
            content: <DealDashboard id={id} state={state} onChanged={refresh} />,
          },
          {
            id: "documents",
            label: "Documents",
            icon: <Icon name="doc" size={14} />,
            content: (
              <>
      <div className="card askbot">
        <h2><Icon name="sparkle" size={17} /> Ask about this deal</h2>
        <p className="muted" style={{ margin: "-0.4rem 0 0.85rem" }}>
          Ask anything about the contract, dates, parties, or documents — answered only from this deal's records,
          or it'll tell you it couldn't find it.
        </p>
        <div className="ask-log">
          {chat.length === 0 && (
            <div className="ask-suggest">
              {[
                "When is close of escrow?",
                "What's the earnest money deposit?",
                "Who is the buyer's agent and their email?",
                "Which contingencies are in play?",
              ].map((s) => (
                <button key={s} className="ask-chip" onClick={() => ask(s)}>{s}</button>
              ))}
            </div>
          )}
          {chat.map((m, i) => (
            <div key={i} className={`ask-msg ${m.role}`}>
              {m.role === "ai" && <div className="ask-ava"><Icon name="sparkle" size={13} /></div>}
              <div className="ask-bubble">{m.text}</div>
            </div>
          ))}
          {chatBusy && (
            <div className="ask-msg ai">
              <div className="ask-ava"><Icon name="sparkle" size={13} /></div>
              <div className="ask-bubble"><span className="spinner" /> Thinking…</div>
            </div>
          )}
        </div>
        <div className="ask-input">
          <input
            placeholder="Ask a question about this deal…"
            value={chatQ}
            disabled={chatBusy}
            onChange={(e) => setChatQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && chatQ.trim()) ask(chatQ); }}
          />
          <button className="gold" disabled={chatBusy || !chatQ.trim()} onClick={() => ask(chatQ)}>Ask</button>
        </div>
      </div>

      <div className="card">
        <h2><Icon name="doc" size={17} /> Documents</h2>
        {state.documents.length === 0 && (
          <div className="empty"><span className="empty-ic"><Icon name="doc" size={26} /></span>No documents yet.</div>
        )}
        {state.documents.length > 0 && (
          <div className="doc-grid">
            {state.documents.map((d) => (
              <button
                key={d.id}
                type="button"
                className="doc-card"
                onClick={() => openDoc(d.id)}
                title="Open document in a new tab"
              >
                <div className="doc-ic" style={{ background: `${docTint(d.doc_type)}1f`, color: docTint(d.doc_type) }}>
                  <Icon name={docIcon(d.doc_type)} size={24} />
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="doc-name">{humanize(d.doc_type ?? "unknown")}</div>
                  {d.created_at && (
                    <div className="muted" style={{ fontSize: "0.76rem", margin: "1px 0 4px" }}>
                      Uploaded {fmtDate(d.created_at)}
                    </div>
                  )}
                  <span className={`badge ${d.status === "confirmed" ? "ok" : "draft"}`}>
                    {d.status}
                  </span>
                </div>
                <span className="doc-open"><Icon name="external" size={15} /></span>
              </button>
            ))}
          </div>
        )}
      </div>

      <ExtractionReview
        state={state}
        busy={busy}
        onConfirmAll={() =>
          void run(
            () =>
              api.post(`/transactions/${id}/fields/confirm`, {
                field_ids: unconfirmed.map((f) => f.id),
              }),
            `${unconfirmed.length} field${unconfirmed.length > 1 ? "s" : ""} confirmed`,
          )
        }
        onVerify={(field, value) =>
          void run(async () => {
            const v = value.trim();
            if (v && v !== field.value) {
              // Corrected value → overwrite (a known §5 name re-add also confirms it).
              await api.post(`/transactions/${id}/fields`, { name: field.name, value: v });
            } else {
              await api.post(`/transactions/${id}/fields/confirm`, { field_ids: [field.id] });
            }
          }, "Field verified")
        }
      />

              </>
            ),
          },
          {
            id: "comms",
            label: "Communication",
            icon: <Icon name="mail" size={14} />,
            content: (
              <>
      {dueReminders.length > 0 && (
        <div className="card awaiting">
          <h2><Icon name="clock" size={17} /> Awaiting reply · {dueReminders.length}</h2>
          <p className="muted" style={{ margin: "-0.4rem 0 0.8rem" }}>
            You sent these and no reply is logged yet — follow up, or dismiss if it's handled.
          </p>
          <div className="stack">
            {dueReminders.map(({ r, m, party }) => (
              <div key={r.id} className="await-row">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="await-subj">{m?.subject ?? "(message)"}</div>
                  <div className="muted" style={{ fontSize: "0.78rem" }}>
                    to {party?.name ?? "recipient"}
                    {m?.sent_at ? ` · sent ${fmtDate(m.sent_at)}` : ""}
                  </div>
                </div>
                <button
                  className="gold sm"
                  disabled={busy || !party}
                  onClick={() => {
                    if (party) {
                      setRecipientId(party.id);
                      setPurpose("general");
                      setSelMsg("new");
                    }
                  }}
                >
                  <Icon name="sparkle" size={13} /> Follow up
                </button>
                <button
                  className="secondary sm"
                  disabled={busy}
                  onClick={() => void run(() => api.del(`/transactions/${id}/reminders/${r.id}`), "Dismissed")}
                >
                  Dismiss
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card mailbox">
        <div className="mbx">
          <div className="mbx-list">
            <div className="mbx-lhead">
              <b>Messages</b>
              <button className={`mbx-new ${sel === "new" ? "on" : ""}`} onClick={() => setSelMsg("new")}>
                <Icon name="sparkle" size={13} /> New
              </button>
            </div>
            {allMsgs.length === 0 && <div className="mbx-listempty">No messages yet — start one with “New”.</div>}
            {allMsgs.map((m) => {
              const party = msgPartyOf(m);
              return (
                <div key={m.id} className={`mbx-item ${sel === m.id ? "on" : ""}`} onClick={() => setSelMsg(m.id)}>
                  <div className="mbx-ava" style={{ background: msgTint(party?.role) }}>
                    {msgInitials(party?.name ?? null, party?.role ?? "")}
                  </div>
                  <div className="mbx-meta">
                    <div className="mbx-row1">
                      <span className="mbx-to">{party?.name ?? "Recipient"}</span>
                      <span className="mbx-time">
                        {m.status === "sent" && m.sent_at ? fmtDate(m.sent_at) : m.status === "draft" ? "draft" : "queued"}
                      </span>
                    </div>
                    <div className="mbx-subj">{m.subject ?? "(no subject)"}</div>
                    <div className="mbx-snip">{snippet(m.body)}</div>
                  </div>
                  <span className={`mbx-dot ${m.status}`} />
                </div>
              );
            })}
          </div>

          <div className="mbx-pane">
            {sel === "new" || !selMessage ? (
              <div className="mbx-compose">
                <div className="mbx-ctitle"><Icon name="sparkle" size={16} /> New message</div>
                <p className="muted" style={{ margin: "0 0 1.1rem" }}>
                  Claude drafts it personalized to this deal · you review the WHY, edit, and approve.
                  Nothing sends without your tap (Rule 3).
                </p>
                {recipients.length === 0 ? (
                  <div className="empty">
                    <span className="empty-ic"><Icon name="mail" size={26} /></span>
                    No recipients with an email yet — add emails on the Parties (Overview) tab.
                  </div>
                ) : (
                  <>
                    <label>To</label>
                    <select value={recipientId} onChange={(e) => setRecipientId(e.target.value)}>
                      <option value="">— choose recipient —</option>
                      {recipients.map((p) => (
                        <option key={p.id} value={p.id}>{p.name} · {humanize(p.role)} ({p.email})</option>
                      ))}
                    </select>
                    <label>Purpose</label>
                    <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
                      {MESSAGE_PURPOSES.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                    <button
                      className="gold"
                      style={{ marginTop: "1.1rem" }}
                      disabled={busy || !recipientId}
                      onClick={() =>
                        void run(async () => {
                          const r = await api.post<{ message: Message; why: string }>(
                            `/transactions/${id}/messages/draft`,
                            { party_id: recipientId, purpose },
                          );
                          setDraftWhy(r.why);
                          setDraftWhyFor(r.message.id);
                          setSelMsg(r.message.id);
                        }, "Draft ready for review")
                      }
                    >
                      {busy ? (<><span className="spinner" /> Drafting…</>) : (<><Icon name="sparkle" size={14} /> Draft with Claude</>)}
                    </button>
                  </>
                )}
              </div>
            ) : (
              (() => {
                const m = selMessage;
                const party = msgPartyOf(m);
                const edit = edits[m.id] ?? { subject: m.subject ?? "", body: m.body ?? "" };
                return (
                  <div className="mbx-read">
                    <div className="mbx-phead">
                      <div className="mbx-ava lg" style={{ background: msgTint(party?.role) }}>
                        {msgInitials(party?.name ?? null, party?.role ?? "")}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div className="mbx-pto">{party?.name ?? "Recipient"}</div>
                        <div className="mbx-prole">{humanize(party?.role ?? "")}{party?.email ? ` · ${party.email}` : ""}</div>
                      </div>
                      <span className={`badge ${m.status === "sent" ? "sent" : "draft"}`} style={{ marginLeft: "auto" }}>
                        {m.status === "sent" ? "sent" : m.status === "approved" ? "approved · not sent" : "draft"}
                      </span>
                    </div>

                    {m.status === "draft" ? (
                      <>
                        {draftWhy && draftWhyFor === m.id && (
                          <div className="why"><strong>Why this draft:</strong> {draftWhy}</div>
                        )}
                        <label>Subject</label>
                        <input value={edit.subject} onChange={(e) => setEdits({ ...edits, [m.id]: { ...edit, subject: e.target.value } })} />
                        <label>Body — edit before sending</label>
                        <textarea rows={11} value={edit.body} onChange={(e) => setEdits({ ...edits, [m.id]: { ...edit, body: e.target.value } })} />
                        <div className="mbx-actions">
                          <button
                            className="gold"
                            disabled={busy}
                            onClick={() =>
                              void run(
                                () => api.post(`/transactions/${id}/messages/${m.id}/approve-and-send`, { subject: edit.subject, body: edit.body }),
                                "Approved & sent",
                              )
                            }
                          >
                            <Icon name="check" size={14} /> Approve &amp; Send
                          </button>
                          <button
                            className="secondary"
                            disabled={busy}
                            onClick={() => {
                              if (!window.confirm("Discard this draft? This can't be undone.")) return;
                              void run(async () => {
                                await api.del(`/transactions/${id}/messages/${m.id}`);
                                if (draftWhyFor === m.id) { setDraftWhy(null); setDraftWhyFor(null); }
                                setSelMsg("new");
                              }, "Draft discarded");
                            }}
                          >
                            <Icon name="x" size={14} /> Discard
                          </button>
                          <span className="mbx-guard"><Icon name="lock" size={12} /> Nothing sends without your tap</span>
                        </div>
                      </>
                    ) : m.status === "approved" ? (
                      <>
                        <div className="mbx-subject">{m.subject}</div>
                        <div className="mbx-bodyview">{m.body}</div>
                        <p className="muted" style={{ fontSize: "0.82rem" }}>
                          Approved, but the send didn’t go through (sending disabled, recipient not allow-listed, or a provider error).
                        </p>
                        <div className="mbx-actions">
                          <button
                            className="gold"
                            disabled={busy}
                            onClick={() => void run(() => api.post(`/transactions/${id}/messages/${m.id}/approve-and-send`), "Retried")}
                          >
                            Retry send
                          </button>
                          <button
                            className="secondary"
                            disabled={busy}
                            onClick={() => {
                              if (!window.confirm("Discard this message? This can't be undone.")) return;
                              void run(async () => {
                                await api.del(`/transactions/${id}/messages/${m.id}`);
                                setSelMsg("new");
                              }, "Message discarded");
                            }}
                          >
                            <Icon name="x" size={14} /> Discard
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="mbx-subject">{m.subject}</div>
                        <div className="mbx-bodyview">{m.body}</div>
                        <div className="mbx-sentnote"><Icon name="check" size={13} /> Sent {m.sent_at ? fmtDateTime(m.sent_at) : ""}</div>
                      </>
                    )}
                  </div>
                );
              })()
            )}
          </div>
        </div>
      </div>

              </>
            ),
          },
          {
            id: "log",
            label: "Log",
            icon: <Icon name="receipt" size={14} />,
            content: (
      <div className="card">
        <h2><Icon name="receipt" size={17} /> Log</h2>
        <p className="muted" style={{ margin: "-0.4rem 0 0.85rem" }}>
          Every action on this deal — uploads, field confirmations, timeline builds, assignments, messages, and
          approvals — newest first. {state.audit_log.length} entries.
        </p>
        <div className="log-wrap">
          <table className="log-table">
            <thead>
              <tr><th>When</th><th>Who</th><th>Action</th><th>On</th><th>Details</th></tr>
            </thead>
            <tbody>
              {[...state.audit_log].reverse().map((a, i) => (
                <tr key={i}>
                  <td className="log-when tnum">{fmtDateTime(a.created_at)}</td>
                  <td className="log-who">{a.actor}</td>
                  <td>
                    <span className="log-act"><Icon name={actionIcon(a.action)} size={12} /> {humanize(a.action)}</span>
                  </td>
                  <td className="log-on">{auditTarget(a)}</td>
                  <td className="log-det">{auditDetails(a) || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
            ),
          },
        ]}
      />
    </>
  );
}
