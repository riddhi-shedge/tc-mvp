import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import { api, asExtractionError, InboxItem, TransactionSummary } from "../lib/api";
import { Icon } from "../lib/icons";

/** Batch intake: the TC drops a whole folder (or many files) at once. Each file
 *  joins the same inbox queue; Terra reads each one and labels it by content
 *  (ZDR-gated, same extractor as confirm). Files Terra can't identify are asked
 *  about — the TC picks the type. One click then files the whole batch: the
 *  purchase agreement creates the deal, everything else attaches to it. The
 *  click is the TC's HITL decision; extracted terms still land unconfirmed for
 *  per-field review inside the deal. */

type Phase =
  | "queued"
  | "uploading"
  | "labeling"
  | "ready" // labeled (by Terra or the TC)
  | "ask" // Terra couldn't tell — needs the TC
  | "skipped"
  | "confirming"
  | "done"
  | "error";

type BatchFile = {
  key: string;
  name: string; // display name (relative path when dropped as a folder)
  file: File | null; // null once uploaded / for skipped rows
  phase: Phase;
  note?: string;
  itemId?: string;
  docType?: string; // current label; undefined/"unknown" means ask
  guess?: string; // Terra's free-text best guess for out-of-vocabulary docs
  // Version signals from the content read — used to tell an original from a
  // ratified copy when two files carry the same label.
  signals?: { signed: boolean; subject_to_counter_offer: boolean };
  signalsFailed?: boolean; // content read failed — never rank this row
};

type ClassifyResponse = {
  doc_type: string;
  identified: boolean;
  guess?: string;
  signals?: { signed?: boolean; subject_to_counter_offer?: boolean };
};

function asSignals(s: ClassifyResponse["signals"]): BatchFile["signals"] {
  if (!s || typeof s.signed !== "boolean") return undefined;
  return { signed: s.signed, subject_to_counter_offer: Boolean(s.subject_to_counter_offer) };
}

/** Higher = more likely the operative (final) version: fully executed and not
 *  subject to a counter beats everything; unsigned drafts rank last. */
function versionRank(s: NonNullable<BatchFile["signals"]>): number {
  return (s.signed ? 2 : 0) + (s.subject_to_counter_offer ? 0 : 1);
}

function sigText(s: BatchFile["signals"]): string {
  if (!s) return "unreadable";
  if (s.signed && !s.subject_to_counter_offer) return "fully signed, no open counter";
  if (s.signed) return "signed but subject to a counter offer";
  return "not fully signed";
}

const BATCH_TYPE_LABELS: Record<string, string> = {
  purchase_agreement: "Purchase agreement",
  seller_counter_offer: "Seller counter offer",
  buyer_counter_offer: "Buyer counter offer",
  counter_offer: "Counter offer",
  contingency_removal: "Contingency removal",
  preapproval: "Preapproval / underwriter",
  preliminary_report: "Preliminary (title) report",
  proof_of_funds: "Proof of funds",
  disclosure: "Disclosure",
  property_inspection: "Property inspection",
  termite_inspection: "Termite inspection",
  inspection_report: "Inspection report",
  other: "Other document",
};

// ---- Folder traversal (drag-and-drop of directories) -------------------------
// Chrome/Safari/Firefox all expose webkitGetAsEntry; typed minimally here.
interface FsEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  fullPath: string;
  file(ok: (f: File) => void, err: (e: unknown) => void): void;
  createReader(): {
    readEntries(ok: (entries: FsEntry[]) => void, err: (e: unknown) => void): void;
  };
}

async function entryFiles(entry: FsEntry, prefix: string): Promise<{ file: File; path: string }[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => entry.file(resolve, reject));
    return [{ file, path: prefix + entry.name }];
  }
  if (!entry.isDirectory) return [];
  const reader = entry.createReader();
  const all: FsEntry[] = [];
  // readEntries returns results in chunks; keep reading until empty.
  for (;;) {
    const chunk = await new Promise<FsEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    );
    if (chunk.length === 0) break;
    all.push(...chunk);
  }
  const nested = await Promise.all(all.map((e) => entryFiles(e, `${prefix}${entry.name}/`)));
  return nested.flat();
}

async function collectDropped(dt: DataTransfer): Promise<{ file: File; path: string }[]> {
  const items = Array.from(dt.items ?? []);
  const entries = items
    .map((i) => (i as unknown as { webkitGetAsEntry?: () => FsEntry | null }).webkitGetAsEntry?.())
    .filter((e): e is FsEntry => Boolean(e));
  if (entries.length > 0) {
    const nested = await Promise.all(entries.map((e) => entryFiles(e, "")));
    return nested.flat();
  }
  return Array.from(dt.files).map((file) => ({ file, path: file.name }));
}

function readB64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result as string).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

