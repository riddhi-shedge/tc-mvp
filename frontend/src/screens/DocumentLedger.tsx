import { useMemo, useState } from "react";
import { api, DealDocument, DealParty, ExtractedField, FullState } from "../lib/api";
import { fmtDate } from "../lib/format";
import { toast } from "../lib/ui";
import { Icon, IconName } from "../lib/icons";

/** The Documents workspace: a master-detail "ledger". Left — every document
 *  grouped by role, dense rows, with expected-but-missing documents as dashed
 *  ghost rows in their group (the checklist IS the list). Right — the selected
 *  document as an object page: role, all of its extracted fields grouped into
 *  facets with inline confirm/verify, supersession trail, the checks it drove,
 *  and its activity. Replaces the doc grid + MissingPanel + DocumentChecks +
 *  ExtractionReview stack. */

const DOC_LABEL: Record<string, string> = {
  purchase_agreement: "Purchase agreement",
  seller_counter_offer: "Seller counter offer",
  buyer_counter_offer: "Buyer counter offer",
  counter_offer: "Counter offer",
  contingency_removal: "Contingency removal",
  cancellation: "Cancellation of contract (CC)",
  request_for_repairs: "Request for repairs (RR)",
  repair_response: "Repair response",
  preapproval: "Preapproval / underwriter",
  preliminary_report: "Preliminary (title) report",
  property_inspection: "Property inspection",
  termite_inspection: "Termite inspection",
  proof_of_funds: "Proof of funds",
  disclosure: "Disclosure",
  inspection_report: "Inspection report",
  other: "Other document",
  unknown: "Unknown",
};
const DOC_ROLE: Record<string, string> = {
  purchase_agreement: "Sets the deal's terms, parties, and deadlines.",
  seller_counter_offer: "Supersedes the agreement's price and terms.",
  buyer_counter_offer: "Supersedes the agreement's price and terms.",
  counter_offer: "Supersedes the agreement's price and terms.",
  contingency_removal: "Removes contingencies from the timeline.",
  cancellation: "Ends the deal. Record the effective date and deposit disposition on the Overview tab.",
  request_for_repairs: "The buyer's repair requests. Track each item and resolve as work completes.",
  repair_response: "The seller's response to the repair request.",
  preapproval: "Adds the loan officer; Terra checks borrower, amount and expiry against the contract.",
  preliminary_report: "Title report. Checked against the contract's APN and owner of record.",
  property_inspection: "Adds the inspector; checks address and recency.",
  termite_inspection: "Adds the pest company; checks address and recency.",
  proof_of_funds: "Evidence the buyer's funds are real.",
  disclosure: "Part of the seller's disclosure packet.",
};
const DOC_ICON: Record<string, IconName> = {
  purchase_agreement: "contract",
  seller_counter_offer: "contract",
  buyer_counter_offer: "contract",
  counter_offer: "contract",
  contingency_removal: "check",
  cancellation: "x",
  request_for_repairs: "clipboard",
  repair_response: "clipboard",
  preapproval: "bank",
  proof_of_funds: "money",
  preliminary_report: "pin",
  disclosure: "clipboard",
  property_inspection: "search",
  termite_inspection: "search",
  inspection_report: "search",
  other: "doc",
  unknown: "doc",
};
const GROUP_OF: Record<string, string> = {
  purchase_agreement: "Contract",
  seller_counter_offer: "Contract",
  buyer_counter_offer: "Contract",
  counter_offer: "Contract",
  contingency_removal: "Contract",
  cancellation: "Contract",
  request_for_repairs: "Contract",
  repair_response: "Contract",
  preapproval: "Financing",
  proof_of_funds: "Financing",
  preliminary_report: "Reports & disclosures",
  disclosure: "Reports & disclosures",
  property_inspection: "Reports & disclosures",
  termite_inspection: "Reports & disclosures",
  inspection_report: "Reports & disclosures",
};
const GROUPS = ["Contract", "Financing", "Reports & disclosures", "Other"];

