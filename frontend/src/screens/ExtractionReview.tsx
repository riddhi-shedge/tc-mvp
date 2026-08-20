import { useState } from "react";
import { ExtractedField, FIELD_DEADLINE_KEYWORD, FullState } from "../lib/api";
import { fmtDate } from "../lib/format";
import { Icon } from "../lib/icons";

// Friendlier row labels than the raw §5 field names; falls back to humanize().
const LABELS: Record<string, string> = {
  purchase_price: "Purchase price",
  initial_deposit_amount: "Initial deposit",
  increased_deposit_amount: "Increased deposit",
  down_payment: "Down payment",
  loan_amount: "Loan amount",
  financing_type: "Financing type",
  all_cash: "All-cash offer",
  loan_contingency_present: "Loan contingency",
  emd_due_days: "EMD due",
  verification_of_funds_days: "Verification of funds",
  inspection_contingency_days: "Inspection",
  appraisal_contingency_days: "Appraisal",
  insurance_contingency_days: "Insurance",
  disclosure_delivery_days: "Disclosure delivery",
  property_address: "Address",
  apn: "APN",
  items_included: "Items included",
  items_excluded: "Items excluded",
  possession_date: "Possession",
  home_warranty_paid_by: "Home warranty — paid by",
  home_warranty_issued_by: "Home warranty — issuer",
  other_terms: "Other terms",
};

const TERM_GROUPS: { key: string; label: string; names: string[] }[] = [
  {
    key: "financial",
    label: "$ Financial",
    names: [
      "purchase_price", "initial_deposit_amount", "increased_deposit_amount",
      "down_payment", "loan_amount", "financing_type", "all_cash", "loan_contingency_present",
    ],
  },
  {
    key: "contingency",
    label: "◷ Contingency periods",
    names: [
      "emd_due_days", "verification_of_funds_days", "inspection_contingency_days",
      "appraisal_contingency_days", "insurance_contingency_days", "disclosure_delivery_days",
    ],
  },
  {
    key: "property",
    label: "⌂ Property",
    names: ["property_address", "apn", "items_included", "items_excluded", "possession_date"],
  },
  {
    key: "allocation",
    label: "◇ Allocation & terms",
    names: ["home_warranty_paid_by", "home_warranty_issued_by", "other_terms"],
  },
];

// Shown in the snapshot / parties strip, so kept out of the detail rows.
const HANDLED_ELSEWHERE = new Set([
  "acceptance_date", "close_of_escrow",
  "buyer_names", "seller_names",
  "buyer_agent", "buyer_agent_email", "buyer_agent_phone",
  "listing_agent", "listing_agent_email", "listing_agent_phone",
  "escrow_holder", "title_company", "lender_contact",
]);

const CONF_THRESHOLD = 0.7;

function humanize(s: string): string {
  return LABELS[s] ?? s.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}
function shortName(name: string): string {
  return name
    .replace(/ \(verification of condition\)/i, "")
    .replace(/ due$/i, "")
    .trim();
}
function initials(name: string | null | undefined): string {
  const s = (name ?? "?").trim().split(/\s+/);
  return ((s[0]?.[0] ?? "") + (s[1]?.[0] ?? "")).toUpperCase() || "?";
}

/** The contract-extraction review as a dashboard: snapshot → parties → deadline
 *  spine → grouped term rows, with confidence and resolved dates encoded in form. */