export function BatchDrop({
  transactions,
  onOpenDeal,
  onQueueChanged,
  onHeldIdsChange,
}: {
  transactions: TransactionSummary[];
  onOpenDeal: (id: string) => void;
  onQueueChanged: () => void;
  onHeldIdsChange: (ids: string[]) => void;
}) {
  const [rows, setRows] = useState<BatchFile[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [target, setTarget] = useState<string>("new");
  const [filing, setFiling] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  const workingRef = useRef(false);
  const comparingRef = useRef(false);

  // Items held by the batch are hidden from the queue below so two UIs never
  // fight over the same document. Filed and failed rows are released — a failed
  // row's escape hatch is the normal per-item queue.
  useEffect(() => {
    onHeldIdsChange(
      rows
        .filter((r) => r.itemId && r.phase !== "done" && r.phase !== "error")
        .map((r) => r.itemId as string),
    );
  }, [rows, onHeldIdsChange]);

  function patch(key: string, updates: Partial<BatchFile>) {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...updates } : r)));
  }

  function addFiles(picked: { file: File; path: string }[]) {
    setBatchError(null);
    const added: BatchFile[] = picked.map(({ file, path }, i) => {
      const pdf = file.name.toLowerCase().endsWith(".pdf");
      return {
        key: `${Date.now()}-${i}-${path}`,
        name: path,
        file: pdf ? file : null,
        phase: pdf ? "queued" : "skipped",
        note: pdf ? undefined : "not a PDF",
      };
    });
    setRows((prev) => [...prev, ...added]);
  }

  // Upload + label the queue, three files at a time. The runner claims every
  // row that was queued when it started; drops that land mid-run re-trigger the
  // effect once the runner clears.
  useEffect(() => {
    const queued = rows.filter((r) => r.phase === "queued");
    if (workingRef.current || queued.length === 0) return;
    workingRef.current = true;
    queued.forEach((r) => patch(r.key, { phase: "uploading" }));

    async function processOne(row: BatchFile) {
      if (!row.file) return;
      try {
        const b64 = await readB64(row.file);
        const item = await api.post<InboxItem>("/ingestion/manual-upload", {
          filename: row.file.name,
          content_base64: b64,
          subject: row.name === row.file.name ? undefined : row.name,
        });
        const detected = item.detected_doc_type ?? "unknown";
        if (detected !== "unknown") {
          patch(row.key, { phase: "ready", itemId: item.id, docType: detected, file: null });
          return;
        }
        // Filename gave nothing — ask Terra to read the content itself.
        patch(row.key, { phase: "labeling", itemId: item.id, file: null });
        const label = await api.post<ClassifyResponse>(`/ingestion/inbox/${item.id}/classify`);
        patch(
          row.key,
          label.identified
            ? { phase: "ready", docType: label.doc_type, signals: asSignals(label.signals) }
            : {
                phase: "ask",
                docType: undefined,
                guess: label.guess || undefined,
                signals: asSignals(label.signals),
              },
        );
      } catch (err) {
        patch(row.key, {
          phase: "error",
          note: err instanceof Error ? err.message : "upload failed",
        });
      }
    }

    void (async () => {
      const CONCURRENCY = 3;
      for (let i = 0; i < queued.length; i += CONCURRENCY) {
        await Promise.all(queued.slice(i, i + CONCURRENCY).map(processOne));
      }
      workingRef.current = false;
      onQueueChanged();
      setRows((prev) => [...prev]); // re-run the effect for late arrivals
    })();
  }, [rows, onQueueChanged]); // eslint-disable-line react-hooks/exhaustive-deps

  // When two or more files claim the same label "purchase agreement" (usually
  // from filenames alone), read each one's content for version signals so Terra
  // can say which is the operative copy and which is an earlier version.
  useEffect(() => {
    const pas = rows.filter(
      (r) =>
        (r.phase === "ready" || r.phase === "ask") &&
        r.itemId &&
        r.docType === "purchase_agreement",
    );
    const unread = pas.filter((r) => !r.signals && !r.signalsFailed);
    if (comparingRef.current || pas.length < 2 || unread.length === 0) return;
    comparingRef.current = true;
    setComparing(true);
    void (async () => {
      for (const row of unread) {
        try {
          const label = await api.post<ClassifyResponse>(
            `/ingestion/inbox/${row.itemId}/classify`,
          );
          const signals = asSignals(label.signals);
          patch(row.key, {
            ...(signals ? { signals } : { signalsFailed: true }),
            // Content beats filename: if the read says it's actually something
            // else (e.g. a counter offer), relabel it out of the PA pile.
            ...(label.identified && label.doc_type !== row.docType
              ? { docType: label.doc_type }
              : {}),
          });
        } catch {
          patch(row.key, { signalsFailed: true });
        }
      }
      comparingRef.current = false;
      setComparing(false);
    })();
  }, [rows]); // eslint-disable-line react-hooks/exhaustive-deps

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    void collectDropped(e.dataTransfer).then(addFiles);
  }

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    addFiles(
      files.map((file) => ({
        file,
        path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
      })),
    );
    e.target.value = "";
  }

  const active = rows.filter((r) => r.phase !== "skipped" && r.phase !== "done");
  const settled = active.filter((r) => ["ready", "ask", "error"].includes(r.phase));
  const stillWorking = active.some((r) =>
    ["queued", "uploading", "labeling"].includes(r.phase),
  );
  const asks = active.filter((r) => r.phase === "ask" && !r.docType);
  const fileable = active.filter(
    (r) => (r.phase === "ready" || r.phase === "ask") && r.itemId && r.docType,
  );
  const paRows = fileable.filter((r) => r.docType === "purchase_agreement");
  const paCount = paRows.length;

  // Rank the competing purchase agreements by version signals. A unique winner
  // becomes Terra's suggestion; a tie is reported honestly — the TC picks.
  let paSuggestion: { keep: BatchFile; demote: BatchFile[] } | null = null;
  let paTie = false;
  if (paCount > 1 && paRows.every((r) => r.signals)) {
    const ranked = [...paRows].sort(
      (a, b) =>
        versionRank(b.signals as NonNullable<BatchFile["signals"]>) -
        versionRank(a.signals as NonNullable<BatchFile["signals"]>),
    );
    const top = versionRank(ranked[0].signals as NonNullable<BatchFile["signals"]>);
    const second = versionRank(ranked[1].signals as NonNullable<BatchFile["signals"]>);
    if (top > second) paSuggestion = { keep: ranked[0], demote: ranked.slice(1) };
    else paTie = true;
  }

  let blockReason: string | null = null;
  if (stillWorking) blockReason = "Terra is still reading the files…";
  else if (asks.length > 0)
    blockReason = `${asks.length} file${asks.length > 1 ? "s" : ""} need${asks.length > 1 ? "" : "s"} a type from you`;
  else if (fileable.length === 0) blockReason = "Nothing to file yet";
  else if (target === "new" && paCount === 0)
    blockReason = "A new deal needs a purchase agreement — label one, or attach to an existing deal";
  else if (target === "new" && paCount > 1)
    blockReason = comparing
      ? "Terra is comparing the purchase agreements…"
      : paSuggestion
        ? "Two purchase agreements — apply Terra's suggestion above, or relabel one"
        : "Two purchase agreements and Terra can't tell which is current — relabel one yourself";

  async function fileBatch() {
    setFiling(true);
    setBatchError(null);
    try {
      let txnId = target;
      // The purchase agreement anchors a NEW deal; into an existing deal it
      // files like any other document.
      const pa =
        target === "new" ? fileable.find((r) => r.docType === "purchase_agreement") : undefined;
      const rest = fileable.filter((r) => r !== pa);
      if (pa) {
        patch(pa.key, { phase: "confirming" });
        try {
          const created = await api.post<{ transaction_id: string }>(
            `/ingestion/inbox/${pa.itemId}/confirm`,
            { decision: "new", doc_type: pa.docType },
          );
          txnId = created.transaction_id;
          patch(pa.key, { phase: "done" });
        } catch (err) {
          const extraction = asExtractionError(err);
          patch(pa.key, {
            phase: "error",
            note: extraction?.manual_fields_required
              ? "extraction needs manual field entry — confirm it from the queue below"
              : err instanceof Error
                ? err.message
                : "confirm failed",
          });
          return; // no deal was created — the rest stays for the TC
        }
      }
      for (const row of rest) {
        patch(row.key, { phase: "confirming" });
        try {
          await api.post(`/ingestion/inbox/${row.itemId}/confirm`, {
            decision: txnId,
            doc_type: row.docType,
          });
          patch(row.key, { phase: "done" });
        } catch (err) {
          patch(row.key, {
            phase: "error",
            note: err instanceof Error ? err.message : "confirm failed",
          });
        }
      }
      onQueueChanged();
      if (txnId !== "new") onOpenDeal(txnId);
    } catch (err) {
      setBatchError(err instanceof Error ? err.message : "Filing failed");
    } finally {
      setFiling(false);
    }
  }

  return (
    <div className="card">
      <h2>
        <Icon name="inbox" size={17} /> Batch upload — drop a whole folder
      </h2>
      <div
        className={`dropzone batchdrop${dragOver ? " over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <p style={{ margin: 0 }}>
          <strong>Drop files or a folder here.</strong> Terra reads each PDF and labels it — you
          stay the one who files.
        </p>
        <div style={{ marginTop: "0.6rem", display: "flex", gap: "0.5rem", justifyContent: "center" }}>
          <label className="batchpick">
            Choose files
            <input type="file" accept="application/pdf" multiple onChange={onPick} hidden />
          </label>
          <label className="batchpick">
            Choose a folder
            <input
              type="file"
              multiple
              hidden
              onChange={onPick}
              ref={(el) => el?.setAttribute("webkitdirectory", "")}
            />
          </label>
        </div>
      </div>

      {rows.length > 0 && (
        <>
          <div style={{ marginTop: "0.8rem" }}>
            {rows.map((row) => (
              <div key={row.key} className="batchrow">
                <span className="batchname" title={row.name}>
                  {row.name}
                </span>
                {row.phase === "queued" && <span className="badge">waiting…</span>}
                {row.phase === "uploading" && (
                  <span className="badge">
                    <span className="spinner" /> uploading…
                  </span>
                )}
                {row.phase === "labeling" && (
                  <span className="badge navy">
                    <span className="spinner" /> Terra is reading…
                  </span>
                )}
                {row.phase === "confirming" && (
                  <span className="badge">
                    <span className="spinner" /> filing…
                  </span>
                )}
                {row.phase === "done" && <span className="badge ok">filed</span>}
                {row.phase === "skipped" && <span className="badge">skipped — {row.note}</span>}
                {row.phase === "error" && (
                  <span className="badge danger" title={row.note}>
                    {row.note ?? "failed"}
                  </span>
                )}
                {(row.phase === "ready" || row.phase === "ask") && (
                  <>
                    {row.phase === "ask" && !row.docType && !row.guess && (
                      <span className="badge warn">What is this?</span>
                    )}
                    {row.phase === "ask" && !row.docType && row.guess && (
                      <button
                        className="secondary batchguess"
                        title={`Terra's best guess — click to file as "Other document" under this name`}
                        onClick={() => patch(row.key, { docType: "other" })}
                      >
                        Terra thinks: {row.guess} — use it?
                      </button>
                    )}
                    <select
                      value={row.docType ?? ""}
                      onChange={(e) =>
                        patch(row.key, { docType: e.target.value || undefined })
                      }
                    >
                      <option value="">(choose a type)</option>
                      {Object.entries(BATCH_TYPE_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <button
                      className="secondary"
                      title="Remove from this batch (stays in the queue below)"
                      onClick={() => setRows((prev) => prev.filter((r) => r.key !== row.key))}
                    >
                      ×
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>

          {paCount > 1 && (comparing || paSuggestion || paTie) && (
            <div className="why" style={{ marginTop: "0.7rem" }}>
              {comparing && (
                <span>
                  <span className="spinner" /> Two files read as purchase agreements — Terra is
                  reading both to find the current version…
                </span>
              )}
              {!comparing && paSuggestion && (
                <>
                  <strong>{paSuggestion.keep.name}</strong> looks like the operative purchase
                  agreement ({sigText(paSuggestion.keep.signals)});{" "}
                  {paSuggestion.demote.map((r) => `"${r.name}" (${sigText(r.signals)})`).join(", ")}{" "}
                  look{paSuggestion.demote.length === 1 ? "s" : ""} like an earlier version.
                  <div style={{ marginTop: "0.45rem" }}>
                    <button
                      onClick={() =>
                        paSuggestion?.demote.forEach((r) =>
                          patch(r.key, {
                            docType: "other",
                            guess: "prior version of the purchase agreement",
                          }),
                        )
                      }
                    >
                      Keep "{paSuggestion.keep.name}" — file the other as a prior version
                    </button>
                  </div>
                </>
              )}
              {!comparing && paTie && (
                <span>
                  Terra read both purchase agreements and they look alike (
                  {sigText(paRows[0]?.signals)}) — it won't guess which is current. Pick one to
                  keep and relabel the other.
                </span>
              )}
            </div>
          )}

          {settled.length > 0 && (
            <div className="batchfile-bar">
              <label style={{ margin: 0 }}>File into</label>
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="new">a new deal (from the purchase agreement)</option>
                {transactions.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.property_address ?? t.id}
                  </option>
                ))}
              </select>
              <button
                disabled={filing || blockReason !== null}
                title={blockReason ?? undefined}
                onClick={() => void fileBatch()}
              >
                {filing ? (
                  <>
                    <span className="spinner" /> Filing…
                  </>
                ) : (
                  `File ${fileable.length} document${fileable.length === 1 ? "" : "s"}`
                )}
              </button>
              {blockReason && <span className="muted">{blockReason}</span>}
            </div>
          )}
          {batchError && <p className="error">{batchError}</p>}
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            Terra only labels — filing is your decision, and extracted terms still wait for your
            per-field confirmation inside the deal.
          </p>
        </>
      )}
    </div>
  );
}
