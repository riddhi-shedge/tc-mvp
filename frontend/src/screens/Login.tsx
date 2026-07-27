import { FormEvent, useState } from "react";
import { supabase } from "../lib/supabase";
import { Icon } from "../lib/icons";

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
    <div className="auth">
      <div className="auth-brand">
        <svg className="auth-contours" viewBox="0 0 500 700" preserveAspectRatio="xMidYMid slice" aria-hidden>
          <defs>
            <linearGradient id="cline" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#cca24a" stopOpacity="0.5" />
              <stop offset="1" stopColor="#cca24a" stopOpacity="0.04" />
            </linearGradient>
          </defs>
          {Array.from({ length: 9 }).map((_, i) => (
            <ellipse
              key={i}
              cx="365"
              cy="330"
              rx={40 + i * 52}
              ry={30 + i * 44}
              fill="none"
              stroke="url(#cline)"
              strokeWidth="1.2"
              opacity={0.9 - i * 0.09}
            />
          ))}
        </svg>
        <div className="auth-brand-inner">
          <div className="brand-mark-lg">T</div>
          <h1 className="auth-title">Terra</h1>
          <p className="auth-tagline">
            Transaction coordination for California residential real estate — every
            deadline computed, nothing sent without your tap.
          </p>
          <ul className="auth-props">
            <li><span className="ic"><Icon name="calendar" /></span> Every contingency &amp; deadline, computed to the day</li>
            <li><span className="ic"><Icon name="shield" /></span> Human-approved — nothing sends on its own</li>
            <li><span className="ic"><Icon name="pin" /></span> California RPA-accurate (rev. 6/26)</li>
          </ul>
          <span className="auth-trust">◆ Synthetic demo data — safe to explore</span>
        </div>
      </div>

      <div className="auth-form">
        <div className="auth-card">
          <div className="card">
            <h2>Sign in</h2>
            <p className="auth-sub">Welcome back — enter your credentials to continue.</p>
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
    </div>
  );
}
