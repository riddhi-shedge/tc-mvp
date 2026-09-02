import { useState } from "react";
import { api, FullState } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

/** Wave 2: the closing-week chain as a six-step stepper. Every advance is a
 *  TC confirmation (Terra suggests, never assumes); order is enforced by the
 *  backend, which also holds the federal TRID 3-business-day CD-review guard.
 *  The client mirrors the TRID math for display only — enforcement is server-side. */

const STEPS: { key: string; label: string; hint: string }[] = [
  { key: "docs_ordered", label: "Loan docs ordered", hint: "Lender drew docs to escrow" },
  { key: "cd_delivered", label: "CD delivered", hint: "Starts the federal 3-business-day review" },
  { key: "signed", label: "Signed", hint: "Buyer + seller signed with the notary" },
  { key: "funded", label: "Funded", hint: "Lender wired funds to title" },
  { key: "recorded", label: "Recorded", hint: "County recorded the deed — THIS is the close" },
  { key: "keys_released", label: "Keys released", hint: "Possession per the contract" },
];

// Display mirror of the backend's TRID clock (Saturdays count; Sundays and
// federal holidays don't). The server is the enforcer; this only informs.
const FEDERAL_HOLIDAYS = new Set([
  "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19",
  "2026-07-03", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26",
  "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31",
  "2027-06-18", "2027-07-05", "2027-09-06", "2027-10-11", "2027-11-11",
  "2027-11-25", "2027-12-24",
]);
function tridEarliestSigning(cdDelivered: string): string {
  const d = new Date(cdDelivered + "T12:00:00");
  let counted = 0;
  while (counted < 3) {
    d.setDate(d.getDate() + 1);
    const iso = d.toISOString().slice(0, 10);
    if (d.getDay() !== 0 && !FEDERAL_HOLIDAYS.has(iso)) counted++;
  }
  return d.toISOString().slice(0, 10);
}

export function ClosingStepper({
  id,
  state,
  onChanged,
}: {
  id: string;
  state: FullState;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [dateVal, setDateVal] = useState<string>(new Date().toISOString().slice(0, 10));
  const events = new Map((state.closing_events ?? []).map((e) => [e.step, e]));
  const nextIdx = STEPS.findIndex((s) => !events.has(s.key));
  const coe = state.deadlines.find((d) => /escrow/i.test(d.name));
  // Only surface once closing is real: a COE exists and it's near, or the
  // chain has started, or the deal is staged as closing.
  const stage = (state.transaction as { stage?: string }).stage ?? "";
  const coeDays = coe
    ? Math.round((Date.parse(coe.due_date) - Date.now()) / 86_400_000)
    : null;
  const started = events.size > 0;
  if (!started && stage !== "closing" && (coeDays === null || coeDays > 14)) return null;

  const cd = events.get("cd_delivered");
  const signedDone = events.has("signed");
  const earliestSigning = cd && !signedDone ? tridEarliestSigning(cd.occurred_on) : null;

  async function record(step: string) {
    setBusy(true);
    try {
      await api.post(`/transactions/${id}/closing/${step}`, { occurred_on: dateVal });
      toast(step === "recorded" ? "Recorded — the deal is closed 🎉" : "Step recorded");
      onChanged();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", { error: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2><Icon name="key" size={17} /> Closing week</h2>
      {earliestSigning && (
        <div className="cs-trid">
          CD review running — earliest signing <b>{fmtDate(earliestSigning).replace(/,\s*\d{4}$/, "")}</b>{" "}
          (3 federal business days: Saturdays count, Sundays &amp; federal holidays don't).
          {coe && Date.parse(earliestSigning) > Date.parse(coe.due_date) && (
            <b className="cs-collide"> That lands AFTER your close-of-escrow date — talk to escrow.</b>
          )}
        </div>
      )}
      <div className="cs-steps">
        {STEPS.map((s, i) => {
          const done = events.get(s.key);
          const isNext = i === nextIdx;
          return (
            <div key={s.key} className={`cs-step ${done ? "done" : isNext ? "next" : "locked"}`}>
              <span className="cs-dot">{done ? <Icon name="check" size={12} /> : i + 1}</span>
              <span className="cs-mid">
                <span className="cs-label">{s.label}</span>
                <span className="cs-hint">
                  {done ? `${fmtDate(done.occurred_on).replace(/,\s*\d{4}$/, "")}${done.note ? ` · ${done.note}` : ""}` : s.hint}
                </span>
              </span>
              {isNext && (
                <span className="cs-act">
                  <input
                    type="date"
                    value={dateVal}
                    onChange={(e) => setDateVal(e.target.value)}
                    aria-label="Date this step happened"
                  />
                  <button disabled={busy} onClick={() => void record(s.key)}>
                    Record
                  </button>
                </span>
              )}
            </div>
          );
        })}
      </div>
      <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.74rem" }}>
        Each step is your confirmation of something that happened outside Terra — recording is
        what closes the deal, not signing.
      </p>
    </div>
  );
}