// §5 field name → facet (unknown names fall into "Other terms").
const FACETS = ["Money", "Dates", "Contingencies", "Parties & contacts", "Property & other terms"];
const FACET_OF: Record<string, string> = {
  purchase_price: "Money", initial_deposit_amount: "Money", loan_amount: "Money",
  down_payment: "Money", financing_type: "Money", seller_credit: "Money",
  acceptance_date: "Dates", close_of_escrow: "Dates", possession_date: "Dates",
  offer_date: "Dates",
  emd_due_days: "Contingencies", inspection_contingency_days: "Contingencies",
  loan_contingency_days: "Contingencies", appraisal_contingency_days: "Contingencies",
  insurance_contingency_days: "Contingencies", disclosure_delivery_days: "Contingencies",
  verification_of_funds_days: "Contingencies",
  buyer_names: "Parties & contacts", seller_names: "Parties & contacts",
  buyer_agent: "Parties & contacts", buyer_agent_phone: "Parties & contacts",
  buyer_agent_email: "Parties & contacts", listing_agent: "Parties & contacts",
  listing_agent_phone: "Parties & contacts", listing_agent_email: "Parties & contacts",
  escrow_company: "Parties & contacts", title_company: "Parties & contacts",
  lender_name: "Parties & contacts", lender_contact_email: "Parties & contacts",
  lender_contact_phone: "Parties & contacts", loan_officer: "Parties & contacts",
  property_address: "Property & other terms", apn: "Property & other terms",
  items_included: "Property & other terms", items_excluded: "Property & other terms",
  other_terms: "Property & other terms", home_warranty: "Property & other terms",
};

// Flag case_keys ↔ the document type whose checks raised them (from DocumentChecks).
function flagMatchesDoc(caseKey: string, docType: string): boolean {
  const c = caseKey.toLowerCase();
  if (docType.includes("counter")) return c.includes("counter");
  if (docType === "preapproval") return c.includes("preapproval") || c.includes("borrower");
  if (docType === "preliminary_report") return c.includes("prelim") || c.includes("vest") || c.includes("apn");
  if (docType.includes("inspection")) return c.includes("inspection_report") || c.includes("inspector");
  if (docType === "purchase_agreement") return c.includes("inconsistency") || c === "counter_pending";
  return false;
}

// Searchable text for content-aware matching: type + label + universal-read kind.
function docText(d: DealDocument): string {
  return `${d.doc_type ?? ""} ${d.label ?? ""} ${d.facts?.doc_kind ?? ""} ${d.facts?.summary ?? ""}`;
}

// Expected-for-a-CA-deal ghost rows. The disclosure packet is tracked FORM BY
// FORM (a real TC never checks off "disclosures" as one lump): a received doc
// satisfies a form when its type/label/universal-read kind matches.
type Ghost = {
  key: string; group: string; name: string; icon: IconName; role: string;
  why: string; askRole: string; purpose: string;
  has: (docs: DealDocument[]) => boolean;
};
const byType = (...types: string[]) => (docs: DealDocument[]) =>
  docs.some((d) => types.includes(d.doc_type ?? ""));
const byMatch = (re: RegExp) => (docs: DealDocument[]) => docs.some((d) => re.test(docText(d)));
const DISCLOSURE_FORMS: { key: string; name: string; re: RegExp }[] = [
  { key: "tds", name: "TDS (Transfer Disclosure Statement)", re: /transfer disclosure|\bTDS\b/i },
  { key: "spq", name: "SPQ (Seller Property Questionnaire)", re: /property questionnaire|\bSPQ\b/i },
  { key: "nhd", name: "NHD (Natural Hazard Disclosure)", re: /natural hazard|\bNHD\b/i },
  { key: "fld", name: "FLD (Lead-Based Paint Disclosure)", re: /lead[- ]based paint|\bFLD\b/i },
  { key: "avid", name: "AVID (Agent Visual Inspection Disclosure)", re: /\bAVID\b|visual inspection/i },
  { key: "whsd", name: "WHSD (Water Heater & Smoke Detector)", re: /water heater|smoke detector|\bWHSD\b/i },
];
const EXPECTED: Ghost[] = [
  { key: "gh-pa", group: "Contract", name: "Purchase agreement", icon: "contract",
    role: "The deal cannot compute without it.", why: "No purchase agreement is on file.",
    askRole: "buyer_agent", purpose: "general", has: byType("purchase_agreement") },
  { key: "gh-fin", group: "Financing", name: "Preapproval or proof of funds", icon: "bank",
    role: "Preapproval letter or proof of funds for the buyer's financing.",
    why: "The loan contingency needs financing evidence behind it.",
    askRole: "buyer_agent", purpose: "lender_status", has: byType("preapproval", "proof_of_funds") },
  ...DISCLOSURE_FORMS.map((f) => ({
    key: `gh-${f.key}`, group: "Reports & disclosures", name: f.name,
    icon: "clipboard" as IconName,
    role: "Part of the seller's disclosure packet. Delivered to the buyer and signed by both parties.",
    why: "Statutory delivery deadline applies; the buyer's review clock starts on delivery.",
    askRole: "listing_agent", purpose: "disclosure_reminder", has: byMatch(f.re),
  })),
  { key: "gh-prelim", group: "Reports & disclosures", name: "Preliminary (title) report", icon: "pin",
    role: "Title report from the title company.",
    why: "Needed before contingencies clear.", askRole: "escrow", purpose: "escrow_checkin",
    has: byType("preliminary_report") },
  { key: "gh-insp", group: "Reports & disclosures", name: "Property & termite inspections", icon: "search",
    role: "Inspection reports attach here once the inspections happen.",
    why: "The inspection contingency needs reports behind it.",
    askRole: "buyer_agent", purpose: "inspection_schedule",
    has: byType("property_inspection", "termite_inspection", "inspection_report") },
];

