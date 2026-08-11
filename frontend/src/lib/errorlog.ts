/* A tiny client-side error log. The ErrorBoundary and any caught runtime error
 * append here; Help & support reads it. In production these entries would POST to
 * an error sink (e.g. Sentry) — the reference id is what surfaces to the TC and
 * to the admin console. Kept in-memory + last-N in localStorage for the session. */

export type CapturedError = {
  ref: string;
  message: string;
  at: string; // ISO
  screen: string;
  status: "sent" | "recovered";
};

const KEY = "tc_error_log_v1";
const MAX = 12;

function load(): CapturedError[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as CapturedError[]) : [];
  } catch {
    return [];
  }
}
function save(list: CapturedError[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list.slice(-MAX)));
  } catch {
    /* storage full / unavailable — non-fatal */
  }
}

export function newRef(): string {
  return "TERRA-" + Math.floor(1000 + Math.random() * 9000);
}

export function captureError(message: string, screen = "unknown", status: CapturedError["status"] = "sent"): CapturedError {
  const entry: CapturedError = { ref: newRef(), message, at: new Date().toISOString(), screen, status };
  save([...load(), entry]);
  return entry;
}

export function recentErrors(): CapturedError[] {
  return load().slice().reverse();
}
