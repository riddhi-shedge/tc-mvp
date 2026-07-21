import { FormEvent, useState } from "react";
import { supabase } from "../lib/supabase";

/** Sign-in → TOTP MFA (enroll on first use, then challenge) → aal2 session.
 *  The API rejects anything below aal2, so this screen must finish MFA. */
export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"password" | "enroll" | "challenge">("password");
  const [factorId, setFactorId] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);

  async function afterPassword() {
    const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    if (aal?.currentLevel === "aal2") return onSignedIn();

    const { data: factors } = await supabase.auth.mfa.listFactors();
    const totp = factors?.totp?.[0];
    if (totp) {
      setFactorId(totp.id);
      setStage("challenge");
    } else {
      const { data, error: enrollErr } = await supabase.auth.mfa.enroll({
        factorType: "totp",
      });
      if (enrollErr || !data) throw enrollErr ?? new Error("MFA enroll failed");
      setFactorId(data.id);
      setQrCode(data.totp.qr_code);
      setStage("enroll");
    }
  }

  async function submitPassword(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { error: err } = await supabase.auth.signInWithPassword({ email, password });
      if (err) throw err;
      await afterPassword();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e: FormEvent) {
    e.preventDefault();
    if (!factorId) return;
    setBusy(true);
    setError(null);
    try {
      const { data: challenge, error: chErr } = await supabase.auth.mfa.challenge({
        factorId,
      });
      if (chErr || !challenge) throw chErr ?? new Error("MFA challenge failed");
      const { error: vErr } = await supabase.auth.mfa.verify({
        factorId,
        challengeId: challenge.id,
        code,
      });
      if (vErr) throw vErr;
      onSignedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <div className="mark">T</div>
          <div className="name">Terra</div>
          <div className="tagline">Transaction Coordinator</div>
        </div>
        <div className="card">
      <h2>Sign in</h2>
      {stage === "password" && (
        <form onSubmit={submitPassword}>
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <label>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <div style={{ marginTop: "0.9rem" }}>
            <button disabled={busy}>Sign in</button>
          </div>
        </form>
      )}
      {stage === "enroll" && (
        <form onSubmit={submitCode}>
          <p className="muted">
            First sign-in: scan this QR code with your authenticator app, then enter the
            6-digit code. MFA is required for every TC session.
          </p>
          {qrCode && <img src={qrCode} alt="TOTP enrollment QR code" style={{ width: "100%" }} />}
          <label>6-digit code</label>
          <input value={code} onChange={(e) => setCode(e.target.value)} required />
          <div style={{ marginTop: "0.9rem" }}>
            <button disabled={busy}>Verify &amp; finish enrollment</button>
          </div>
        </form>
      )}
      {stage === "challenge" && (
        <form onSubmit={submitCode}>
          <label>Authenticator code</label>
          <input value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
          <div style={{ marginTop: "0.9rem" }}>
            <button disabled={busy}>Verify</button>
          </div>
        </form>
      )}
      {error && <p className="error">{error}</p>}
        </div>
      </div>
    </div>
  );
}