// Statutory buyer-rescission advisory (Civ. Code §1102.3): TDS/NHD delivery
// opens a 3-day (personal) / 5-day (mail) rescission window that does NOT roll
// for weekends. Display-only, computed from the RECEIVED date as a proxy — the
// real clock runs from delivery to the buyer.
const RESCISSION_RE = /transfer disclosure|\bTDS\b|natural hazard|\bNHD\b/i;
function rescissionWindow(d: DealDocument): { p3: string; p5: string } | null {
  if (!d.created_at || !RESCISSION_RE.test(docText(d))) return null;
  const t = new Date(d.created_at).getTime();
  const fmt = (days: number) =>
    fmtDate(new Date(t + days * 86_400_000).toISOString()).replace(/,\s*\d{4}$/, "");
  return { p3: fmt(3), p5: fmt(5) };
}

function humanize(s: string): string {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}
function docName(d: DealDocument): string {
  return d.doc_type === "other" && d.label ? d.label : DOC_LABEL[d.doc_type ?? "unknown"] ?? humanize(d.doc_type ?? "unknown");
}
const shortDate = (iso?: string | null) => (iso ? fmtDate(iso).replace(/,\s*\d{4}$/, "") : "");

type Row =
  | { kind: "doc"; doc: DealDocument; fields: ExtractedField[]; group: string }
  | { kind: "ghost"; ghost: Ghost };

