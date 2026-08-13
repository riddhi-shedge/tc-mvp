import { FullState } from "../lib/api";
import { Icon } from "../lib/icons";

/* A "space" per document: each uploaded document with the cross-checks it drove —
 * the risk flags it raised, or a passed state when its checks came back clean.
 * Flags are matched to a document by their case_key (the master's flag taxonomy). */

const DOC_LABEL: Record<string, string> = {
  purchase_agreement: "Purchase agreement",
  seller_counter_offer: "Seller counter offer",
  buyer_counter_offer: "Buyer counter offer",
  counter_offer: "Counter offer",
  contingency_removal: "Contingency removal",
  preapproval: "Preapproval / underwriter",
  preliminary_report: "Preliminary (title) report",
  property_inspection: "Property inspection",
  termite_inspection: "Termite inspection",
  proof_of_funds: "Proof of funds",
  disclosure: "Disclosure",
  inspection_report: "Inspection report",
  other: "Other",
  unknown: "Unknown",
};

// One line describing what each document type contributes to the deal.
const DOC_ROLE: Record<string, string> = {
  purchase_agreement: "The deal's terms, parties and timeline",
  seller_counter_offer: "Supersedes the agreement's price / terms",
  buyer_counter_offer: "Supersedes the agreement's price / terms",
  counter_offer: "Supersedes the agreement's price / terms",
  contingency_removal: "Removes contingencies from the timeline",
  preapproval: "Adds the loan officer; checks borrower, amount, expiry",
  preliminary_report: "Checks APN, owner of record and recency",
  property_inspection: "Adds the inspector; checks address and recency",
  termite_inspection: "Adds the pest company; checks address and recency",
};

const VALIDATED = new Set(Object.keys(DOC_ROLE));

function flagMatchesDoc(caseKey: string, docType: string): boolean {
  if (caseKey.startsWith("preapproval_")) return docType === "preapproval";
  if (caseKey.startsWith("prelim_")) return docType === "preliminary_report";
  if (caseKey.startsWith("inspection_"))
    return docType === "property_inspection" || docType === "termite_inspection";
  if (caseKey === "counter_not_accepted" || caseKey === "counter_chain")
    return docType.endsWith("counter_offer");
  if (caseKey === "counter_pending" || caseKey === "document_inconsistency")
    return docType === "purchase_agreement";
  return false;
}

export function DocumentChecks({ state }: { state: FullState }) {
  if (state.documents.length === 0) return null;
  const openFlags = state.risk_flags.filter((f) => !f.resolved);

  return (
    <div className="card">
      <h2><Icon name="clipboard" size={17} /> Documents &amp; checks</h2>
      <p className="muted" style={{ margin: "-0.4rem 0 0.9rem", fontSize: "0.82rem" }}>
        Each uploaded document and the cross-checks it drove against the deal.
      </p>
      <div className="dc-list">
        {state.documents.map((d) => {
          const t = d.doc_type ?? "unknown";
          const mine = openFlags.filter((f) => f.case_key && flagMatchesDoc(f.case_key, t));
          return (
            <div key={d.id} className="dc-doc">
              <span className="dc-ic"><Icon name="doc" size={18} /></span>
              <div className="dc-body">
                <div className="dc-head">
                  <span className="dc-t">{DOC_LABEL[t] ?? t}</span>
                  <span className={`badge ${d.status === "confirmed" ? "ok" : "draft"}`}>{d.status}</span>
                </div>
                {DOC_ROLE[t] && <div className="dc-role">{DOC_ROLE[t]}</div>}
                {mine.length > 0 ? (
                  <div className="dc-flags">
                    {mine.map((f) => (
                      <div key={f.id} className={`dc-flag ${f.severity === "critical" ? "crit" : "warn"}`}>
                        <Icon name="warning" size={12} /> {f.description}
                      </div>
                    ))}
                  </div>
                ) : VALIDATED.has(t) ? (
                  <div className="dc-ok"><Icon name="checkCircle" size={13} /> Checks passed</div>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