export function ExtractionReview({
  state,
  busy,
  onConfirmAll,
  onVerify,
}: {
  state: FullState;
  busy: boolean;
  onConfirmAll: () => void;
  onVerify: (field: ExtractedField, value: string) => void;
}) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const fields = state.extracted_fields;
  if (fields.length === 0) {
    return (
      <div className="card">
        <div className="empty"><span className="empty-ic"><Icon name="search" size={26} /></span>No extracted fields yet.</div>
      </div>
    );
  }

  const eff = state.effective_fields ?? {};
  // Prefer the effective field (e.g. a counter offer's price over the PA's) so the
  // term rows show the superseding value, not a stale duplicate.
  const byName = (n: string) => {
    const matches = fields.filter((f) => f.name === n);
    if (matches.length <= 1) return matches[0];
    const v = eff[n]?.value;
    return matches.find((f) => f.value === v) ?? matches[matches.length - 1];
  };
  // Prefer the effective (superseded) value so a counter offer's price/dates win.
  const fv = (n: string) => eff[n]?.value ?? byName(n)?.value ?? null;
  const supersededFrom = (n: string) => eff[n]?.superseded_from ?? null;
  const total = fields.length;
  const unconfirmed = fields.filter((f) => !f.confirmed).length;
  const verifiedCount = total - unconfirmed;
  const needsReview = fields.filter((f) => f.confidence < CONF_THRESHOLD && !f.confirmed);

  // BUG-21: "Confirm all" would otherwise one-tap-confirm low-confidence,
  // deadline-driving fields without the TC ever opening the verify panel. Make
  // that a conscious choice — warn before confirming unreviewed low-confidence values.
  const confirmAllGuarded = () => {
    if (
      needsReview.length > 0 &&
      !window.confirm(
        `${needsReview.length} low-confidence field${needsReview.length === 1 ? " has" : "s have"} ` +
          "not been reviewed. These can drive the deal's deadlines. Confirm all without checking them?",
      )
    ) {
      return;
    }
    onConfirmAll();
  };

  const resolved = (name: string): string | null => {
    const kw = FIELD_DEADLINE_KEYWORD[name];
    if (!kw) return null;
    const d = state.deadlines.find((x) => x.name.toLowerCase().includes(kw));
    return d ? fmtDate(d.due_date) : null;
  };

  // confidence ring geometry (r = 15.5)
  const C = 2 * Math.PI * 15.5;
  const offset = total ? C * (1 - verifiedCount / total) : C;

  // snapshot
  const coeDl = state.deadlines.find((d) => d.name.toLowerCase().includes("escrow"));
  const price = fv("purchase_price");
  const coe = coeDl ? fmtDate(coeDl.due_date) : fv("close_of_escrow");
  const financing = fv("financing_type") ?? (fv("all_cash") === "true" ? "All cash" : "—");
  const allCash = fv("all_cash") === "true" || fv("loan_contingency_present") === "false";
  const acceptance = fv("acceptance_date");

  // parties
  const buyers = state.parties.filter((p) => p.role === "buyer");
  const sellers = state.parties.filter((p) => p.role === "seller");
  const bAgent = state.parties.find((p) => p.role === "buyer_agent");
  const lAgent = state.parties.find((p) => p.role === "listing_agent");

  // deadline spine: acceptance anchor + computed deadlines, chronological
  const spine = [...state.deadlines].sort((a, b) => a.due_date.localeCompare(b.due_date));

  // term rows: curated groups + an "other" catch-all so nothing is hidden
  const usedNames = new Set(TERM_GROUPS.flatMap((g) => g.names));
  const leftover = fields.filter(
    (f) => !usedNames.has(f.name) && !HANDLED_ELSEWHERE.has(f.name),
  );
  const groups = [
    ...TERM_GROUPS.map((g) => ({
      ...g,
      items: g.names.map(byName).filter((f): f is (typeof fields)[number] => !!f),
    })),
    ...(leftover.length ? [{ key: "other", label: "· Other details", items: leftover }] : []),
  ].filter((g) => g.items.length > 0);

  const row = (f: (typeof fields)[number]) => {
    const low = f.confidence < CONF_THRESHOLD;
    const date = resolved(f.name);
    return (
      <div key={f.id} className={`xr-row ${low ? "verify" : ""}`}>
        <span className="xr-t">
          <span className={`xr-dot ${low ? "low" : "ok"}`} />
          {humanize(f.name)}
          {low && <span className="xr-vpill">verify</span>}
        </span>
        <span className="xr-val">
          {f.value}
          {supersededFrom(f.name) && <span className="xr-super"> · was {supersededFrom(f.name)}</span>}
          {date && <span className="xr-datechip"><Icon name="calendar" size={12} /> {date}</span>}
        </span>
      </div>
    );
  };

  const agentBlock = (a: typeof bAgent, side: string) =>
    a ? (
      <div className="xr-agent">
        <div className="xr-av">{initials(a.name)}</div>
        <div style={{ minWidth: 0 }}>
          <div className="xr-nm">{a.name}</div>
          <div className="xr-co">
            {side} agent{a.company ? ` · ${a.company}` : ""}
          </div>
          {(a.email || a.phone) && (
            <div className="xr-chips">
              {a.email && <span className="xr-chip"><Icon name="mail" size={12} /> {a.email}</span>}
              {a.phone && <span className="xr-chip"><Icon name="phone" size={12} /> {a.phone}</span>}
            </div>
          )}
        </div>
      </div>
    ) : (
      <div className="xr-agent xr-muted" style={{ fontSize: "0.8rem" }}>
        No {side.toLowerCase()} agent captured
      </div>
    );

  return (
    <div className="xr">
      {/* header */}
      <div className="xr-top">
        <div>
          <div className="xr-eyebrow">Contract review · §5 extraction</div>
          <div className="xr-h">Extracted terms</div>
        </div>
        <div className="xr-topright">
          <div className="xr-conf">
            <svg className="xr-ring" viewBox="0 0 36 36" aria-hidden="true">
              <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--line)" strokeWidth="4" />
              <circle
                cx="18" cy="18" r="15.5" fill="none" stroke="var(--gold-500)" strokeWidth="4"
                strokeLinecap="round" strokeDasharray={C} strokeDashoffset={offset}
                transform="rotate(-90 18 18)"
              />
            </svg>
            <div className="xr-ringtxt">
              <b>{verifiedCount} of {total}</b> verified
              <br />
              <span className="xr-muted">
                {needsReview.length > 0 ? `${needsReview.length} low-confidence to check` : "all confirmed"}
              </span>
            </div>
          </div>
          {unconfirmed > 0 && (
            <button className="gold" disabled={busy} onClick={confirmAllGuarded}>
              {busy ? "…" : `✓ Confirm all (${unconfirmed})`}
            </button>
          )}
        </div>
      </div>

      {/* review & verify: always shown so it's easy to find — actionable amber
          panel when fields need a look, a green all-clear otherwise. */}
      <div className={`xr-verify ${needsReview.length ? "" : "done"}`}>
        <div className="xr-verify-head">
          {needsReview.length > 0 ? (
            <>
              <Icon name="warning" size={15} /> Review &amp; verify · {needsReview.length} to check
              <span className="xr-muted">Low-confidence values — check each, fix if wrong, then Verify.</span>
            </>
          ) : (
            <>
              <Icon name="checkCircle" size={15} /> All {total} fields verified
              <span className="xr-muted">Nothing needs your review right now — low-confidence fields would appear here to fix &amp; confirm.</span>
            </>
          )}
        </div>
        {needsReview.map((f) => (
          <div key={f.id} className="xr-verify-row">
            <div className="xr-verify-lbl">{humanize(f.name)}</div>
            <input
              className="xr-verify-input"
              value={edits[f.id] ?? f.value}
              disabled={busy}
              onChange={(e) => setEdits({ ...edits, [f.id]: e.target.value })}
            />
            <button className="gold sm" disabled={busy} onClick={() => onVerify(f, edits[f.id] ?? f.value)}>
              <Icon name="check" size={13} /> Verify
            </button>
          </div>
        ))}
      </div>

      {/* snapshot */}
      <div className="xr-snap">
        <div className="xr-stat hero">
          <div className="xr-k">Purchase price</div>
          <div className="xr-v tnum">{price ?? "—"}</div>
          {supersededFrom("purchase_price") && (
            <div className="xr-super">↑ Counter offer · was {supersededFrom("purchase_price")}</div>
          )}
          <div className="xr-m">{fv("initial_deposit_amount") ? `Deposit ${fv("initial_deposit_amount")}` : " "}</div>
        </div>
        <div className="xr-stat">
          <div className="xr-k">Close of escrow</div>
          <div className="xr-v tnum">{coe ?? "—"}</div>
          <div className="xr-m">{coeDl ? fv("close_of_escrow") ?? " " : "confirm to compute"}</div>
        </div>
        <div className="xr-stat">
          <div className="xr-k">Financing</div>
          <div className="xr-v">{financing}</div>
          {allCash ? <div className="xr-pill cash">● No loan contingency</div> : <div className="xr-m">&nbsp;</div>}
        </div>
        <div className="xr-stat">
          <div className="xr-k">Acceptance</div>
          <div className="xr-v tnum">{acceptance ? fmtDate(acceptance) : "—"}</div>
          <div className="xr-m">the clock starts here</div>
        </div>
      </div>

      {/* parties */}
      <div className="xr-sides">
        <div className="xr-side">
          <div className="xr-lbl">▲ Buy side</div>
          <div className="xr-prin">
            {buyers.length ? (
              buyers.map((b) => <div key={b.id} className="xr-who">{b.name}</div>)
            ) : (
              <div className="xr-who xr-muted">{fv("buyer_names") ?? "—"}</div>
            )}
            <div className="xr-role">Buyer{buyers.length > 1 ? "s" : ""}</div>
          </div>
          {agentBlock(bAgent, "Buyer's")}
        </div>
        <div className="xr-side">
          <div className="xr-lbl">▼ Sell side</div>
          <div className="xr-prin">
            {sellers.length ? (
              sellers.map((s) => <div key={s.id} className="xr-who">{s.name}</div>)
            ) : (
              <div className="xr-who xr-muted">{fv("seller_names") ?? "—"}</div>
            )}
            <div className="xr-role">Seller{sellers.length > 1 ? "s" : ""}</div>
          </div>
          {agentBlock(lAgent, "Listing")}
        </div>
      </div>

      {/* deadline spine */}
      {spine.length > 0 && (
        <div className="xr-spinecard">
          <div className="xr-spineh">
            <div className="xr-lbl">◷ Deadline spine</div>
            <span className="xr-muted" style={{ fontSize: "0.75rem" }}>
              computed · CA business-day rules
            </span>
          </div>
          <div className="xr-spine">
            {acceptance && (
              <div className="xr-stop anchor">
                <div className="xr-d tnum">{fmtDate(acceptance).replace(/, \d{4}$/, "")}</div>
                <div className="xr-nm2">Acceptance</div>
                <div className="xr-rel">contract signed</div>
              </div>
            )}
            {spine.map((d) => {
              const anchor = d.name.toLowerCase().includes("escrow");
              return (
                <div key={d.id} className={`xr-stop ${anchor ? "anchor" : ""}`}>
                  <div className="xr-d tnum">{fmtDate(d.due_date).replace(/, \d{4}$/, "")}</div>
                  <div className="xr-nm2">{shortName(d.name)}</div>
                  <div className="xr-rel">{fmtDate(d.due_date).replace(/^\w+ \d+, /, "")}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* term rows */}
      <div className="xr-terms">
        {groups.map((g) => (
          <div key={g.key} className="xr-grp">
            <div className="xr-lbl">{g.label}</div>
            {g.items.map(row)}
          </div>
        ))}
      </div>

      <div className="xr-legend">
        <span><span className="xr-dot ok" /> High confidence</span>
        <span><span className="xr-dot low" /> Low — please verify</span>
        <span><span className="xr-datechip"><Icon name="calendar" size={12} /></span> resolved deadline</span>
      </div>
    </div>
  );
}
