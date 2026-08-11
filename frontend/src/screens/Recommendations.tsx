import { useCallback, useEffect, useMemo, useState } from "react";
import { api, CalendarDeadline, DealSummary } from "../lib/api";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

/* The Context Rail — "Terra recommendations". Source-backed, review-first: every
 * card says what Terra found, why it matters, and where the evidence is, then
 * offers Open / Mark reviewed / Dismiss. Cards are DERIVED from live board +
 * calendar data (risk flags, imminent closings, deadlines due today) — no
 * fabricated figures, and nothing sends or changes without you. */

const DAY = 86_400_000;
function daysTo(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso + "T00:00:00").getTime();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((t - today.getTime()) / DAY);
}
const addr = (a: string | null) => (a ?? "(no address)").split(",")[0];

type Rec = {
  id: string;
  dealId: string;
  deal: string;
  title: string;
  why: string;
  detected: string;
  affects: string;
  source: string;
};

function derive(deals: DealSummary[], cal: CalendarDeadline[]): Rec[] {
  const out: Rec[] = [];
  const active = deals.filter((d) => d.stage !== "closed");

  for (const d of active) {
    if (d.risk_count > 0) {
      out.push({
        id: `risk-${d.id}`,
        dealId: d.id,
        deal: addr(d.property_address),
        title: `${d.risk_count} unresolved risk flag${d.risk_count > 1 ? "s" : ""} to review`,
        why: "Terra's compliance checks found issues on this deal that haven't been resolved. Review them before they affect the closing.",
        detected: "Risk & compliance checks",
        affects: addr(d.property_address),
        source: "Deal · Overview → risk flags",
      });
    }
    const n = daysTo(d.coe_date);
    if (n != null && n >= 0 && n <= 3 && d.open_tasks > 0) {
      out.push({
        id: `close-${d.id}`,
        dealId: d.id,
        deal: addr(d.property_address),
        title: `Closing in ${n === 0 ? "today" : `${n} day${n > 1 ? "s" : ""}`} with ${d.open_tasks} open task${d.open_tasks > 1 ? "s" : ""}`,
        why: "Close of escrow is imminent but work is still open on this deal. Clear the remaining tasks so the closing stays on schedule.",
        detected: "Close-of-escrow countdown",
        affects: addr(d.property_address),
        source: "Deal · Tasks",
      });
    }
  }

  for (const c of cal) {
    if (daysTo(c.due_date) === 0) {
      out.push({
        id: `due-${c.transaction_id}-${c.name}`,
        dealId: c.transaction_id,
        deal: addr(c.property_address),
        title: `${c.name.replace(/ (ends|due|delivery).*$/i, "")} is due today`,
        why: "A contractual deadline falls today. Confirm it's handled or take the next step now.",
        detected: "Contract timeline",
        affects: addr(c.property_address),
        source: "Deal · Timeline",
      });
    }
  }

  return out.slice(0, 8);
}

type CardState = "review" | "reviewed" | "dismissed";

export function Recommendations({ onOpenDeal, onClose }: { onOpenDeal: (id: string) => void; onClose?: () => void }) {
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [cal, setCal] = useState<CalendarDeadline[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [states, setStates] = useState<Record<string, CardState>>({});

  const load = useCallback(async () => {
    try {
      const [b, c] = await Promise.all([
        api.get<DealSummary[]>("/transactions/board"),
        api.get<CalendarDeadline[]>("/transactions/calendar"),
      ]);
      setDeals(b);
      setCal(c);
    } catch {
      /* rail is best-effort; the main page surfaces load errors */
    } finally {
      setLoaded(true);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const recs = useMemo(() => derive(deals, cal), [deals, cal]);
  const visible = recs.filter((r) => states[r.id] !== "dismissed");

  function set(id: string, s: CardState) {
    setStates((prev) => ({ ...prev, [id]: s }));
  }

  return (
    <div className="rail-inner">
      <div className="rail-h">
        <span className="rail-h-ic"><Icon name="sparkle" size={16} /></span>
        <h3>Terra recommendations</h3>
        {onClose && <button className="rail-x" aria-label="Close" onClick={onClose}>×</button>}
      </div>
      <div className="rail-note">Source-backed · nothing runs without your approval.</div>

      {!loaded && <div className="rail-empty">Reading your deals…</div>}
      {loaded && visible.length === 0 && (
        <div className="rail-empty">
          <span className="rail-empty-ic"><Icon name="checkCircle" size={22} /></span>
          Nothing needs review right now — you're on top of it.
        </div>
      )}

      {visible.map((r) => {
        const st = states[r.id] ?? "review";
        return (
          <div key={r.id} className={`rec ${st === "reviewed" ? "reviewed" : ""}`}>
            <div className="rec-h">
              <span className="rec-lab">◆ Terra · {r.deal}</span>
              <span className="rec-status">{st === "reviewed" ? "reviewed" : "needs review"}</span>
            </div>
            <div className="rec-b">
              <h4>{r.title}</h4>
              <p className="rec-why">{r.why}</p>
              <div className="rec-kv">
                <div className="rec-kv-r"><span className="k">Detected</span><span className="v">{r.detected}</span></div>
                <div className="rec-kv-r"><span className="k">Affects</span><span className="v">{r.affects}</span></div>
              </div>
              <button className="rec-src" onClick={() => onOpenDeal(r.dealId)}>
                <Icon name="external" size={13} /> {r.source}
              </button>
              {st === "review" ? (
                <div className="rec-acts">
                  <button className="rec-ap" onClick={() => onOpenDeal(r.dealId)}>Review</button>
                  <button className="rec-di" onClick={() => { set(r.id, "reviewed"); toast("Marked reviewed"); }}>Mark done</button>
                  <button className="rec-di" onClick={() => set(r.id, "dismissed")}>Dismiss</button>
                </div>
              ) : (
                <div className="rec-done">
                  <Icon name="check" size={13} /> Reviewed
                  <button className="rec-undo" onClick={() => set(r.id, "review")}>Undo</button>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
