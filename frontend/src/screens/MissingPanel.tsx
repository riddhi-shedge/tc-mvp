import { FullState } from "../lib/api";
import { Icon } from "../lib/icons";

/** What a TC would notice is ABSENT: expected documents not yet received, §5
 *  fields still missing/unconfirmed (from the timeline gate), and key parties
 *  with no way to reach them. Derived entirely from the deal state — nothing
 *  here guesses; a row appears only when the gap is concrete. */

const EXPECTED_DOCS: { label: string; has: (types: Set<string>) => boolean }[] = [
  { label: "Purchase agreement", has: (t) => t.has("purchase_agreement") },
  {
    label: "Preapproval or proof of funds",
    has: (t) => t.has("preapproval") || t.has("proof_of_funds"),
  },
  { label: "Preliminary (title) report", has: (t) => t.has("preliminary_report") },
  { label: "Disclosures (TDS / SPQ / NHD)", has: (t) => t.has("disclosure") },
  {
    label: "Property inspection report",
    has: (t) => t.has("property_inspection") || t.has("inspection_report"),
  },
  { label: "Termite inspection report", has: (t) => t.has("termite_inspection") },
];

// Roles whose contact info the TC will need before close.
const CONTACT_ROLES: Record<string, string> = {
  buyer: "Buyer",
  seller: "Seller",
  buyer_agent: "Buyer's agent",
  listing_agent: "Listing agent",
  escrow: "Escrow",
};

function prettyField(name: string): string {
  return name.replace(/_/g, " ");
}

export function MissingPanel({ state }: { state: FullState }) {
  const types = new Set(state.documents.map((d) => d.doc_type ?? ""));

  const missingDocs = EXPECTED_DOCS.filter((e) => !e.has(types)).map((e) => e.label);
  // A contingency deadline already passed with no contingency removal on file
  // is a concrete gap (the buyer's right to back out never got closed out).
  const today = new Date().toISOString().slice(0, 10);
  const passedContingency = state.deadlines.some(
    (d) => d.name.toLowerCase().includes("contingency") && d.due_date < today,
  );
  if (passedContingency && !types.has("contingency_removal")) {
    missingDocs.push("Contingency removal (a contingency deadline has passed)");
  }

  const gate = state.timeline_gate;
  const missingFields = gate?.missing_fields ?? [];
  const unconfirmedFields = gate?.unconfirmed_fields ?? [];

  const noContact = state.parties.filter(
    (p) => p.role in CONTACT_ROLES && !p.email && !p.phone,
  );

  const total = missingDocs.length + missingFields.length + noContact.length;
  const anythingToShow = total > 0 || unconfirmedFields.length > 0;
  if (!anythingToShow) {
    return (
      <div className="card">
        <h2>
          <Icon name="check" size={17} /> Nothing missing
        </h2>
        <p className="muted" style={{ margin: 0 }}>
          All expected documents are on file, every deadline-driving field is present and
          confirmed, and key parties have contact info.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>
        <Icon name="flag" size={17} /> Missing from this deal
      </h2>

      {missingDocs.length > 0 && (
        <div style={{ marginBottom: "0.7rem" }}>
          <div className="muted" style={{ marginBottom: "0.3rem" }}>
            Documents not received yet
          </div>
          {missingDocs.map((label) => (
            <div key={label} className="missing-row">
              <span className="badge warn">missing</span> {label}
            </div>
          ))}
        </div>
      )}

      {(missingFields.length > 0 || unconfirmedFields.length > 0) && (
        <div style={{ marginBottom: "0.7rem" }}>
          <div className="muted" style={{ marginBottom: "0.3rem" }}>
            Deal terms (§5 fields)
          </div>
          {missingFields.map((name) => (
            <div key={name} className="missing-row">
              <span className="badge warn">missing</span> {prettyField(name)} — not found on any
              document; enter it or upload the document that carries it
            </div>
          ))}
          {unconfirmedFields.length > 0 && (
            <div className="missing-row">
              <span className="badge draft">unconfirmed</span>{" "}
              {unconfirmedFields.map(prettyField).join(", ")} — extracted but awaiting your
              confirmation below
            </div>
          )}
        </div>
      )}

      {noContact.length > 0 && (
        <div>
          <div className="muted" style={{ marginBottom: "0.3rem" }}>
            No way to reach
          </div>
          {noContact.map((p) => (
            <div key={p.id} className="missing-row">
              <span className="badge warn">no contact</span> {p.name ?? "(unnamed)"} —{" "}
              {CONTACT_ROLES[p.role]}: no email or phone on file (drafts to them can't send)
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
