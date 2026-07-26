import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { fmtDate } from "../lib/format";

type Deadline = { id: string; name: string; due_date: string };
type Task = { id: string; title: string; status: string; assigned_party_id: string | null; deadline_id: string | null };
type Party = { id: string; name: string | null; role: string };
type Loaded = { address: string | null; deadlines: Deadline[]; tasks: Task[]; parties: Party[] };

function decodeParty(token: string): string | null {
  try {
    return JSON.parse(atob(token.split(".")[1])).app_metadata?.party_id ?? null;
  } catch {
    return null;
  }
}
const isDone = (t: Task) => t.status === "done" || t.status === "complete";

/** The invited party's landing page — a read-only, personalized view of just
 *  their deal, scoped entirely by row-level security on their access token. */
export function InviteView({ token }: { token: string }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const partyId = useMemo(() => decodeParty(token), [token]);

  const sb: SupabaseClient = useMemo(
    () =>
      createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_ANON_KEY, {
        global: { headers: { Authorization: `Bearer ${token}` } },
        auth: { persistSession: false, autoRefreshToken: false },
      }),
    [token],
  );

  const load = useCallback(async () => {
    try {
      const [props, dls, tasks, parties] = await Promise.all([
        sb.from("properties").select("address"),
        sb.from("deadlines").select("id, name, due_date").order("due_date"),
        sb.from("tasks").select("id, title, status, assigned_party_id, deadline_id"),
        sb.from("parties").select("id, name, role"),
      ]);
      if (props.error) throw props.error;
      setData({
        address: props.data?.[0]?.address ?? null,
        deadlines: dls.data ?? [],
        tasks: tasks.data ?? [],
        parties: parties.data ?? [],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "This invite link is invalid or has expired.");
    }
  }, [sb]);
  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(t: Task) {
    setBusy(true);
    try {
      await sb.from("tasks").update({ status: isDone(t) ? "pending" : "done" }).eq("id", t.id);
      await load();
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <div className="inv-wrap">
        <div className="card" style={{ maxWidth: 460, margin: "10vh auto", textAlign: "center" }}>
          <div className="mark" style={{ margin: "0 auto 1rem" }}>T</div>
          <h2>This invite isn't available</h2>
          <p className="muted">{error}</p>
        </div>
      </div>
    );
  }
  if (!data) return <div className="inv-wrap"><p className="muted" style={{ padding: "10vh 2rem", textAlign: "center" }}>Loading…</p></div>;

  const me = data.parties.find((p) => p.id === partyId);
  const mine = data.tasks.filter((t) => t.assigned_party_id === partyId);
  const dateFor = (id: string | null) =>
    id ? data.deadlines.find((d) => d.id === id)?.due_date ?? null : null;

  return (
    <div className="inv-wrap">
      <div className="inv-shell">
        <div className="inv-top">
          <div className="brand">
            <div className="mark">T</div>
            <div>
              <div className="name" style={{ color: "var(--ink)" }}>Terra</div>
              <div className="sub" style={{ color: "var(--muted)" }}>Shared with you</div>
            </div>
          </div>
        </div>

        <div className="card inv-hero">
          <div className="inv-eyebrow">Transaction coordinator · shared a read-only view</div>
          <h1 style={{ margin: "0.2rem 0 0" }}>
            Hi {me?.name ?? "there"} 👋
          </h1>
          <p className="muted" style={{ margin: "0.4rem 0 0" }}>
            Here's the transaction for <b style={{ color: "var(--ink)" }}>{data.address ?? "this property"}</b>.
            You're seeing only what's relevant to you.
          </p>
        </div>

        {mine.length > 0 && (
          <div className="card">
            <h2>✅ Your items</h2>
            <div className="stack">
              {mine.map((t) => {
                const due = dateFor(t.deadline_id);
                const done = isDone(t);
                return (
                  <div key={t.id} className={`task-row ${done ? "done" : ""}`}>
                    <button className="task-check" disabled={busy} onClick={() => void toggle(t)} title={done ? "Reopen" : "Mark done"}>
                      {done ? "✓" : ""}
                    </button>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="task-title">{t.title}</div>
                      {due && <div className="task-meta muted">📅 {fmtDate(due)}</div>}
                    </div>
                    <span className={`badge ${done ? "ok" : "draft"}`}>{t.status}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="card">
          <h2>◷ Deal timeline</h2>
          {data.deadlines.length === 0 ? (
            <div className="empty"><span className="emoji">🗓️</span>No dated milestones yet.</div>
          ) : (
            <div className="stack">
              {data.deadlines.map((d) => (
                <div key={d.id} className="inv-dl">
                  <span className="inv-dl-date">{fmtDate(d.due_date)}</span>
                  <span className="inv-dl-name">{d.name}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="inv-foot muted">
          🔒 Read-only, scoped to this deal — enforced by the database. You can't see other parties'
          private information or any other transaction.
        </p>
      </div>
    </div>
  );
}
