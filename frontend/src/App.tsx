import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import { Deal } from "./screens/Deal";
import { Inbox } from "./screens/Inbox";
import { Login } from "./screens/Login";
import { InviteView } from "./screens/InviteView";
import { Toaster } from "./lib/ui";
import { motion } from "framer-motion";

// An invited party arrives with their scoped token in the URL fragment
// (#invite=<token>) — the fragment never reaches a server or a log.
const inviteToken = (() => {
  const m = /[#&]invite=([^&]+)/.exec(window.location.hash);
  return m ? decodeURIComponent(m[1]) : null;
})();

type View = { name: "inbox" } | { name: "deal"; id: string };

export default function App() {
  // An invited party (not a TC) lands here — no login, just their scoped view.
  if (inviteToken) return <InviteView token={inviteToken} />;

  return <TcApp />;
}

function TcApp() {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [view, setView] = useState<View>({ name: "inbox" });
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebar_collapsed") === "1");

  function toggleSidebar() {
    setCollapsed((c) => {
      localStorage.setItem("sidebar_collapsed", c ? "0" : "1");
      return !c;
    });
  }

  useEffect(() => {
    void supabase.auth.getSession().then(async ({ data }) => {
      if (data.session) {
        setEmail(data.session.user.email ?? null);
        const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
        setSignedIn(aal?.currentLevel === "aal2");
      }
      setReady(true);
    });
  }, []);

  if (!ready) return null;
  if (!signedIn) return <Login onSignedIn={() => setSignedIn(true)} />;

  return (
    <div className={`app ${collapsed ? "collapsed" : ""}`}>
      {collapsed && (
        <button className="side-open" title="Show sidebar" aria-label="Show sidebar" onClick={toggleSidebar}>
          ☰
        </button>
      )}
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">T</div>
          <div>
            <div className="name">Terra</div>
            <div className="sub">Coordinator</div>
          </div>
          <button
            className="side-collapse"
            title="Hide sidebar"
            aria-label="Hide sidebar"
            onClick={toggleSidebar}
          >
            «
          </button>
        </div>

        <button
          className={`nav-item ${view.name === "inbox" ? "active" : ""}`}
          onClick={() => setView({ name: "inbox" })}
        >
          {view.name === "inbox" && (
            <motion.span
              layoutId="side-ind"
              className="side-ind"
              transition={{ type: "spring", stiffness: 400, damping: 34 }}
            />
          )}
          <span className="ni-label"><span className="ic">▤</span> Inbox &amp; Deals</span>
        </button>
        {view.name === "deal" && (
          <div className="nav-item active" style={{ cursor: "default" }}>
            <motion.span
              layoutId="side-ind"
              className="side-ind"
              transition={{ type: "spring", stiffness: 400, damping: 34 }}
            />
            <span className="ni-label"><span className="ic">◈</span> Current deal</span>
          </div>
        )}

        <div className="spacer" />
        <div className="side-synth">
          <span className="badge gold" style={{ fontSize: "0.66rem" }}>◆ Synthetic data</span>
        </div>
        <div className="side-account">
          <div className="side-ava">{(email ?? "?").slice(0, 1).toUpperCase()}</div>
          <div className="side-account-info">
            <div className="side-email">{email ?? "signed in"}</div>
            <div className="side-plan">Coordinator</div>
          </div>
          <button
            className="side-signout"
            title="Sign out"
            onClick={() => void supabase.auth.signOut().then(() => setSignedIn(false))}
          >
            ⇥
          </button>
        </div>
      </aside>

      <main className="main">
        <div className="page">
          {view.name === "inbox" && (
            <Inbox
              onOpenDeal={(id) => {
                setView({ name: "deal", id });
                setCollapsed(true); // focus mode: hide the nav inside a deal
              }}
            />
          )}
          {view.name === "deal" && (
            <Deal
              id={view.id}
              onBack={() => {
                setView({ name: "inbox" });
                setCollapsed(false);
              }}
            />
          )}
        </div>
      </main>

      <Toaster />
      {/* Shared SVG gradient for progress rings */}
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
        <defs>
          <linearGradient id="goldgrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#cca24a" />
            <stop offset="1" stopColor="#9a6b1e" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
}
