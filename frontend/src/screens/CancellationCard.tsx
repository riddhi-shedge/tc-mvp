import { useState } from "react";
import { api, FullState } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

/** Wave 4B: the cancellation unwind. Shown only on canceled deals — records
 *  what the signed CC form says: effective date + deposit DISPOSITION (a
 *  status word; amounts and money movement are never stored — Rule 2). */

const DISPOSITIONS: { value: string; label: string }[] = [
  { value: "released_to_buyer", label: "Deposit released to buyer" },
  { value: "released_to_seller", label: "Deposit released to seller" },
  { value: "disputed", label: "Disputed (held in escrow)" },
  { value: "n_a", label: "No deposit involved" },
];

export function CancellationCard({
  id,
  state,
  onChanged,
}: {
  id: string;
  state: FullState;
  onChanged: () => void;
}) {
  const txn = state.transaction as {
    status: string;
    canceled_on?: string | null;
    deposit_disposition?: string | null;
  };
  const [busy, setBusy] = useState(false);
  const [disp, setDisp] = useState("released_to_buyer");
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  if (txn.status !== "canceled") return null;

  const recorded = txn.deposit_disposition
    ? DISPOSITIONS.find((d) => d.value === txn.deposit_disposition)?.label ?? txn.deposit_disposition
    : null;

  return (
    <div className="card cx-card">
      <h2><Icon name="x" size={17} /> Cancellation record</h2>
      {recorded ? (
        <p style={{ margin: 0 }}>
          Effective <b>{txn.canceled_on ? fmtDate(txn.canceled_on) : "—"}</b> · {recorded}.
          <span className="muted"> Upload the signed Cancellation of Contract to the Documents tab.</span>
        </p>
      ) : (
        <>
          <p className="muted" style={{ marginTop: 0 }}>
            Record the effective date and deposit disposition from the signed Cancellation of Contract.
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
            <select value={disp} onChange={(e) => setDisp(e.target.value)} style={{ width: "auto" }}>
              {DISPOSITIONS.map((d) => (
                <option key={d.value} value={d.value}>{d.label}</option>
              ))}
            </select>
            <input
              type="date"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              aria-label="Cancellation effective date"
              style={{ width: "auto" }}
            />
            <button
              disabled={busy}
              onClick={() =>
                void (async () => {
                  setBusy(true);
                  try {
                    await api.post(`/transactions/${id}/cancellation`, {
                      deposit_disposition: disp,
                      canceled_on: when,
                    });
                    toast("Cancellation recorded");
                    onChanged();
                  } catch (err) {
                    toast(err instanceof Error ? err.message : "Failed", { error: true });
                  } finally {
                    setBusy(false);
                  }
                })()
              }
            >
              Record unwind
            </button>
          </div>
        </>
      )}
    </div>
  );
}
