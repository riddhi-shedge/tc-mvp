import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import { Deal } from "./screens/Deal";
import { Inbox } from "./screens/Inbox";
import { Login } from "./screens/Login";
import { Toaster } from "./lib/ui";

type View = { name: "inbox" } | { name: "deal"; id: string };

export default function App() {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [view, setView] = useState<View>({ name: "inbox" });

  useEffect(() => {
    void supabase.auth.getSession().then(async ({ data }) => {
      if (data.session) {
        const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
        setSignedIn(aal?.currentLevel === "aal2");
      }
      setReady(true);
    });
  }, []);

  if (!ready) return null;
  if (!signedIn) return <Login onSignedIn={() => setSignedIn(true)} />;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">T</div>
          <div>
            <div className="name">Terra</div>
            <div className="sub">Coordinator</div>
          </div>
        </div>

        <button
          className={`nav-item ${view.name === "inbox" ? "active" : ""}`}
          onClick={() => setView({ name: "inbox" })}
        >
          <span className="ic">▤</span> Inbox &amp; Deals
        </button>
        {view.name === "deal" && (
          <div className="nav-item active" style={{ cursor: "default" }}>
            <span className="ic">◈</span> Current deal
          </div>
        )}

        <div className="spacer" />
        <div className="who">
          <span className="badge gold" style={{ fontSize: "0.66rem" }}>◆ Synthetic data</span>
        </div>
        <button
          className="nav-item"
          onClick={() => void supabase.auth.signOut().then(() => setSignedIn(false))}
        >
          <span className="ic">⇥</span> Sign out
        </button>
      </aside>

      <main className="main">
        <div className="page">
          {view.name === "inbox" && <Inbox onOpenDeal={(id) => setView({ name: "deal", id })} />}
          {view.name === "deal" && (
            <Deal id={view.id} onBack={() => setView({ name: "inbox" })} />
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
