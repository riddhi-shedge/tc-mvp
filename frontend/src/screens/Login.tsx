import { FormEvent, useEffect, useRef, useState } from "react";
import { supabase } from "../lib/supabase";
import { Icon } from "../lib/icons";

/** Sign-in → TOTP MFA (enroll on first use, then challenge) → aal2 session.
 *  The API rejects anything below aal2, so this screen must finish MFA.
 *
 *  Terra is invite-only (no public signup), so this page IS the landing:
 *  the brand panel carries the product identity (Fraunces, evergreen, the
 *  contour motif) and an operable approve-loop micro-demo — a visitor can
 *  feel Rule 3 before ever signing in. */

// Supabase/API errors → words a human can act on.
function friendlyError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  const m = raw.toLowerCase();
  if (m.includes("invalid login credentials")) return "Wrong email or password.";
  if (m.includes("invalid totp") || m.includes("invalid code") || m.includes("expired"))
    return "Incorrect code. Codes refresh every 30 seconds.";
  if (m.includes("rate limit") || m.includes("too many"))
    return "Too many attempts. Please wait a minute and try again.";
  if (m.includes("already registered") || m.includes("already exists"))
    return "An account with this email already exists. Sign in instead.";
  if (m.includes("password") && (m.includes("short") || m.includes("least")))
    return "Password is too short. Use at least 8 characters.";
  if (m.includes("fetch") || m.includes("network"))
    return "Unable to reach the server. Please try again in a moment.";
  return raw || "Something went wrong. Please try again.";
}

// Deterministic topographic contour: a wobbled closed loop (Terra = land).
function contourPath(cx: number, cy: number, r: number, seed: number): string {
  const pts: [number, number][] = [];
  const N = 14;
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    const wob = 1 + 0.09 * Math.sin(a * 3 + seed * 1.7) + 0.05 * Math.sin(a * 5 + seed);
    pts.push([cx + Math.cos(a) * r * wob, cy + Math.sin(a) * r * wob * 0.78]);
  }
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < N; i++) {
    const p0 = pts[i];
    const p1 = pts[(i + 1) % N];
    const mx = (p0[0] + p1[0]) / 2;
    const my = (p0[1] + p1[1]) / 2;
    d += ` Q ${p0[0].toFixed(1)} ${p0[1].toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`;
  }
  return d + " Z";
}

