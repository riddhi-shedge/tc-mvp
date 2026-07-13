import { useCallback, useEffect, useState } from "react";
import { api, InboxItem, TransactionSummary } from "../lib/api";

/** HITL screen: pending inbound emails from the dedicated deal address.
 *  Nothing commits to the SOR until the TC confirms here. */
export function Inbox({ onOpenDeal }: { onOpenDeal: (id: string) => void }) {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [transactions, setTransactions] = useState<TransactionSummary[]>([]);
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

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

  async function confirm(item: InboxItem) {
    const decision = decisions[item.id] ?? "new";
    setBusy(item.id);
    setError(null);
    try {
      const result = await api.post<{ transaction_id: string }>(
        `/ingestion/inbox/${item.id}/confirm`,
        { decision },
      );
      await refresh();
      onOpenDeal(result.transaction_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Confirm failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="card">
        <h2>Inbound — dedicated deal address</h2>
        {items.length === 0 && <p className="muted">No pending emails.</p>}
        {items.map((item) => (
          <div key={item.id} className="row" style={{ marginBottom: "0.75rem" }}>
            <div>
              <strong>{item.subject ?? "(no subject)"}</strong>
              <div className="muted">
                from {item.from_email}
                {item.attachment_name ? ` · ${item.attachment_name}` : " · no attachment"}
              </div>
            </div>
            <div>
              <label>New deal, or attach to which existing?</label>
              <select
                value={decisions[item.id] ?? "new"}
                onChange={(e) => setDecisions({ ...decisions, [item.id]: e.target.value })}
              >
                <option value="new">Create new deal</option>
                {transactions.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.property_address ?? t.id}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ flex: "0 0 auto" }}>
              <button disabled={busy === item.id} onClick={() => void confirm(item)}>
                Confirm
              </button>
            </div>
          </div>
        ))}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="card">
        <h2>Deals</h2>
        {transactions.length === 0 && <p className="muted">No transactions yet.</p>}
        <table>
          <tbody>
            {transactions.map((t) => (
              <tr key={t.id}>
                <td>{t.property_address ?? "(no property)"}</td>
                <td>
                  <span className="badge">{t.status}</span>
                </td>
                <td style={{ textAlign: "right" }}>
                  <button className="secondary" onClick={() => onOpenDeal(t.id)}>
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
