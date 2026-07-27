import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, DEAL_STAGES, DealSummary } from "../lib/api";

type Cmd = { id: string; label: string; sub?: string; icon: string; kind: string; run: () => void };
const stageName = (id: string) => DEAL_STAGES.find((s) => s.id === id)?.name ?? id;

/** ⌘K command palette — jump to any deal or run an action, keyboard-first. */
export function CommandPalette({
  onClose,
  onOpenDeal,
  onGoHome,
  onGoDeals,
  onToggleTheme,
}: {
  onClose: () => void;
  onOpenDeal: (id: string) => void;
  onGoHome: () => void;
  onGoDeals: () => void;
  onToggleTheme: () => void;
}) {
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    void api.get<DealSummary[]>("/transactions/board").then(setDeals).catch(() => {});
  }, []);

  const commands: Cmd[] = useMemo(() => {
    const nav: Cmd[] = [
      { id: "home", label: "Home", sub: "Command center", icon: "◉", kind: "Go to", run: () => { onGoHome(); onClose(); } },
      { id: "deals", label: "Deals & Inbox", sub: "Pipeline & intake", icon: "▤", kind: "Go to", run: () => { onGoDeals(); onClose(); } },
      { id: "theme", label: "Toggle theme", icon: "◐", kind: "Action", run: () => { onToggleTheme(); onClose(); } },
    ];
    const dealCmds: Cmd[] = deals.map((d) => ({
      id: d.id,
      label: (d.property_address ?? "Deal").split(",")[0],
      sub: stageName(d.stage) + (d.risk_count > 0 ? ` · ⚠ ${d.risk_count}` : ""),
      icon: "◈",
      kind: "Open deal",
      run: () => { onOpenDeal(d.id); onClose(); },
    }));
    return [...nav, ...dealCmds];
  }, [deals]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return commands;
    return commands.filter((c) => `${c.label} ${c.sub ?? ""} ${c.kind}`.toLowerCase().includes(s));
  }, [q, commands]);

  useEffect(() => setI(0), [q]);
  useEffect(() => {
    (listRef.current?.children[i] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
  }, [i]);

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(x + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(x - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); filtered[i]?.run(); }
  }

  return (
    <div className="cmdk-backdrop" onClick={onClose}>
      <div className="cmdk" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="cmdk-input"
          placeholder="Search deals, jump anywhere, run an action…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
        />
        <div className="cmdk-list" ref={listRef}>
          {filtered.length === 0 && <div className="cmdk-empty">No matches</div>}
          {filtered.map((c, idx) => (
            <div
              key={c.id}
              className={`cmdk-row ${idx === i ? "on" : ""}`}
              onMouseEnter={() => setI(idx)}
              onClick={() => c.run()}
            >
              <span className="cmdk-ic">{c.icon}</span>
              <span className="cmdk-label">
                {c.label}
                {c.sub && <span className="cmdk-sub"> · {c.sub}</span>}
              </span>
              <span className="cmdk-kind">{c.kind}</span>
            </div>
          ))}
        </div>
        <div className="cmdk-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> select</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
