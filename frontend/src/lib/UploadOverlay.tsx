import { useEffect, useMemo, useState } from "react";

/* A calm, real-estate-themed processing overlay shown while a document is read
 * and the deal is assembled. The house blueprint draws itself while a scan line
 * sweeps the document and the status advances through the real steps the backend
 * is taking. The first step names the document being read (falls back to a
 * generic "document" when the filename isn't known). */
const REST_STEPS = [
  "Identifying buyers, sellers & agents…",
  "Extracting price, deposits & key dates…",
  "Computing California contingency deadlines…",
  "Assembling your deal workspace…",
];

// Trim a filename down to something readable for the status line.
function docLabel(name?: string | null): string {
  const raw = (name ?? "").trim().replace(/\.[a-z0-9]+$/i, "").replace(/[_-]+/g, " ").trim();
  return raw || "document";
}

export function UploadOverlay({ show, docName }: { show: boolean; docName?: string | null }) {
  const [i, setI] = useState(0);
  const steps = useMemo(() => [`Reading ${docLabel(docName)}…`, ...REST_STEPS], [docName]);
  useEffect(() => {
    if (!show) {
      setI(0);
      return;
    }
    const t = setInterval(() => setI((x) => Math.min(x + 1, steps.length - 1)), 1600);
    return () => clearInterval(t);
  }, [show, steps.length]);

  if (!show) return null;
  return (
    <div className="uplo-backdrop" role="status" aria-live="polite">
      <div className="uplo-card">
        <div className="uplo-art">
          <svg viewBox="0 0 120 120" width="112" height="112">
            {/* faint blueprint grid */}
            <g className="uplo-grid">
              {[24, 48, 72, 96].map((n) => (
                <line key={`h${n}`} x1="8" y1={n} x2="112" y2={n} />
              ))}
              {[24, 48, 72, 96].map((n) => (
                <line key={`v${n}`} x1={n} y1="8" x2={n} y2="112" />
              ))}
            </g>
            {/* house — draws itself */}
            <g className="uplo-house" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <path pathLength={1} d="M18 58 L60 24 L102 58" />
              <path pathLength={1} d="M28 54 V98 H92 V54" />
              <path pathLength={1} d="M52 98 V74 H68 V98" />
              <rect pathLength={1} x="36" y="64" width="12" height="12" rx="1.5" />
              <line pathLength={1} x1="12" y1="98" x2="108" y2="98" />
            </g>
            {/* scan sweep */}
            <rect className="uplo-scan" x="10" y="20" width="100" height="6" rx="3" />
          </svg>
        </div>
        <div className="uplo-title">Processing your document</div>
        <div className="uplo-step" key={i}>{steps[i]}</div>
        <div className="uplo-bar"><span /></div>
        <div className="uplo-foot">This usually takes a few seconds — no need to wait here.</div>
      </div>
    </div>
  );
}
