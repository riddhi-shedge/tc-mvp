import { ChangeEvent, useCallback, useEffect, useState } from "react";
import {
  api,
  asExtractionError,
  InboxItem,
  S5_FIELD_NAMES,
  TransactionSummary,
} from "../lib/api";

const DOC_TYPE_LABELS: Record<string, string> = {
  purchase_agreement: "Purchase agreement",
  proof_of_funds: "Proof of funds",
  disclosure: "Disclosure",
  inspection_report: "Inspection report",
  unknown: "Unknown — pick a type",
};

/** HITL screen: pending inbound documents from the dedicated deal address plus
 *  the manual-upload fallback. The agent detects and suggests; nothing commits
 *  to the SOR until the TC confirms here. */
export function Inbox({ onOpenDeal }: { onOpenDeal: (id: string) => void }) {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [transactions, setTransactions] = useState<TransactionSummary[]>([]);
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [docTypes, setDocTypes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [uploadB64, setUploadB64] = useState<string | null>(null);
  // Manual field-entry fallback (open per item after an extraction 422)
  const [manualFor, setManualFor] = useState<string | null>(null);
  const [manualReasons, setManualReasons] = useState<string[]>([]);
  const [manualRows, setManualRows] = useState<{ name: string; value: string }[]>([]);
  const [showArchived, setShowArchived] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [inbox, txns] = await Promise.all([
        api.get<InboxItem[]>("/ingestion/inbox"),
        api.get<TransactionSummary[]>("/transactions"),
      ]);
      setItems(inbox);
      setTransactions(txns);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load inbox");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function decisionFor(item: InboxItem): string {
    return decisions[item.id] ?? item.suggestion?.transaction_id ?? "new";
  }

  async function confirm(item: InboxItem, manualFields?: { name: string; value: string }[]) {
    setBusy(item.id);
    setError(null);
    try {
      const docType = docTypes[item.id];
      const result = await api.post<{ transaction_id: string }>(
        `/ingestion/inbox/${item.id}/confirm`,
        {
          decision: decisionFor(item),
          ...(docType ? { doc_type: docType } : {}),
          ...(manualFields?.length ? { manual_fields: manualFields } : {}),
        },
      );
      setManualFor(null);
      await refresh();
      onOpenDeal(result.transaction_id);
    } catch (err) {
      const extraction = asExtractionError(err);
      if (extraction?.manual_fields_required) {
        // §4 error state: extraction refused to guess — open manual entry.
        setManualFor(item.id);
        setManualReasons(extraction.reasons);
        setManualRows([
          { name: "property_address", value: "" },
          { name: "close_of_escrow", value: "" },
        ]);
      } else {
        setError(err instanceof Error ? err.message : "Confirm failed");
      }
    } finally {
      setBusy(null);
    }
  }

  async function dismiss(item: InboxItem) {
    setBusy(item.id);
    try {
      await api.post(`/ingestion/inbox/${item.id}/dismiss`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dismiss failed");
    } finally {
      setBusy(null);
    }
  }

  function onFilePicked(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      setUploadB64(dataUrl.split(",", 2)[1] ?? null);
      setUploadName(file.name);
    };
    reader.readAsDataURL(file);
  }

  async function uploadManual() {
    if (!uploadName || !uploadB64) return;
    setBusy("upload");
    setError(null);
    try {
      await api.post("/ingestion/manual-upload", {
        filename: uploadName,
        content_base64: uploadB64,
      });
      setUploadName(null);
      setUploadB64(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(null);
    }
  }

  const pending = items.filter((i) => i.status === "pending");
  const needsManual = items.filter((i) => i.status === "needs_manual");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Inbox &amp; Deals</h1>
          <div className="muted">Triage inbound documents, and open any active deal.</div>
        </div>
      </div>

      {(() => {
        const active = transactions.filter((t) => t.status !== "archived");
        const archived = transactions.filter((t) => t.status === "archived");
        return (
          <div className="card">
            <div className="between" style={{ marginBottom: "1rem" }}>
              <h2 style={{ margin: 0 }}>🏠 Deals</h2>
              {archived.length > 0 && (
                <button className="secondary sm" onClick={() => setShowArchived((s) => !s)}>
                  {showArchived ? "Hide" : "Show"} archived ({archived.length})
                </button>
              )}
            </div>
            {active.length === 0 && (
              <div className="empty">
                <span className="emoji">🗂️</span>
                No active deals — confirm an inbound document to create one.
              </div>
            )}
            <div className="deal-grid">
              {active.map((t) => (
                <div key={t.id} className="deal-tile" onClick={() => onOpenDeal(t.id)}>
                  <div className="dt-addr">{t.property_address ?? "(no property on file)"}</div>
                  <span className={`badge ${t.status === "open" ? "ok" : ""}`} style={{ alignSelf: "flex-start" }}>
                    <span className="dot open" /> {t.status}
                  </span>
                  <div className="dt-meta">
                    <span className="dt-id">{t.id.slice(0, 8)}</span>
                    <span className="dt-open">Open →</span>
                  </div>
                </div>
              ))}
            </div>
            {showArchived && archived.length > 0 && (
              <div className="deal-grid" style={{ marginTop: "0.8rem" }}>
                {archived.map((t) => (
                  <div key={t.id} className="deal-tile archived" onClick={() => onOpenDeal(t.id)}>
                    <div className="dt-addr">{t.property_address ?? "(no property on file)"}</div>
                    <span className="badge" style={{ alignSelf: "flex-start" }}>archived</span>
                    <div className="dt-meta">
                      <span className="dt-id">{t.id.slice(0, 8)}</span>
                      <button
                        className="secondary sm"
                        onClick={async (e) => {
                          e.stopPropagation();
                          await api.post(`/transactions/${t.id}/unarchive`);
                          await refresh();
                        }}
                      >
                        Unarchive
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      <div className="card">
        <h2>📥 Inbound — dedicated deal address</h2>
        {pending.length === 0 && (
          <div className="empty">
            <span className="emoji">📨</span>
            Inbox zero. New documents emailed to the deal address land here for your review.
          </div>
        )}
        {pending.map((item) => (
          <div key={item.id} className="row" style={{ marginBottom: "0.9rem" }}>
            <div>
              <strong>{item.subject ?? "(no subject)"}</strong>{" "}
              <span className="badge">
                {DOC_TYPE_LABELS[item.detected_doc_type ?? "unknown"] ?? item.detected_doc_type}
              </span>
              {item.source === "manual" && <span className="badge"> manual upload</span>}
              <div className="muted">
                from {item.from_email}
                {item.attachment_name ? ` · ${item.attachment_name}` : ""}
                {item.attachment_count > 1 ? ` (+${item.attachment_count - 1} more)` : ""}
              </div>
              {item.suggestion && (
                <div className="muted">Suggested: {item.suggestion.reason}</div>
              )}
            </div>
            <div>
              <label>New deal, or attach to which existing?</label>
              <select
                value={decisionFor(item)}
                onChange={(e) => setDecisions({ ...decisions, [item.id]: e.target.value })}
              >
                <option value="new">Create new deal</option>
                {transactions.map((t) => (
                  <option key={t.id} value={t.id}>
                    {(t.property_address ?? t.id) +
                      (item.suggestion?.transaction_id === t.id ? " (suggested)" : "")}
                  </option>
                ))}
              </select>
              {item.detected_doc_type === "unknown" && (
                <>
                  <label>Document type</label>
                  <select
                    value={docTypes[item.id] ?? ""}
                    onChange={(e) => setDocTypes({ ...docTypes, [item.id]: e.target.value })}
                  >
                    <option value="">(choose)</option>
                    {Object.entries(DOC_TYPE_LABELS)
                      .filter(([k]) => k !== "unknown")
                      .map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                  </select>
                </>
              )}
            </div>
            <div style={{ flex: "0 0 auto", display: "flex", gap: "0.4rem" }}>
              <button
                disabled={
                  busy === item.id ||
                  (item.detected_doc_type === "unknown" && !docTypes[item.id])
                }
                title={
                  item.detected_doc_type === "unknown" && !docTypes[item.id]
                    ? "Pick a document type first"
                    : undefined
                }
                onClick={() => void confirm(item)}
              >
                {busy === item.id ? (
                  <>
                    <span className="spinner" />
                    Reading…
                  </>
                ) : (
                  "Confirm"
                )}
              </button>
              <button
                className="secondary"
                disabled={busy === item.id}
                onClick={() => void dismiss(item)}
              >
                Dismiss
              </button>
            </div>
          </div>
        ))}
        {manualFor && (
          <div className="why" style={{ borderLeftColor: "#b35c00" }}>
            <strong>Extraction needs your help — enter the fields manually.</strong>
            <ul>
              {manualReasons.map((reason, i) => (
                <li key={i}>{reason}</li>
              ))}
            </ul>
            {manualRows.map((row, i) => (
              <div className="row" key={i} style={{ marginBottom: "0.4rem" }}>
                <div>
                  <select
                    value={row.name}
                    onChange={(e) => {
                      const rows = [...manualRows];
                      rows[i] = { ...rows[i], name: e.target.value };
                      setManualRows(rows);
                    }}
                  >
                    {S5_FIELD_NAMES.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <input
                    placeholder="value as written on the document"
                    value={row.value}
                    onChange={(e) => {
                      const rows = [...manualRows];
                      rows[i] = { ...rows[i], value: e.target.value };
                      setManualRows(rows);
                    }}
                  />
                </div>
              </div>
            ))}
            <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.5rem" }}>
              <button
                className="secondary"
                onClick={() => setManualRows([...manualRows, { name: "purchase_price", value: "" }])}
              >
                + field
              </button>
              <button
                disabled={busy !== null || manualRows.every((r) => !r.value.trim())}
                onClick={() => {
                  const item = pending.find((i) => i.id === manualFor);
                  if (item)
                    void confirm(
                      item,
                      manualRows.filter((r) => r.value.trim()),
                    );
                }}
              >
                {manualFor && busy === manualFor ? (
                  <>
                    <span className="spinner" />
                    Saving…
                  </>
                ) : (
                  "Confirm with manual fields"
                )}
              </button>
              <button className="secondary" onClick={() => setManualFor(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </div>

      {needsManual.length > 0 && (
        <div className="card">
          <h2>Needs manual upload (unreadable)</h2>
          {needsManual.map((item) => (
            <div key={item.id} className="row" style={{ marginBottom: "0.6rem" }}>
              <div>
                <strong>{item.subject ?? "(no subject)"}</strong>
                <div className="muted">
                  from {item.from_email} — {item.needs_manual_reason}
                </div>
              </div>
              <div style={{ flex: "0 0 auto" }}>
                <button
                  className="secondary"
                  disabled={busy === item.id}
                  onClick={() => void dismiss(item)}
                >
                  Dismiss
                </button>
              </div>
            </div>
          ))}
          <p className="muted">Upload the readable copy below, then confirm it.</p>
        </div>
      )}

      <div className="card">
        <h2>📎 Manual upload</h2>
        <div className="dropzone">
          <input type="file" accept="application/pdf" onChange={onFilePicked} />
          <div style={{ marginTop: "0.7rem" }}>
            <button disabled={!uploadB64 || busy === "upload"} onClick={() => void uploadManual()}>
              {busy === "upload" ? (
                <>
                  <span className="spinner" />
                  Uploading…
                </>
              ) : (
                `Upload${uploadName ? ` ${uploadName}` : ""}`
              )}
            </button>
          </div>
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            Fallback for a document that didn't arrive by email (PDF).
          </p>
        </div>
      </div>

    </>
  );
}
