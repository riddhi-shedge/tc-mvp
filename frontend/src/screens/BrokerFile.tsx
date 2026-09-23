import { useState } from "react";
import { DealDocument, FullState } from "../lib/api";
import { fmtDate } from "../lib/format";
import { Icon } from "../lib/icons";

/** Wave 4A: the broker compliance file + close-out packet.
 *  Brokers audit closed files against a checklist; this card computes file
 *  completeness from the documents actually on record (type + label +
 *  universal-read content matching) and prints a close-out packet — the
 *  deal's full story on paper — straight from SOR data. Display-only. */

const short = (iso?: string | null) => (iso ? fmtDate(iso).replace(/,\s*\d{4}$/, "") : "");

function docText(d: DealDocument): string {
  return `${d.doc_type ?? ""} ${d.label ?? ""} ${d.facts?.doc_kind ?? ""} ${d.facts?.summary ?? ""}`;
}

// The CA broker-audit set: what a compliance reviewer expects in a closed file.
const FILE_ITEMS: { key: string; name: string; match: (docs: DealDocument[]) => DealDocument | undefined }[] = [
  { key: "pa", name: "Executed purchase agreement", match: (ds) => ds.find((d) => d.doc_type === "purchase_agreement") },
  { key: "counters", name: "Counter offers (chain)", match: (ds) => ds.find((d) => (d.doc_type ?? "").includes("counter")) },
  { key: "tds", name: "TDS", match: (ds) => ds.find((d) => /transfer disclosure|\bTDS\b/i.test(docText(d))) },
  { key: "spq", name: "SPQ", match: (ds) => ds.find((d) => /property questionnaire|\bSPQ\b/i.test(docText(d))) },
  { key: "nhd", name: "NHD report", match: (ds) => ds.find((d) => /natural hazard|\bNHD\b/i.test(docText(d))) },
  { key: "fld", name: "Lead-paint (FLD)", match: (ds) => ds.find((d) => /lead[- ]based paint|\bFLD\b/i.test(docText(d))) },
  { key: "avid", name: "AVID", match: (ds) => ds.find((d) => /\bAVID\b|visual inspection/i.test(docText(d))) },
  { key: "whsd", name: "WHSD", match: (ds) => ds.find((d) => /water heater|smoke detector|\bWHSD\b/i.test(docText(d))) },
  { key: "cr", name: "Contingency removals", match: (ds) => ds.find((d) => d.doc_type === "contingency_removal") },
  { key: "fin", name: "Financing evidence", match: (ds) => ds.find((d) => d.doc_type === "preapproval" || d.doc_type === "proof_of_funds") },
  { key: "prelim", name: "Preliminary report", match: (ds) => ds.find((d) => d.doc_type === "preliminary_report") },
  { key: "insp", name: "Inspection reports", match: (ds) => ds.find((d) => (d.doc_type ?? "").includes("inspection")) },
];

export function BrokerFile({ state }: { state: FullState }) {
  const [open, setOpen] = useState(false);
  const docs = state.documents;
  const rows = FILE_ITEMS.map((it) => ({ ...it, doc: it.match(docs) }));
  const met = rows.filter((r) => r.doc).length;
  const prop = state.property?.address ?? "(address pending)";
  const eff = state.effective_fields ?? {};
  const closing = state.closing_events ?? [];
  const repairs = state.repairs ?? [];

  return (
    <div className="card bf-card">
      <div className="between">
        <h2><Icon name="folder" size={17} /> Broker file · {met}/{rows.length}</h2>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button className="dl-mini" onClick={() => setOpen((v) => !v)}>
            {open ? "Hide checklist" : "Checklist"}
          </button>
          <button
            className="dl-mini pri"
            title="Print the close-out packet (browser print → save as PDF)"
            onClick={() => {
              document.body.classList.add("printing-packet");
              window.print();
              document.body.classList.remove("printing-packet");
            }}
          >
            Print close-out packet
          </button>
        </div>
      </div>
      <div className="bf-bar"><i style={{ width: `${(met / rows.length) * 100}%` }} /></div>
      {open && (
        <div className="bf-grid">
          {rows.map((r) => (
            <div key={r.key} className="bf-item">
              <span className={`bf-dot ${r.doc ? "ok" : ""}`}>{r.doc ? "✓" : "·"}</span>
              <span className={r.doc ? "" : "muted"}>{r.name}</span>
              {r.doc?.created_at && <span className="bf-when">{short(r.doc.created_at)}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Printable close-out packet: hidden on screen, the only thing on paper. */}
      <div className="packet">
        <h1>Close-out packet: {prop}</h1>
        <p className="pk-sub">Prepared {short(new Date().toISOString())} · Terra transaction record</p>
        <h2>Parties</h2>
        <table><tbody>
          {state.parties.map((p) => (
            <tr key={p.id}><td>{p.role.replace(/_/g, " ")}</td><td>{p.name}</td><td>{p.email ?? ""}</td></tr>
          ))}
        </tbody></table>
        <h2>Final terms</h2>
        <table><tbody>
          {Object.entries(eff).map(([k, v]) => (
            <tr key={k}><td>{k.replace(/_/g, " ")}</td><td>{v.value}{v.superseded_from ? ` (superseded: ${v.superseded_from})` : ""}</td></tr>
          ))}
        </tbody></table>
        <h2>Closing record</h2>
        <table><tbody>
          {closing.map((e) => (
            <tr key={e.id}><td>{e.step.replace(/_/g, " ")}</td><td>{e.occurred_on}</td></tr>
          ))}
        </tbody></table>
        <h2>Documents on file ({docs.length})</h2>
        <table><tbody>
          {docs.map((d) => (
            <tr key={d.id}>
              <td>{d.doc_type === "other" && d.label ? d.label : (d.doc_type ?? "").replace(/_/g, " ")}</td>
              <td>received {short(d.created_at)}</td>
            </tr>
          ))}
        </tbody></table>
        {repairs.length > 0 && (
          <>
            <h2>Repairs</h2>
            <table><tbody>
              {repairs.map((r) => (
                <tr key={r.id}><td>{r.description}</td><td>{r.status}</td></tr>
              ))}
            </tbody></table>
          </>
        )}
        <h2>File checklist</h2>
        <table><tbody>
          {rows.map((r) => (
            <tr key={r.key}><td>{r.name}</td><td>{r.doc ? `on file · ${short(r.doc.created_at)}` : "NOT ON FILE"}</td></tr>
          ))}
        </tbody></table>
        <p className="pk-foot">Generated from the transaction record. Deposit and disbursement details are not stored in this system.</p>
      </div>
    </div>
  );
}