/** P4: the operable approve-loop — the product's core promise, tappable. */
function ApproveLoopDemo() {
  const [phase, setPhase] = useState<"draft" | "sending" | "sent">("draft");
  useEffect(() => {
    if (phase === "sending") {
      const t = setTimeout(() => setPhase("sent"), 650);
      return () => clearTimeout(t);
    }
    if (phase === "sent") {
      const t = setTimeout(() => setPhase("draft"), 4200);
      return () => clearTimeout(t);
    }
  }, [phase]);
  return (
    <div className="lg-demo" aria-label="Interactive demo of the approval loop">
      <div className="lg-demo-eyebrow">Preview: message approval</div>
      <div className="lg-demo-card">
        <div className="lg-demo-to">
          To: Hector R. <span>· buyer's agent</span>
        </div>
        <div className="lg-demo-subj">Inspection report follow-up</div>
        <div className="lg-demo-body">
          Hi Hector, the inspection contingency ends Friday. Could you send the report
          when it's in? Happy to help with anything.
        </div>
        {phase === "sent" ? (
          <div className="lg-demo-sent">✓ Sent</div>
        ) : (
          <button
            className="lg-demo-btn"
            disabled={phase === "sending"}
            onClick={() => setPhase("sending")}
          >
            {phase === "sending" ? "Sending…" : "Approve & Send"}
          </button>
        )}
      </div>
      <div className="lg-demo-note">Every message requires manual approval.</div>
    </div>
  );
}

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState(() => {
    try {
      return localStorage.getItem("terra_last_email") ?? "";
    } catch {
      return "";
    }
  });
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"password" | "enroll" | "challenge">("password");
  const [factorId, setFactorId] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [totpSecret, setTotpSecret] = useState<string | null>(null);
  const [secretCopied, setSecretCopied] = useState(false);
  const submittingCode = useRef(false);

  // Account creation: available when self-serve signup is open, or when this
  // browser holds a workspace join link (the teammate needs an account first).
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [notice, setNotice] = useState<string | null>(null);
  const [signupOpen, setSignupOpen] = useState(false);
  const joinPending = (() => {
    try {
      return Boolean(localStorage.getItem("terra_join_token"));
    } catch {
      return false;
    }
  })();
  useEffect(() => {
    void import("../lib/api").then(({ orgApi }) =>
      orgApi
        .config()
        .then((c) => setSignupOpen(c.signup_mode === "open"))
        .catch(() => {}),
    );
  }, []);
  const canSignup = signupOpen || joinPending;

  async function afterPassword() {
    try {
      localStorage.setItem("terra_last_email", email);
    } catch {
      /* private mode — fine */
    }
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
      setTotpSecret(data.totp.secret ?? null);
      setStage("enroll");
    }
  }

  async function submitPassword(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "signup") {
        const { data, error: err } = await supabase.auth.signUp({ email, password });
        if (err) throw err;
        if (data.session) {
          await afterPassword(); // confirmations off: straight to MFA setup
        } else {
          setMode("signin");
          setNotice("Almost there — confirm your email from the message we sent, then sign in.");
        }
        return;
      }
      const { error: err } = await supabase.auth.signInWithPassword({ email, password });
      if (err) throw err;
      await afterPassword();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e?: FormEvent) {
    e?.preventDefault();
    if (!factorId || submittingCode.current) return;
    submittingCode.current = true;
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
      setError(friendlyError(err));
      setCode("");
    } finally {
      setBusy(false);
      submittingCode.current = false;
    }
  }

  // P3: numeric OTP input, auto-submit the moment 6 digits are in.
  function onCodeChange(v: string) {
    const digits = v.replace(/\D/g, "").slice(0, 6);
    setCode(digits);
    if (digits.length === 6 && !busy) void submitCode();
  }

  async function forgotPassword() {
    if (!email.trim()) {
      setError("Enter your email above first, then tap 'Forgot password?' again.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: window.location.origin,
      });
      setNotice("If an account exists for that address, a reset link is on its way.");
    } catch {
      setNotice("If an account exists for that address, a reset link is on its way.");
    } finally {
      setBusy(false);
    }
  }

  function copySecret() {
    if (!totpSecret) return;
    void navigator.clipboard?.writeText(totpSecret).then(() => {
      setSecretCopied(true);
      setTimeout(() => setSecretCopied(false), 2000);
    });
  }

  const stageEyebrow =
    stage === "password" ? "Secure sign-in" : stage === "enroll" ? "Step 2 of 2 · Set up your authenticator" : "Step 2 of 2 · Authenticator";

  return (
    <div className="auth">
      <div className="auth-brand">
        <svg className="auth-contours" viewBox="0 0 520 720" preserveAspectRatio="xMidYMid slice" aria-hidden>
          {Array.from({ length: 8 }).map((_, i) => (
            <path
              key={i}
              d={contourPath(400, 300, 56 + i * 62, i)}
              fill="none"
              stroke="var(--lg-contour)"
              strokeWidth="1.1"
              opacity={0.75 - i * 0.085}
            />
          ))}
        </svg>
        <div className="auth-brand-inner">
          <div className="lg-wordmark">Terra</div>
          <p className="auth-tagline">
            Transaction coordination for California residential real estate.
          </p>
          <ul className="auth-props">
            <li>
              <span className="ic"><Icon name="calendar" size={16} /></span>
              Deadlines computed from the current California RPA
            </li>
            <li>
              <span className="ic"><Icon name="doc" size={16} /></span>
              Reads and cross-checks every document in the deal
            </li>
            <li>
              <span className="ic"><Icon name="shield" size={16} /></span>
              Messages send only with your approval, and every action is logged
            </li>
          </ul>
          <ApproveLoopDemo />
          <span className="auth-trust">
            <Icon name="lock" size={12} /> Invite-only · demo data
          </span>
        </div>
      </div>

      <div className="auth-form">
        <div className="auth-card">
          <div className="card">
            <div className="lg-eyebrow">{stageEyebrow}</div>
            {stage === "password" && (
              <>
                <h2>{mode === "signup" ? "Create your account" : "Welcome back"}</h2>
                <p className="auth-sub">
                  {mode === "signup"
                    ? "Set an email and password, then add an authenticator."
                    : "Sign in to your workspace."}
                </p>
                {joinPending && (
                  <p className="lg-joinnote">
                    You've been invited to a workspace. Use the invited email address to
                    {" "}
                    {mode === "signup" ? "create your account" : "sign in"}.
                  </p>
                )}
                {notice && <p className="lg-joinnote">{notice}</p>}
                <form onSubmit={submitPassword}>
                  <label htmlFor="lg-email">Email</label>
                  <input
                    id="lg-email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoFocus={!email}
                    required
                  />
                  <div className="lg-pwrow">
                    <label htmlFor="lg-pw">Password</label>
                    {mode === "signin" && (
                      <button
                        type="button"
                        className="lg-forgot"
                        onClick={() => void forgotPassword()}
                      >
                        Forgot password?
                      </button>
                    )}
                  </div>
                  <div className="lg-pwwrap">
                    <input
                      id="lg-pw"
                      type={showPw ? "text" : "password"}
                      autoComplete={mode === "signup" ? "new-password" : "current-password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoFocus={!!email}
                      minLength={mode === "signup" ? 8 : undefined}
                      required
                    />
                    <button
                      type="button"
                      className="lg-pwtoggle"
                      aria-label={showPw ? "Hide password" : "Show password"}
                      onClick={() => setShowPw((v) => !v)}
                    >
                      {showPw ? "Hide" : "Show"}
                    </button>
                  </div>
                  <div style={{ marginTop: "1rem" }}>
                    <button disabled={busy} style={{ width: "100%" }}>
                      {busy ? (
                        <><span className="spinner" /> {mode === "signup" ? "Creating account…" : "Signing in…"}</>
                      ) : mode === "signup" ? (
                        "Create account"
                      ) : (
                        "Sign in"
                      )}
                    </button>
                  </div>
                </form>
                {canSignup && (
                  <p className="lg-modeswitch">
                    {mode === "signup" ? (
                      <>
                        Already have an account?{" "}
                        <button type="button" onClick={() => { setMode("signin"); setError(null); }}>
                          Sign in
                        </button>
                      </>
                    ) : (
                      <>
                        New to Terra?{" "}
                        <button type="button" onClick={() => { setMode("signup"); setError(null); }}>
                          Create your account
                        </button>
                      </>
                    )}
                  </p>
                )}
              </>
            )}
            {stage === "enroll" && (
              <>
                <h2>Set up your authenticator</h2>
                <p className="auth-sub">
                  First sign-in only: scan with any authenticator app (1Password, Google
                  Authenticator, Authy), then enter the 6-digit code.
                </p>
                <form onSubmit={submitCode}>
                  {qrCode && <img className="lg-qr" src={qrCode} alt="TOTP enrollment QR code" />}
                  {totpSecret && (
                    <div className="lg-secret">
                      <span className="muted">Can't scan?</span>
                      <code>{totpSecret}</code>
                      <button type="button" className="lg-copy" onClick={copySecret}>
                        {secretCopied ? "Copied ✓" : "Copy"}
                      </button>
                    </div>
                  )}
                  <label htmlFor="lg-code">6-digit code</label>
                  <input
                    id="lg-code"
                    className="lg-otp"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="••••••"
                    value={code}
                    onChange={(e) => onCodeChange(e.target.value)}
                    required
                  />
                  <div style={{ marginTop: "1rem" }}>
                    <button disabled={busy} style={{ width: "100%" }}>
                      {busy ? (<><span className="spinner" /> Verifying…</>) : "Verify & finish setup"}
                    </button>
                  </div>
                </form>
              </>
            )}
            {stage === "challenge" && (
              <>
                <h2>One more step</h2>
                <p className="auth-sub">Enter the code from your authenticator app.</p>
                <form onSubmit={submitCode}>
                  <label htmlFor="lg-code2">Authenticator code</label>
                  <input
                    id="lg-code2"
                    className="lg-otp"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="••••••"
                    value={code}
                    onChange={(e) => onCodeChange(e.target.value)}
                    autoFocus
                    required
                  />
                  <div style={{ marginTop: "1rem" }}>
                    <button disabled={busy} style={{ width: "100%" }}>
                      {busy ? (<><span className="spinner" /> Verifying…</>) : "Verify"}
                    </button>
                  </div>
                </form>
              </>
            )}
            {error && <p className="error" role="alert">{error}</p>}
            <p className="lg-invite">
              {signupOpen
                ? "Locked out of your authenticator? A workspace owner can reset it."
                : "Access is invite-only. Ask a workspace owner for an invite, or to reset your authenticator."}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
