import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import { Deal } from "./screens/Deal";
import { Home } from "./screens/Home";
import { Calendar } from "./screens/Calendar";
import { Inbox } from "./screens/Inbox";
import { Login } from "./screens/Login";
import { InviteView } from "./screens/InviteView";
import { Quarter } from "./screens/Quarter";
import { Recommendations } from "./screens/Recommendations";
import { CommandPalette } from "./screens/CommandPalette";
import { Support } from "./screens/Support";
import { Admin } from "./screens/Admin";
import { GuideModal, GuidePage, guideSeen } from "./screens/Guide";
import { ErrorBoundary } from "./lib/ErrorBoundary";
import { Toaster } from "./lib/ui";
import { Icon } from "./lib/icons";
import { motion } from "framer-motion";

// An invited party arrives with their scoped token in the URL fragment
// (#invite=<token>) — the fragment never reaches a server or a log.
const inviteToken = (() => {
  const m = /[#&]invite=([^&]+)/.exec(window.location.hash);
  return m ? decodeURIComponent(m[1]) : null;
})();

// A workspace is a daytime tool — default to the bright theme and only honor a
// deliberate opt-in to dark (never the OS setting, which was forcing dark on TCs
// who work in dark-mode OSes). Applied before first paint so there's no flash.
const _initTheme = localStorage.getItem("theme") === "dark" ? "dark" : "light";
document.documentElement.setAttribute("data-theme", _initTheme);

type View =
  | { name: "home" }
  | { name: "calendar" }
  | { name: "inbox" }
  | { name: "quarter" }
  | { name: "guide" }
  | { name: "deal"; id: string };

const VIEW_KEY = "tc_view";
const VIEW_NAMES = ["home", "calendar", "inbox", "quarter", "guide", "deal"];

// Persist the current view so a page refresh keeps the TC where they were —
// most importantly, on the deal they were reading rather than bouncing home.
function loadView(): View {
  try {
    const raw = localStorage.getItem(VIEW_KEY);
    if (raw) {
      const v = JSON.parse(raw) as View;
      if (v && VIEW_NAMES.includes(v.name) && (v.name !== "deal" || typeof v.id === "string")) {
        return v;
      }
    }
  } catch {
    /* ignore malformed state */
  }
  return { name: "home" };
}

export default function App() {
  // An invited party (not a TC) lands here — no login, just their scoped view.
  if (inviteToken) return <InviteView token={inviteToken} />;

  return <TcApp />;
}

function TcApp() {
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [view, setView] = useState<View>(() => loadView());
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebar_collapsed") === "1");
  const [supportOpen, setSupportOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [railOpen, setRailOpen] = useState(() => localStorage.getItem("rail_open") !== "0");
  const [cmdOpen, setCmdOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function toggleRail() {
    setRailOpen((r) => {
      localStorage.setItem("rail_open", r ? "0" : "1");
      return !r;
    });
  }

  const [dark, setDark] = useState(
    () => document.documentElement.getAttribute("data-theme") === "dark",
  );
  function toggleTheme() {
    setDark((d) => {
      const next = !d;
      document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
      localStorage.setItem("theme", next ? "dark" : "light");
      return next;
    });
  }

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

  useEffect(() => {
    if (signedIn && !guideSeen()) setShowGuide(true);
  }, [signedIn]);

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify(view));
    } catch {
      /* ignore */
    }
  }, [view]);

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

        <div className="nav-search" title="Search (coming soon)">
          <Icon name="search" size={14} /> Search…<kbd>⌘K</kbd>
        </div>

        <button
          className={`nav-item ${view.name === "home" ? "active" : ""}`}
          onClick={() => setView({ name: "home" })}
        >
          {view.name === "home" && (
            <motion.span layoutId="side-ind" className="side-ind" transition={{ type: "spring", stiffness: 400, damping: 34 }} />
          )}
          <span className="ni-label"><span className="ic"><Icon name="home" /></span> Home</span>
        </button>
        <button
          className={`nav-item ${view.name === "calendar" ? "active" : ""}`}
          onClick={() => setView({ name: "calendar" })}
        >
          {view.name === "calendar" && (
            <motion.span layoutId="side-ind" className="side-ind" transition={{ type: "spring", stiffness: 400, damping: 34 }} />
          )}
          <span className="ni-label"><span className="ic"><Icon name="calendar" /></span> Calendar</span>
        </button>
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
          <span className="ni-label"><span className="ic"><Icon name="deals" /></span> Deals &amp; Inbox</span>
        </button>
        <button
          className={`nav-item ${view.name === "quarter" ? "active" : ""}`}
          onClick={() => setView({ name: "quarter" })}
        >
          {view.name === "quarter" && (
            <motion.span layoutId="side-ind" className="side-ind" transition={{ type: "spring", stiffness: 400, damping: 34 }} />
          )}
          <span className="ni-label"><span className="ic"><Icon name="board" /></span> My quarter</span>
        </button>
        {view.name === "deal" && (
          <div className="nav-item active" style={{ cursor: "default" }}>
            <motion.span
              layoutId="side-ind"
              className="side-ind"
              transition={{ type: "spring", stiffness: 400, damping: 34 }}
            />
            <span className="ni-label"><span className="ic"><Icon name="doc" /></span> Current deal</span>
          </div>
        )}

        <div className="spacer" />
        <button
          className={`nav-item ${view.name === "guide" ? "active" : ""}`}
          onClick={() => setView({ name: "guide" })}
        >
          {view.name === "guide" && (
            <motion.span layoutId="side-ind" className="side-ind" transition={{ type: "spring", stiffness: 400, damping: 34 }} />
          )}
          <span className="ni-label"><span className="ic"><Icon name="clipboard" /></span> Guide</span>
        </button>
        <button className="nav-item" onClick={() => setSupportOpen(true)}>
          <span className="ni-label"><span className="ic"><Icon name="shield" /></span> Help &amp; support</span>
        </button>
        <button className="nav-item nav-admin" onClick={() => setAdminOpen(true)}>
          <span className="ni-label"><span className="ic"><Icon name="lock" /></span> Admin console</span>
          <span className="admin-tag">ADMIN</span>
        </button>
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
        <div className="topbar">
          <div className="crumbs">
            {view.name === "deal" ? (
              <>
                <span>Deals</span>
                <span className="sep">›</span>
                <b>Current deal</b>
              </>
            ) : (
              <b>
                {view.name === "home"
                  ? "Home"
                  : view.name === "calendar"
                    ? "Calendar"
                    : view.name === "quarter"
                      ? "My quarter"
                      : view.name === "guide"
                        ? "Guide"
                        : "Deals"}
              </b>
            )}
          </div>
          <div className="top-sp" />
          <button className="kbtn" title="Ask Terra" onClick={() => setCmdOpen(true)}>
            <Icon name="search" size={14} /> Ask Terra <kbd>⌘K</kbd>
          </button>
          <button
            className="kbtn pri"
            title="Create — deals start from inbound documents"
            onClick={() => { setView({ name: "inbox" }); setCollapsed(false); }}
          >
            <Icon name="plus" size={14} /> Create
          </button>
          {view.name !== "deal" && (
            <button
              className={`kbtn icon notif ${railOpen ? "on" : ""}`}
              title="Notifications & recommendations"
              aria-label="Notifications"
              onClick={toggleRail}
            >
              <Icon name="bell" size={15} />
              <span className="dot" />
            </button>
          )}
          <button className="kbtn icon" title="Help &amp; support" aria-label="Help and support" onClick={() => setSupportOpen(true)}>
            <Icon name="help" size={15} />
          </button>
          <button className="kbtn icon" title="Toggle theme" aria-label="Toggle theme" onClick={toggleTheme}>
            <Icon name={dark ? "sun" : "moon"} size={15} />
          </button>
        </div>
        <div className={`workarea ${railOpen && view.name !== "deal" ? "" : "rail-closed"}`}>
        <div className="page">
          <ErrorBoundary>
          {view.name === "calendar" && (
            <Calendar onOpenDeal={(id) => { setView({ name: "deal", id }); setCollapsed(true); }} />
          )}
          {view.name === "home" && (
            <Home
              onOpenDeal={(id) => {
                setView({ name: "deal", id });
                setCollapsed(true);
              }}
              onOpenRail={() => setRailOpen(true)}
            />
          )}
          {view.name === "quarter" && <Quarter />}
          {view.name === "guide" && <GuidePage />}
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
          </ErrorBoundary>
        </div>
        {railOpen && view.name !== "deal" && (
          <aside className="ctx-rail">
            <Recommendations
              onOpenDeal={(id) => {
                setView({ name: "deal", id });
                setCollapsed(true);
              }}
              onClose={() => setRailOpen(false)}
            />
          </aside>
        )}
        </div>
      </main>

      {cmdOpen && (
        <CommandPalette
          onClose={() => setCmdOpen(false)}
          onOpenDeal={(id) => { setView({ name: "deal", id }); setCollapsed(true); }}
          onGoHome={() => setView({ name: "home" })}
          onGoDeals={() => setView({ name: "inbox" })}
          onToggleTheme={toggleTheme}
        />
      )}
      {supportOpen && <Support onClose={() => setSupportOpen(false)} />}
      {adminOpen && <Admin onClose={() => setAdminOpen(false)} />}
      {showGuide && (
        <GuideModal
          onClose={() => setShowGuide(false)}
          onOpenFull={() => {
            setShowGuide(false);
            setView({ name: "guide" });
          }}
        />
      )}

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
