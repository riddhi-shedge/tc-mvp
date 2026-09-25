import { useEffect, useRef, useState } from "react";
import { api, AttentionItem, FullState } from "../lib/api";
import { fmtDate } from "../lib/format";
import { Icon } from "../lib/icons";
import { Runway } from "./Runway";

/** P-A: the deal context panel beside the decision queue. Answers "can I act
 *  without opening the deal?" — header facts, the deadline runway, the Rule-3
 *  approval card for the selected draft (full recipient + why + editable body),
 *  recent events, people. `Open deal` stays the escape hatch for deep work. */

const STAGE_LABEL: Record<string, string> = { new: "New offer", cont: "Contingencies", closing: "Closing", closed: "Closed" };

function initials(n: string | null | undefined) {
  const s = (n ?? "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function DealPeek({
  item, busy, onApprove, onDismiss, onResolve, onChase, onOpenDeal, onReviewFields,
}: {
  item: AttentionItem | null;
  busy: boolean;
  onApprove: (it: AttentionItem, edited?: { body?: string }) => void;
  onDismiss: (it: AttentionItem) => void;
  onResolve: (it: AttentionItem) => void;
  onChase: (it: AttentionItem) => void;
  onOpenDeal: (id: string) => void;
  onReviewFields: (id: string) => void;
}) {
  const [state, setState] = useState<FullState | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [body, setBody] = useState("");
  // Short-lived per-open cache: cleared whenever the peek acts on a deal so a
  // just-approved draft can't show a stale digest.
  const cache = useRef(new Map<string, FullState>());
  const dealId = item?.dealId ?? null;

  useEffect(() => {
    if (!dealId) return setState(null);
    setLoadFailed(false);
    const hit = cache.current.get(dealId);
    if (hit) { setState(hit); return; }
    setState(null);
    let live = true;
    api.get<FullState>(`/transactions/${dealId}`)
      .then((s) => { cache.current.set(dealId, s); if (live) setState(s); })
      .catch(() => { if (live) { setState(null); setLoadFailed(true); } });
    return () => { live = false; };
  }, [dealId]);

  useEffect(() => { setBody(item?.body ?? ""); }, [item?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!item) return <div className="pk pk-empty">Select an item to preview its deal.<br /><span className="muted">j/k to move · Enter to act · o opens the full deal</span></div>;

  const eff = state?.effective_fields ?? {};
  const price = eff.purchase_price?.value ?? null;
  const stage = state ? (STAGE_LABEL[(state as unknown as { transaction: { stage?: string } }).transaction.stage ?? ""] ?? null) : null;
  const coe = state?.deadlines?.find((x) => x.name.toLowerCase().includes("escrow"))?.due_date ?? null;
  const parties = state?.parties ?? [];
  const digest = (state?.digest ?? []).slice(0, 5);

  return (
    <div className="pk">
      <div className="pk-card pk-head">
        <div className="pk-addr">{item.address}</div>
        <div className="pk-meta">
          {stage && <span className="pk-stage">{stage}</span>}
          {price && <span><b>{price}</b></span>}
          {coe && <span>COE <b className="tnum">{fmtDate(coe)}</b></span>}
          <button className="kbtn" style={{ marginLeft: "auto" }} onClick={() => onOpenDeal(item.dealId)}>
            Open deal <kbd className="pk-kbd">o</kbd>
          </button>
        </div>
      </div>

      <div className="pk-card">
        <div className="pk-sect">Deadline runway · next 10 business days</div>
        {state ? (
          <Runway items={state.deadlines ?? []} />
        ) : (
          <div className="pk-load">{loadFailed ? "Couldn't load this deal. Open it to retry." : "Loading…"}</div>
        )}
      </div>

      {item.kind === "draft" && (
        <div className="pk-card">
          <div className="pk-sect">Approve &amp; send</div>
          <div className="pk-to">
            To <b>{item.recipientName ?? "recipient"}</b>
            {item.recipientRole ? ` · ${item.recipientRole.replace(/_/g, " ")}` : ""} · email
          </div>
          {item.why && <div className="pk-why"><Icon name="sparkle" size={13} /><span><b>Why:</b> {item.why}</span></div>}
          <textarea className="pk-body" value={body} rows={7} onChange={(e) => setBody(e.target.value)} aria-label="Draft body" />
          <div className="pk-actions">
            <button className="kbtn pri" disabled={busy} onClick={() => onApprove(item, body !== item.body ? { body } : undefined)}>
              <Icon name="check" size={13} /> Approve &amp; send <kbd className="pk-kbd">↵</kbd>
            </button>
            <button className="kbtn" disabled={busy} onClick={() => onDismiss(item)}>Dismiss <kbd className="pk-kbd">d</kbd></button>
          </div>
        </div>
      )}
      {item.kind === "reminder" && (
        <div className="pk-card">
          <div className="pk-sect">No reply</div>
          <div className="pk-line">{item.title}</div>
          <div className="pk-actions">
            {item.messageId && <button className="kbtn pri" disabled={busy} onClick={() => onChase(item)}>Draft chase <kbd className="pk-kbd">↵</kbd></button>}
            <button className="kbtn" disabled={busy} onClick={() => onDismiss(item)}>Dismiss <kbd className="pk-kbd">d</kbd></button>
          </div>
        </div>
      )}
      {item.kind === "gate" && (
        <div className="pk-card">
          <div className="pk-sect">Timeline blocked</div>
          <div className="pk-line">{item.detail}</div>
          {item.fields && <div className="pk-fields">{item.fields.map((f) => <span key={f} className="pk-field">{f.replace(/_/g, " ")}</span>)}</div>}
          <div className="pk-actions">
            <button className="kbtn pri" onClick={() => onReviewFields(item.dealId)}>Review fields <kbd className="pk-kbd">↵</kbd></button>
          </div>
        </div>
      )}
      {item.kind === "risk" && (
        <div className="pk-card">
          <div className="pk-sect">Risk flag</div>
          <div className="pk-line">{item.title}</div>
          <div className="pk-actions">
            <button className="kbtn pri" disabled={busy} onClick={() => onResolve(item)}>Resolve <kbd className="pk-kbd">↵</kbd></button>
            <button className="kbtn" onClick={() => onOpenDeal(item.dealId)}>Open deal</button>
          </div>
        </div>
      )}

      {digest.length > 0 && (
        <div className="pk-card">
          <div className="pk-sect">Recent on this deal</div>
          {digest.map((e) => (
            <div key={e.id} className="pk-ev">
              <span className={`pk-dot ${e.mode === "needs_you" ? "you" : ""}`} />
              <span className="pk-ev-t">{e.text}</span>
              {e.occurredAt && <span className="pk-ev-when tnum">{fmtDate(e.occurredAt).replace(/, \d{4}$/, "")}</span>}
            </div>
          ))}
        </div>
      )}

      {parties.length > 0 && (
        <div className="pk-card">
          <div className="pk-sect">People</div>
          <div className="pk-people">
            {parties.slice(0, 8).map((p) => (
              <span key={p.id} className="pk-person" title={p.role}>
                <i>{initials(p.name)}</i>{p.name ?? p.role.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
