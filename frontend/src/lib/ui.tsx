import { ReactNode, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

/** Brand-styled animated tabs: a sliding gold-underlined indicator (shared-layout
 *  animation) + a soft fade/slide on content change. */
export type TabDef = { id: string; label: string; icon?: string; content: ReactNode };
export function AnimatedTabs({ tabs, initial }: { tabs: TabDef[]; initial?: string }) {
  const [active, setActive] = useState(initial ?? tabs[0]?.id);
  const current = tabs.find((t) => t.id === active) ?? tabs[0];
  return (
    <div>
      <div className="tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`tab ${active === t.id ? "active" : ""}`}
            onClick={() => setActive(t.id)}
          >
            {active === t.id && (
              <motion.span
                layoutId="tab-ind"
                className="tab-ind"
                transition={{ type: "spring", stiffness: 380, damping: 32 }}
              />
            )}
            <span className="tab-label">
              {t.icon && <span>{t.icon}</span>}
              {t.label}
            </span>
          </button>
        ))}
      </div>
      <AnimatePresence mode="wait">
        <motion.div
          key={active}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        >
          {current?.content}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

/** SVG progress ring (0..1). Fill uses the shared #goldgrad gradient (defined
 *  once in App). */
export function Ring({
  value,
  size = 96,
  stroke = 9,
  children,
}: {
  value: number;
  size?: number;
  stroke?: number;
  children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(1, value));
  const offset = c * (1 - clamped);
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle className="ring-track" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} />
        <circle
          className="ring-fill"
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  );
}

/** Animate a number from 0 → target once on mount / when target changes. */
export function useCountUp(target: number, ms = 750): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms);
      setN(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
      else setN(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return n;
}

/** Animated count-up number (rounds), with optional suffix. */
export function CountUp({ value, suffix = "" }: { value: number; suffix?: string }) {
  const n = useCountUp(value);
  return (
    <>
      {Math.round(n)}
      {suffix}
    </>
  );
}

// ---- Toasts (module-level pub/sub; <Toaster/> mounted once in App) ---------
type Toast = { id: number; msg: string; error?: boolean };
let _toasts: Toast[] = [];
let _listeners: ((t: Toast[]) => void)[] = [];
let _id = 0;

export function toast(msg: string, opts?: { error?: boolean }) {
  const t: Toast = { id: ++_id, msg, error: opts?.error };
  _toasts = [..._toasts, t];
  _listeners.forEach((l) => l(_toasts));
  setTimeout(() => {
    _toasts = _toasts.filter((x) => x.id !== t.id);
    _listeners.forEach((l) => l(_toasts));
  }, 3400);
}

export function Toaster() {
  const [ts, setTs] = useState<Toast[]>(_toasts);
  useEffect(() => {
    _listeners.push(setTs);
    return () => {
      _listeners = _listeners.filter((l) => l !== setTs);
    };
  }, []);
  return (
    <div className="toast-wrap">
      {ts.map((t) => (
        <div key={t.id} className={`toast ${t.error ? "err" : ""}`}>
          <span>{t.error ? "⚠" : "✓"}</span>
          {t.msg}
        </div>
      ))}
    </div>
  );
}