export function DocumentLedger({
  id,
  state,
  onChanged,
  onOpenDoc,
}: {
  id: string;
  state: FullState;
  onChanged: () => void;
  onOpenDoc: (docId: string) => void;
}) {
  const [filter, setFilter] = useState<"all" | "needs" | "done" | "miss">("all");
  const [sel, setSel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null); // field id being verified
  const [editVal, setEditVal] = useState("");
  // Cross-document synthesis (advisory): narrative + observations on demand.
  type Story = {
    narrative: string;
    observations: { text: string; severity: string; sources: string[] }[];
  };
  const [story, setStory] = useState<Story | null>(null);
  const [storyBusy, setStoryBusy] = useState(false);
  async function weaveStory() {
    setStoryBusy(true);
    try {
      setStory(await api.post<Story>(`/transactions/${id}/story`, {}));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Synthesis failed", { error: true });
    } finally {
      setStoryBusy(false);
    }
  }

  const model = useMemo(() => {
    const docOfPayload = new Map((state.payloads ?? []).map((p) => [p.id, p.document_id]));
    const fieldsByDoc = new Map<string, ExtractedField[]>();
    for (const f of state.extracted_fields) {
      const did = f.payload_id ? docOfPayload.get(f.payload_id) : undefined;
      if (!did) continue;
      const arr = fieldsByDoc.get(did) ?? [];
      arr.push(f);
      fieldsByDoc.set(did, arr);
    }
    const rows: Row[] = state.documents.map((d) => ({
      kind: "doc" as const,
      doc: d,
      fields: fieldsByDoc.get(d.id) ?? [],
      group: GROUP_OF[d.doc_type ?? ""] ?? "Other",
    }));
    for (const g of EXPECTED) if (!g.has(state.documents)) rows.push({ kind: "ghost", ghost: g });
    return { rows };
  }, [state]);

  const rowKey = (r: Row) => (r.kind === "doc" ? r.doc.id : r.ghost.key);
  const rowState = (r: Row) =>
    r.kind === "ghost" ? "miss" : r.fields.some((f) => !f.confirmed) ? "needs" : "done";
  const needsCount = (r: Row) => (r.kind === "doc" ? r.fields.filter((f) => !f.confirmed).length : 0);
  const visible = model.rows.filter((r) => filter === "all" || rowState(r) === filter);
  const selRow = model.rows.find((r) => rowKey(r) === sel) ?? visible[0] ?? model.rows[0];

  const counts = { all: model.rows.length, needs: 0, done: 0, miss: 0 };
  for (const r of model.rows) counts[rowState(r)]++;

  const eff = state.effective_fields ?? {};

  async function run(fn: () => Promise<unknown>, okMsg: string) {
    setBusy(true);
    try {
      await fn();
      toast(okMsg);
      onChanged();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed", { error: true });
    } finally {
      setBusy(false);
    }
  }
  const confirmFields = (ids: string[], msg: string) =>
    run(() => api.post(`/transactions/${id}/fields/confirm`, { field_ids: ids }), msg);
  const saveVerify = (f: ExtractedField) => {
    const v = editVal.trim();
    setEditing(null);
    if (v && v !== f.value) {
      void run(
        () => api.post(`/transactions/${id}/fields`, { name: f.name, value: v }),
        `${humanize(f.name)} corrected`,
      );
    } else {
      void confirmFields([f.id], `${humanize(f.name)} verified`);
    }
  };
  const draftRequest = (g: Ghost) => {
    const party = state.parties.find((p) => p.role === g.askRole && p.email);
    if (!party) {
      const anyParty = state.parties.find((p) => p.role === g.askRole);
      toast(
        anyParty
          ? `${anyParty.name ?? "This party"} has no email address. Add one on the Overview tab.`
          : `No ${g.askRole.replace("_", " ")} on this deal yet`,
        { error: true },
      );
      return;
    }
    void run(
      () =>
        api.post(`/transactions/${id}/messages/draft`, { party_id: party.id, purpose: g.purpose }),
      `Draft created for ${party.name ?? "recipient"}. Review it in Communication.`,
    );
  };

  // ---------- render helpers ----------
  function listRow(r: Row) {
    const st = rowState(r);
    const key = rowKey(r);
    const selected = selRow && rowKey(selRow) === key;
    if (r.kind === "ghost") {
      return (
        <button
          key={key}
          className={`dl-row ghost ${selected ? "sel" : ""}`}
          onClick={() => setSel(key)}
        >
          <span className="dl-ic ghost"><Icon name="plus" size={14} /></span>
          <span className="dl-mid">
            <span className="dl-nm">{r.ghost.name}</span>
            <span className="dl-mt">not received</span>
          </span>
          <span className="dl-st miss">missing</span>
        </button>
      );
    }
    const d = r.doc;
    return (
      <button key={key} className={`dl-row ${selected ? "sel" : ""}`} onClick={() => setSel(key)}>
        <span className="dl-ic"><Icon name={DOC_ICON[d.doc_type ?? "unknown"] ?? "doc"} size={14} /></span>
        <span className="dl-mid">
          <span className="dl-nm">{docName(d)}</span>
          <span className="dl-mt">received {shortDate(d.created_at)}</span>
        </span>
        {st === "needs" ? (
          <span className="dl-st warn">{needsCount(r)} to confirm</span>
        ) : (
          <span className={`dl-st ${r.fields.length ? "ok" : "info"}`}>
            {r.fields.length ? "verified" : "on file"}
          </span>
        )}
      </button>
    );
  }

  function fieldRow(f: ExtractedField) {
    const e = eff[f.name];
    const superseded = e && e.value !== f.value; // a later confirmed value governs
    const low = f.confidence < 0.7;
    return (
      <div className="dl-fr" key={f.id}>
        <span className="dl-fn">{humanize(f.name)}</span>
        <span className="dl-fv" title={f.evidence ? `Read from: "${f.evidence}"` : f.value}>
          {superseded ? (
            <>
              <s>{f.value}</s> → {e.value}
              <span className="dl-via">superseded</span>
            </>
          ) : (
            f.value
          )}
        </span>
        {f.evidence && (
          <span className="dl-quote" title={`Read from: "${f.evidence}"`}>❝</span>
        )}
        <span className={`dl-conf ${low ? "low" : ""}`}>{f.confidence.toFixed(2)}</span>
        {f.confirmed ? (
          <span className="dl-okmark"><Icon name="check" size={13} /></span>
        ) : editing === f.id ? (
          <span className="dl-editrow">
            <input
              autoFocus
              value={editVal}
              onChange={(ev) => setEditVal(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter") saveVerify(f);
                if (ev.key === "Escape") setEditing(null);
              }}
            />
            <button className="dl-mini pri" disabled={busy} onClick={() => saveVerify(f)}>Save</button>
          </span>
        ) : (
          <button
            className={`dl-mini ${low ? "" : "pri"}`}
            disabled={busy}
            onClick={() => {
              if (low) {
                setEditing(f.id);
                setEditVal(f.value);
              } else {
                void confirmFields([f.id], `${humanize(f.name)} confirmed`);
              }
            }}
            title={low ? "Low confidence. Verify against the PDF." : undefined}
          >
            {low ? "Verify" : "Confirm"}
          </button>
        )}
      </div>
    );
  }

  function detail() {
    if (!selRow) return <div className="dl-empty">No documents yet.</div>;
    if (selRow.kind === "ghost") {
      const g = selRow.ghost;
      const party: DealParty | undefined = state.parties.find((p) => p.role === g.askRole);
      return (
        <div className="dl-missing">
          <div className="dl-eyebrow"><Icon name="plus" size={13} /> Missing document</div>
          <div className="dl-title">{g.name} · not received</div>
          <p>{g.role}</p>
          <p className="why">{g.why}</p>
          <p>
            <strong>Who has it:</strong>{" "}
            {party ? `${party.name ?? "(unnamed)"} (${g.askRole.replace("_", " ")})` : `no ${g.askRole.replace("_", " ")} on the deal yet`}
          </p>
          <button className="dl-act pri" disabled={busy} onClick={() => draftRequest(g)}>
            Draft the request
          </button>
          <p className="dl-note">The message is saved as a draft for your approval in Communication.</p>
        </div>
      );
    }
    const d = selRow.doc;
    const fields = selRow.fields;
    const byFacet = new Map<string, ExtractedField[]>();
    for (const f of fields) {
      const facet = FACET_OF[f.name] ?? "Property & other terms";
      byFacet.set(facet, [...(byFacet.get(facet) ?? []), f]);
    }
    const flags = state.risk_flags.filter(
      (r) => !r.resolved && flagMatchesDoc(r.case_key ?? "", d.doc_type ?? ""),
    );
    const activity = state.audit_log
      .filter((a) => {
        const det = a.details as { document_external_ref?: string; superseded_by?: string };
        return (
          (a.action === "payload.written" && det.document_external_ref === d.external_ref) ||
          (a.action === "document.superseded" && (a.entity_id === d.id || det.superseded_by === d.id)) ||
          (a.action === "document.labeled" && a.entity_id === d.id)
        );
      })
      .slice(-6);
    const open = fields.filter((f) => !f.confirmed && f.confidence >= 0.7);
    const price = eff.purchase_price?.value;
    const acc = eff.acceptance_date?.value;
    const coe = state.deadlines.find((x) => /escrow/i.test(x.name));
    return (
      <>
        <div className="dl-objhead">
          <div className="dl-eyebrow">
            <Icon name={DOC_ICON[d.doc_type ?? "unknown"] ?? "doc"} size={13} />
            {rowState(selRow) === "needs" ? "Needs you" : "On file"} · {selRow.group}
          </div>
          <div className="dl-titlerow">
            <div>
              <div className="dl-title">{docName(d)}</div>
              <div className="dl-meta">
                Received {d.created_at ? fmtDate(d.created_at) : "—"} · {d.status}
                {d.doc_type === "other" && d.label ? " · labeled by Terra" : ""}
              </div>
            </div>
            <button className="dl-act" onClick={() => onOpenDoc(d.id)}>
              <Icon name="external" size={13} /> Open PDF
            </button>
          </div>
          {DOC_ROLE[d.doc_type ?? ""] && <div className="dl-role">{DOC_ROLE[d.doc_type ?? ""]}</div>}
          {(() => {
            const w = rescissionWindow(d);
            return w ? (
              <div className="dl-rescission">
                Statutory buyer rescission window: through <b>{w.p3}</b> (personal delivery) /{" "}
                <b>{w.p5}</b> (by mail). Computed
                from the received date; the real clock runs from delivery to the buyer.
              </div>
            ) : null;
          })()}
          {d.doc_type === "purchase_agreement" && (
            <div className="dl-keyfacts">
              {price && <div className="dl-kf"><span>Price</span><b>{price}</b></div>}
              {acc && <div className="dl-kf"><span>Acceptance</span><b>{acc}</b></div>}
              {coe && <div className="dl-kf"><span>Close of escrow</span><b>{shortDate(coe.due_date)}</b></div>}
              <div className="dl-kf"><span>Fields</span><b>{fields.length} <small>{fields.filter((f) => !f.confirmed).length} open</small></b></div>
            </div>
          )}
        </div>
        <div className="dl-objbody">
          {FACETS.filter((fc) => byFacet.has(fc)).map((fc) => {
            const fs = byFacet.get(fc) as ExtractedField[];
            const openHere = fs.filter((f) => !f.confirmed && f.confidence >= 0.7);
            return (
              <div className="dl-facet" key={fc}>
                <div className="dl-faceth">
                  <h4>{fc}</h4>
                  <span className="dl-fhn">{fs.length}</span>
                  {openHere.length > 1 && (
                    <button
                      className="dl-mini dl-fhact"
                      disabled={busy}
                      onClick={() =>
                        void confirmFields(
                          openHere.map((f) => f.id),
                          `${openHere.length} fields confirmed. Low-confidence fields still need review.`,
                        )
                      }
                    >
                      Confirm {openHere.length} readable
                    </button>
                  )}
                </div>
                <div className={fs.length > 4 ? "dl-grid2" : ""}>{fs.map(fieldRow)}</div>
              </div>
            );
          })}
          {fields.length === 0 && d.facts && (d.facts.facts?.length || d.facts.summary) && (
            <div className="dl-facet">
              <div className="dl-faceth">
                <h4>What Terra read from it</h4>
                <span className="dl-fhn">{d.facts.facts?.length ?? 0}</span>
              </div>
              {d.facts.summary && <p className="dl-summary">{d.facts.summary}</p>}
              {(d.facts.facts ?? []).map((f, i) => (
                <div className="dl-fr" key={i}>
                  <span className="dl-fn">{f.label}</span>
                  <span className="dl-fv" title={f.value}>{f.value}</span>
                  <span className="dl-kind">{f.kind}</span>
                  <span className={`dl-conf ${f.confidence < 0.7 ? "low" : ""}`}>
                    {f.confidence.toFixed(2)}
                  </span>
                  {(d.doc_type === "request_for_repairs" || d.doc_type === "repair_response") && (
                    <button
                      className="dl-mini"
                      disabled={busy}
                      title="Promote this read item into a tracked repair (your click is the confirmation)"
                      onClick={() =>
                        void run(
                          () =>
                            api.post(`/transactions/${id}/repairs`, {
                              description: `${f.label}: ${f.value}`.slice(0, 300),
                              source_document_id: d.id,
                            }),
                          "Repair tracked",
                        )
                      }
                    >
                      Track
                    </button>
                  )}
                </div>
              ))}
              <p className="dl-note">
                For reference only. These values do not affect fields, parties, or deadlines.
              </p>
            </div>
          )}
          {fields.length === 0 && !(d.facts && (d.facts.facts?.length || d.facts.summary)) && (
            <div className="dl-facet">
              <div className="dl-faceth"><h4>No structured data</h4></div>
              <p className="dl-note">
                No extracted data for this document.
              </p>
            </div>
          )}
          {open.length > 1 && fields.length > 0 && (
            <button
              className="dl-act pri"
              disabled={busy}
              style={{ marginTop: 12 }}
              onClick={() =>
                void confirmFields(
                  open.map((f) => f.id),
                  `${open.length} fields confirmed. Low-confidence fields still need review.`,
                )
              }
            >
              Confirm all {open.length} readable fields
            </button>
          )}
          {(d.doc_type === "request_for_repairs" || d.doc_type === "repair_response") &&
            (state.repairs ?? []).length > 0 && (
              <div className="dl-facet">
                <div className="dl-faceth">
                  <h4>Tracked repairs</h4>
                  <span className="dl-fhn">
                    {(state.repairs ?? []).filter((r) => r.status === "open").length} open
                  </span>
                </div>
                {(state.repairs ?? []).map((r) => (
                  <div className="dl-fr" key={r.id}>
                    <span className="dl-fv" style={r.status === "resolved" ? { textDecoration: "line-through", color: "var(--muted)" } : undefined}>
                      {r.description}
                    </span>
                    {r.status === "open" ? (
                      <button
                        className="dl-mini pri"
                        disabled={busy}
                        onClick={() =>
                          void run(
                            () => api.post(`/transactions/${id}/repairs/${r.id}/resolve`),
                            "Repair resolved",
                          )
                        }
                      >
                        Resolve
                      </button>
                    ) : (
                      <span className="dl-okmark"><Icon name="check" size={13} /></span>
                    )}
                  </div>
                ))}
                <p className="dl-note">Resolving is human-only by design (repair.resolve is never machine-actionable).</p>
              </div>
            )}
          {(flags.length > 0 || DOC_ROLE[d.doc_type ?? ""]) && (
            <div className="dl-facet">
              <div className="dl-faceth"><h4>Checks</h4></div>
              {flags.length === 0 ? (
                <div className="dl-check"><span className="dot ok" />No open flags from this document.</div>
              ) : (
                flags.map((f) => (
                  <div className="dl-check" key={f.id}>
                    <span className={`dot ${f.severity === "critical" ? "danger" : "warn"}`} />
                    {f.description}
                  </div>
                ))
              )}
            </div>
          )}
          {activity.length > 0 && (
            <div className="dl-facet">
              <div className="dl-faceth"><h4>Activity</h4></div>
              {activity.map((a, i) => (
                <div className="dl-actrow" key={i}>
                  <span className="dl-when">{shortDate(a.created_at)}</span>
                  <span>
                    {a.action === "payload.written"
                      ? `Filed. ${(a.details as { field_count?: number }).field_count ?? 0} fields extracted.`
                      : a.action === "document.superseded"
                        ? "Superseded an earlier version (one agreement per deal)"
                        : `Labeled: ${(a.details as { label?: string }).label ?? ""}`}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </>
    );
  }

  return (
    <div className="dl-frame">
      <div className="dl-filters">
        {(["all", "needs", "done", "miss"] as const).map((f) => (
          <button
            key={f}
            className={`dl-fchip ${filter === f ? "on" : ""}`}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? "All" : f === "needs" ? "Needs you" : f === "done" ? "On file" : "Missing"}
            <span className="dl-n">{counts[f]}</span>
          </button>
        ))}
        <button
          className="dl-fchip dl-story-btn"
          disabled={storyBusy || state.documents.length === 0}
          onClick={() => (story ? setStory(null) : void weaveStory())}
          title="Summarize the deal across all documents"
        >
          <Icon name="sparkle" size={12} />
          {storyBusy ? "Generating…" : story ? "Hide summary" : "Deal summary"}
        </button>
      </div>
      {story && (
        <div className="dl-story">
          <p className="dl-story-narrative">{story.narrative}</p>
          {story.observations.map((o, i) => (
            <div className="dl-check" key={i}>
              <span
                className={`dot ${o.severity === "critical" ? "danger" : o.severity === "warn" ? "warn" : "ok"}`}
              />
              <span>
                {o.text}
                {o.sources.length > 0 && (
                  <span className="dl-story-src"> ({o.sources.join(", ")})</span>
                )}
              </span>
            </div>
          ))}
          <p className="dl-note">
            Generated from extracted data only. Verify anything unexpected against the documents.
          </p>
        </div>
      )}
      <div className="dl-split">
        <div className="dl-list" role="listbox" aria-label="Documents">
          {GROUPS.map((g) => {
            const rows = visible.filter((r) => (r.kind === "doc" ? r.group : r.ghost.group) === g);
            if (!rows.length) return null;
            return (
              <div key={g}>
                <div className="dl-gname">{g}</div>
                {rows.map(listRow)}
              </div>
            );
          })}
          {visible.length === 0 && <div className="dl-empty">Nothing under this filter.</div>}
        </div>
        <div className="dl-detail">{detail()}</div>
      </div>
    </div>
  );
}
