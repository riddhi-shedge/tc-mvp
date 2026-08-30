import { useEffect, useRef } from "react";

/** §7 live-sync. The SOR is authoritative; surfaces re-render projections on
 *  change. Lacking a Realtime socket on the invite token, we poll: re-run `fn`
 *  every `ms`, but only while the tab is visible (no work in the background). */
export function usePoll(fn: () => void, ms = 25000) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const tick = () => { if (document.visibilityState === "visible") ref.current(); };
    const id = window.setInterval(tick, ms);
    return () => window.clearInterval(id);
  }, [ms]);
}
