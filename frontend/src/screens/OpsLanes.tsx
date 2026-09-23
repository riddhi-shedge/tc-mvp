import { useState } from "react";
import { api, FullState } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon, IconName } from "../lib/icons";

/** Wave 3A: the four ops lanes a TC babysits between contingencies and close —
 *  HOA package, home warranty, NHD report, utilities transfer. One generic
 *  ordered→done chain per lane; Chase drafts to the right party (Rule 3:
 *  drafts only, approval happens in Communication). */

type LaneDef = {
  key: string;
  name: string;
  icon: IconName;
  orderedLabel: string;
  doneLabel: string;
  hint: string;
  askRole: string;
  purpose: string;
};
const LANES: LaneDef[] = [
  { key: "hoa", name: "HOA document package", icon: "home",
    orderedLabel: "Ordered", doneLabel: "Delivered", askRole: "escrow", purpose: "escrow_checkin",
    hint: "CC&Rs, financials, and minutes for condo/PUD sales" },
  { key: "warranty", name: "Home warranty", icon: "shield",
    orderedLabel: "Ordered", doneLabel: "Confirmed", askRole: "listing_agent", purpose: "general",
    hint: "Order per the contract and confirm the invoice" },
  { key: "nhd", name: "NHD report", icon: "map" as IconName,
    orderedLabel: "Ordered", doneLabel: "Delivered", askRole: "listing_agent", purpose: "disclosure_reminder",
    hint: "Natural hazard disclosure report" },
  { key: "utilities", name: "Utilities transfer", icon: "spark",
    orderedLabel: "Buyer reminded", doneLabel: "Switched", askRole: "buyer", purpose: "general",
    hint: "Power/water/gas in the buyer's name by possession day" },
];

export function OpsLanes({
  id,
  state,
  onChanged,
}: {
  id: string;
  state: FullState;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const items = new Map((state.ops_items ?? []).map((o) => [o.lane, o]));
  const warrantyWaived = /waived/i.test(state.effective_fields?.home_warranty?.value ?? "");

  async function advance(lane: string, status: "ordered" | "done") {
    setBusy(lane);
    try {
      await api.post(`/transactions/${id}/ops/${lane}`, { status });
      toast(status === "ordered" ? "Lane started" : "Lane complete");
      onChanged();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", { error: true });
    } finally {
      setBusy(null);
    }
  }
  async function chase(lane: LaneDef) {
    const party = state.parties.find((p) => p.role === lane.askRole && p.email);
    if (!party) {
      toast(`No ${lane.askRole.replace("_", " ")} with an email on this deal yet`, { error: true });
      return;
    }
    setBusy(lane.key);
    try {
      await api.post(`/transactions/${id}/messages/draft`, {
        party_id: party.id,
        purpose: lane.purpose,
      });
      toast(`Draft created for ${party.name ?? "recipient"}. Review it in Communication.`);
      onChanged();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Draft failed", { error: true });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <h2><Icon name="clipboard" size={17} /> Ops lanes</h2>
      {LANES.map((lane) => {
        const item = items.get(lane.key);
        const waived = lane.key === "warranty" && warrantyWaived && !item;
        return (
          <div key={lane.key} className={`ops-row ${waived ? "waived" : ""}`}>
            <span className="ops-ic"><Icon name={lane.icon} size={15} /></span>
            <span className="ops-mid">
              <span className="ops-name">{lane.name}</span>
              <span className="ops-hint">
                {waived ? "Waived per the contract" : lane.hint}
              </span>
            </span>
            {item?.status === "done" ? (
              <span className="dl-st ok">
                {lane.doneLabel} {fmtDate(item.completed_on ?? "").replace(/,\s*\d{4}$/, "")}
              </span>
            ) : item ? (
              <>
                <span className="dl-st warn">
                  {lane.orderedLabel} {fmtDate(item.ordered_on ?? "").replace(/,\s*\d{4}$/, "")}
                </span>
                <button className="dl-mini pri" disabled={busy === lane.key}
                  onClick={() => void advance(lane.key, "done")}>
                  {lane.doneLabel}
                </button>
                <button className="dl-mini" disabled={busy === lane.key}
                  onClick={() => void chase(lane)}>
                  Chase
                </button>
              </>
            ) : (
              !waived && (
                <button className="dl-mini" disabled={busy === lane.key}
                  onClick={() => void advance(lane.key, "ordered")}>
                  {lane.orderedLabel}
                </button>
              )
            )}
          </div>
        );
      })}
      <div style={{ display: "flex", alignItems: "center", gap: "0.7rem", marginTop: "0.7rem" }}>
        <button
          className="dl-act pri"
          disabled={busy === "__weekly"}
          title="Draft a status update for each party"
          onClick={() =>
            void (async () => {
              setBusy("__weekly");
              try {
                const r = await api.post<{ drafted: unknown[]; skipped: { name: string | null; reason: string }[] }>(
                  `/transactions/${id}/status-updates`,
                );
                toast(
                  `${r.drafted.length} update${r.drafted.length === 1 ? "" : "s"} drafted` +
                    (r.skipped.length ? `, ${r.skipped.length} skipped (${r.skipped.map((s) => s.reason)[0]})` : "") +
                    ". Review in Communication.",
                );
                onChanged();
              } catch (err) {
                toast(err instanceof Error ? err.message : "Failed", { error: true });
              } finally {
                setBusy(null);
              }
            })()
          }
        >
          {busy === "__weekly" ? "Drafting…" : "Draft weekly updates"}
        </button>
        <span className="muted" style={{ fontSize: "0.74rem" }}>
          Drafts require your approval before sending.
        </span>
      </div>
    </div>
  );
}
