import { FormEvent, useState } from "react";
import { supabase } from "../lib/supabase";

/** Password recovery landing (Track B): Supabase's reset email drops the user
 *  here with a recovery session. Set the new password, then sign back in
 *  normally (password + authenticator) — the recovery session is signed out on
 *  purpose so aal2 is always re-established the front door way. */

export function ResetPassword({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { error: err } = await supabase.auth.updateUser({ password });
      if (err) throw err;
      await supabase.auth.signOut();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rp-wrap">
      <div className="auth-card">
        <div className="card">
          <div className="lg-eyebrow">Password reset</div>
          <h2>Choose a new password</h2>
          <p className="auth-sub">
            Then sign in with it and your authenticator code as usual.
          </p>
          <form onSubmit={submit}>
            <label htmlFor="rp-pw">New password</label>
            <input
              id="rp-pw"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              required
            />
            <label htmlFor="rp-pw2">Confirm new password</label>
            <input
              id="rp-pw2"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
            <div style={{ marginTop: "1rem" }}>
              <button disabled={busy} style={{ width: "100%" }}>
                {busy ? (<><span className="spinner" /> Saving…</>) : "Set new password"}
              </button>
            </div>
          </form>
          {error && <p className="error" role="alert">{error}</p>}
        </div>
      </div>
    </div>
  );
}
