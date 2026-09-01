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

/** Version verdict for a group of same-type rows whose contents were all read:
 *  a unique best-ranked row is the likely current version; equal ranks mean
 *  Terra can't (and won't) pick. null until every row has signals. */
function suggestFor(
  group: BatchFile[],
): { keep: BatchFile; demote: BatchFile[] } | "tie" | null {
  if (group.length < 2 || !group.every((r) => r.signals)) return null;
  const ranked = [...group].sort(
    (a, b) =>
      versionRank(b.signals as NonNullable<BatchFile["signals"]>) -
      versionRank(a.signals as NonNullable<BatchFile["signals"]>),
  );
  const top = versionRank(ranked[0].signals as NonNullable<BatchFile["signals"]>);
  const second = versionRank(ranked[1].signals as NonNullable<BatchFile["signals"]>);
  return top > second ? { keep: ranked[0], demote: ranked.slice(1) } : "tie";
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
  const [comparing, setComparing] = useState<string | null>(null); // docType being read
  const workingRef = useRef(false);
  const comparingRef = useRef(false);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;

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
        const item = await api.post<
          InboxItem & {
            duplicate_of?: InboxItem;
            already_filed?: { attachment_name?: string | null; transaction_id?: string | null };
          }
        >("/ingestion/manual-upload", {
          filename: row.file.name,
          content_base64: b64,
          subject: row.name === row.file.name ? undefined : row.name,
        });
        if (item.duplicate_of) {
          // Byte-identical to a document already waiting in the queue (or
          // earlier in this batch) — one copy is enough.
          const dupName = item.duplicate_of.attachment_name ?? "a file already in the queue";
          patch(row.key, {
            phase: "skipped",
            note: `exact duplicate of "${dupName}" — only one copy kept`,
            file: null,
          });
          return;
        }
        if (item.already_filed) {
          patch(row.key, {
            note: `an identical file was already filed${item.already_filed.attachment_name ? ` ("${item.already_filed.attachment_name}")` : ""} — confirm only if you mean to re-file it`,
          });
        }
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

  // Read the contents of every same-type row lacking version signals, so a
  // group of look-alike labels ("two purchase agreements", "two FHA addenda")
  // can be told apart: executed signatures / subject-to-counter decide which
  // is the operative copy and which is an earlier version.
  async function runCompare(type: string) {
    if (comparingRef.current) return;
    comparingRef.current = true;
    setComparing(type);
    try {
      const targets = rowsRef.current.filter(
        (r) =>
          (r.phase === "ready" || r.phase === "ask") &&
          r.itemId &&
          r.docType === type &&
          !r.signals &&
          !r.signalsFailed,
      );
      for (const row of targets) {
        try {
          const label = await api.post<ClassifyResponse>(
            `/ingestion/inbox/${row.itemId}/classify`,
          );
          const signals = asSignals(label.signals);
          patch(row.key, {
            ...(signals ? { signals } : { signalsFailed: true }),
            // Content beats filename: if the read says it's actually something
            // else (e.g. a counter offer), relabel it out of this pile.
            ...(label.identified && label.doc_type !== row.docType
              ? { docType: label.doc_type }
              : {}),
          });
        } catch {
          patch(row.key, { signalsFailed: true });
        }
      }
    } finally {
      comparingRef.current = false;
      setComparing(null);
    }
  }

  // Competing PURCHASE AGREEMENTS block deal creation, so those are compared
  // automatically. Other same-type groups often ARE different documents (a TDS
  // and an SPQ both label "disclosure") — Terra flags them and compares only
  // when the TC asks.
  useEffect(() => {
    const pas = rows.filter(
      (r) =>
        (r.phase === "ready" || r.phase === "ask") &&
        r.itemId &&
        r.docType === "purchase_agreement",
    );
    if (pas.length < 2 || !pas.some((r) => !r.signals && !r.signalsFailed)) return;
    void runCompare("purchase_agreement");
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
  // Same-label groups of 2+ — candidates for version comparison. The PA group
  // is special (it blocks new-deal creation); the rest are advisory.
  const typeGroups = new Map<string, BatchFile[]>();
  for (const r of fileable) {
    if (!r.docType || r.docType === "other") continue;
    typeGroups.set(r.docType, [...(typeGroups.get(r.docType) ?? []), r]);
  }
  const dupGroups = [...typeGroups.entries()].filter(([, g]) => g.length >= 2);

  const paRows = typeGroups.get("purchase_agreement") ?? [];
  const paCount = paRows.length;
  const paVerdict = suggestFor(paRows);
  const paSuggestion = paVerdict !== null && paVerdict !== "tie" ? paVerdict : null;

  let blockReason: string | null = null;
  if (stillWorking) blockReason = "Terra is still reading the files…";
  else if (asks.length > 0)
    blockReason = `${asks.length} file${asks.length > 1 ? "s" : ""} need${asks.length > 1 ? "" : "s"} a type from you`;
  else if (fileable.length === 0) blockReason = "Nothing to file yet";
  else if (target === "new" && paCount === 0)
    blockReason = "A new deal needs a purchase agreement — label one, or attach to an existing deal";
  else if (target === "new" && paCount > 1)
    blockReason =
      comparing === "purchase_agreement"
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
            // 'Other' filings keep their name (Terra's guess / "prior version…").
            ...(row.docType === "other" && row.guess ? { label: row.guess } : {}),
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
                    {row.note && (
                      <span className="badge warn" title={row.note}>
                        already filed?
                      </span>
                    )}
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

          {dupGroups.map(([type, group]) => {
            const label = BATCH_TYPE_LABELS[type] ?? type;
            const isPA = type === "purchase_agreement";
            const verdict = suggestFor(group);
            const reading = comparing === type;
            const unread = group.some((r) => !r.signals && !r.signalsFailed);
            if (!isPA && !reading && verdict === null && !unread) return null; // reads failed
            return (
              <div key={type} className="why" style={{ marginTop: "0.7rem" }}>
                {reading && (
                  <span>
                    <span className="spinner" /> {group.length} files read as {label} — Terra is
                    reading each to tell the versions apart…
                  </span>
                )}
                {!reading && verdict === null && unread && !isPA && (
                  <>
                    {group.length} files are labeled <strong>{label}</strong>. They may simply be
                    different documents of the same kind — but if they're two versions of one
                    document, Terra can read both and flag the outdated one.
                    <div style={{ marginTop: "0.45rem" }}>
                      <button className="secondary" onClick={() => void runCompare(type)}>
                        Compare versions
                      </button>
                    </div>
                  </>
                )}
                {!reading && verdict !== null && verdict !== "tie" && (
                  <>
                    <strong>{verdict.keep.name}</strong> looks like the current {label} (
                    {sigText(verdict.keep.signals)});{" "}
                    {verdict.demote.map((r) => `"${r.name}" (${sigText(r.signals)})`).join(", ")}{" "}
                    look{verdict.demote.length === 1 ? "s" : ""} like an earlier version.
                    <div style={{ marginTop: "0.45rem" }}>
                      <button
                        onClick={() =>
                          verdict.demote.forEach((r) =>
                            patch(r.key, {
                              docType: "other",
                              guess: `prior version of the ${label.toLowerCase()}`,
                            }),
                          )
                        }
                      >
                        Keep "{verdict.keep.name}" — file the other{" "}
                        {verdict.demote.length === 1 ? "as a prior version" : "s as prior versions"}
                      </button>
                    </div>
                  </>
                )}
                {!reading && verdict === "tie" && (
                  <span>
                    Terra read {group.length === 2 ? "both" : "all"} {label} files and they look
                    alike ({sigText(group[0]?.signals)}) — it won't guess.{" "}
                    {isPA
                      ? "Pick one to keep and relabel the other."
                      : "If they're genuinely different documents (say, a TDS and an SPQ), leave both as they are."}
                  </span>
                )}
              </div>
            );
          })}

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
