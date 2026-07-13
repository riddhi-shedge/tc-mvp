import { useEffect, useState } from "react";
import { supabase } from "./lib/supabase";
import { Deal } from "./screens/Deal";
import { Inbox } from "./screens/Inbox";
import { Login } from "./screens/Login";

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
    <div className="shell">
      <div className="topbar">
        <h1>tc-mvp — walking skeleton (synthetic data only)</h1>
        <button
          className="secondary"
          onClick={() => void supabase.auth.signOut().then(() => setSignedIn(false))}
        >
          Sign out
        </button>
      </div>
      {view.name === "inbox" && (
        <Inbox onOpenDeal={(id) => setView({ name: "deal", id })} />
      )}
      {view.name === "deal" && (
        <Deal id={view.id} onBack={() => setView({ name: "inbox" })} />
      )}
    </div>
  );
}
