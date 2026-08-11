import { useState } from "react";
import { Icon } from "../lib/icons";
import { toast } from "../lib/ui";
import { recentErrors } from "../lib/errorlog";

/* Remote admin console — a separate full-screen mode for an org admin / developer
 * to oversee every coordinator's workspace, health and errors. The current product
 * is single-TC, so the cross-TC roster and org analytics here are PROTOTYPE data
 * (clearly labelled). Wiring this for real needs org tenancy + an admin role — the
 * one genuinely new backend capability among these features. Your own session's
 * real captured errors are merged into the feed so it isn't purely synthetic. */

type Health = "ok" | "warn" | "crit";
const TCS: { id: string; n: string; s: string; h: Health; st: string }[] = [
  { id: "jr", n: "Jordan Rivera", s: "6 active · 2 closing this wk", h: "ok", st: "Healthy" },
  { id: "am", n: "Aisha Mensah", s: "9 active · 1 error", h: "warn", st: "1 error" },
  { id: "dl", n: "Diego Lara", s: "4 active", h: "ok", st: "Healthy" },
  { id: "sk", n: "Sana Kapoor", s: "7 active · degraded", h: "crit", st: "Degraded" },
  { id: "tw", n: "Tomás Weber", s: "5 active", h: "ok", st: "Healthy" },
];
const HCOLOR: Record<Health, string> = { ok: "var(--green-600)", warn: "var(--amber-600)", crit: "var(--red-600)" };

type Sev = "crit" | "warn" | "info" | "ok";
const SAMPLE_ERRS: { ref: string; sev: Sev; msg: string; tc: string; when: string; status: string }[] = [
  { ref: "TERRA-4831", sev: "crit", msg: "Unhandled render error — deal timeline", tc: "Sana Kapoor", when: "2 min ago", status: "Open" },
  { ref: "TERRA-4825", sev: "warn", msg: "Supabase timeout on documents fetch", tc: "Aisha Mensah", when: "41 min ago", status: "Acknowledged" },
  { ref: "TERRA-4788", sev: "warn", msg: "AI extraction confidence below threshold ×3", tc: "Diego Lara", when: "Yesterday", status: "Resolved" },
];

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "errors", label: "Errors & crashes" },
  { id: "activity", label: "Activity log" },
  { id: "workspaces", label: "Workspaces" },
];

export function Admin({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState("overview");
  const mine = recentErrors().map((e) => ({
    ref: e.ref, sev: "info" as Sev, msg: e.message, tc: "Jordan Rivera (you)", when: new Date(e.at).toLocaleTimeString(), status: e.status === "sent" ? "Sent" : "Auto-resolved",
  }));
  const errs = [...mine, ...SAMPLE_ERRS];

  return (
    <div className="adm">
      <div className="adm-bar">
        <div className="adm-lg">
          <div className="adm-sq">T</div>
          <div className="adm-nm">Terra</div>
          <span className="adm-tag">REMOTE ADMIN · PROTOTYPE</span>
        </div>
        <span className="muted adm-org">Rivera &amp; Co. Realty · 5 coordinators</span>
        <div style={{ flex: 1 }} />
        <button className="kbtn" onClick={() => toast("Impersonation is read-only and fully audited.")}>
          <Icon name="user" size={14} /> View as TC
        </button>
        <button className="kbtn" onClick={onClose}>Exit admin <Icon name="chevron" size={14} /></button>
      </div>

      <div className="adm-body">
        <aside className="adm-tcs">
          <div className="adm-tcs-h">Coordinators</div>
          {TCS.map((t) => (
            <button key={t.id} className="adm-tc" onClick={() => toast(`Opens ${t.n}'s workspace (read-only, audited)`)}>
              <span className="adm-hdot" style={{ background: HCOLOR[t.h] }} />
              <span className="adm-tc-who">
                <span className="adm-tc-n">{t.n}</span>
                <span className="adm-tc-s">{t.s}</span>
              </span>
            </button>
          ))}
          <div className="adm-tcs-h" style={{ marginTop: 8 }}>Platform health</div>
          <div className="adm-health">
            <div><span className="sev-tag ok">OK</span> Uptime 99.98%</div>
            <div><span className="sev-tag warn">P95</span> API latency 240ms</div>
          </div>
        </aside>

        <div className="adm-center">
          <div className="adm-tabs">
            {TABS.map((t) => (
              <button key={t.id} className={`adm-tab ${tab === t.id ? "on" : ""}`} onClick={() => setTab(t.id)}>
                {t.label}
                {t.id === "errors" && <span className="adm-badge">{errs.length}</span>}
              </button>
            ))}
          </div>

          {tab === "overview" && (
            <>
              <div className="adm-kpis">
                <Kpi k="Active coordinators" v="5" s="all signed in today" />
                <Kpi k="Active deals (org)" v="31" s="▲ 4 this week" />
                <Kpi k="Org close rate" v="91%" s="on-time, trailing 90d" />
                <Kpi k="AI recs approved" v="86%" s="of surfaced · adoption" />
              </div>
              <div className="adm-cols">
                <div className="card">
                  <div className="card-h"><h3>Errors — last 14 days</h3><span className="chip-sample">sample</span></div>
                  <div className="adm-spark">
                    {[9, 7, 11, 6, 8, 5, 7, 4, 6, 3, 5, 4, 3, 2].map((v, i) => (
                      <i key={i} style={{ height: v * 7 }} />
                    ))}
                  </div>
                  <p className="muted adm-p">
                    Analytics-on-analytics: error rate per 1k sessions, crash-free %, and AI adoption roll up here for
                    the whole org.
                  </p>
                </div>
                <div className="card">
                  <div className="card-h"><h3>Needs an admin's eyes</h3><span className="chip-sample">sample</span></div>
                  <div className="adm-alert"><span className="sev-dot crit" /><div><b>Sana Kapoor — workspace degraded</b><div className="muted">1 open crash · timeline render error</div></div></div>
                  <div className="adm-alert"><span className="sev-dot warn" /><div><b>Aisha Mensah — Supabase timeouts ×3</b><div className="muted">documents fetch · last 40 min</div></div></div>
                </div>
              </div>
            </>
          )}

          {tab === "errors" && (
            <div className="card">
              <div className="card-h"><h3>Error &amp; crash feed</h3><span className="muted" style={{ marginLeft: "auto", fontSize: ".78rem" }}>auto-captured · routed to engineering</span></div>
              <div className="adm-tbl-wrap">
                <table className="adm-tbl">
                  <thead><tr><th>Ref</th><th>Severity</th><th>What happened</th><th>TC affected</th><th>When</th><th>Status</th><th /></tr></thead>
                  <tbody>
                    {errs.map((e) => (
                      <tr key={e.ref}>
                        <td><span className="adm-ref">{e.ref}</span></td>
                        <td><span className={`sev-tag ${e.sev}`}>{e.sev.toUpperCase()}</span></td>
                        <td>{e.msg}</td>
                        <td>{e.tc}</td>
                        <td className="muted">{e.when}</td>
                        <td><span className={`badge ${e.status === "Open" ? "err" : e.status === "Acknowledged" ? "draft" : "ok"}`}>{e.status}</span></td>
                        <td><button className="mini-btn" onClick={() => toast("Assigned to on-call engineer")}>Assign</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {tab === "activity" && (
            <div className="card">
              <div className="card-h"><h3>Org-wide activity</h3><span className="chip-sample">sample</span></div>
              {[
                ["Sana Kapoor", "opened deal 2841 Bryant St", "2 min ago"],
                ["System", "auto-captured error TERRA-4831", "2 min ago"],
                ["Aisha Mensah", "approved AI draft → sent to escrow", "12 min ago"],
                ["Jordan Rivera", "closed deal 88 Cortland Ave", "1 h ago"],
                ["Diego Lara", "invited party: Old Republic Title", "3 h ago"],
              ].map((l, i) => (
                <div key={i} className="adm-log">
                  <span className="adm-log-ava">{l[0].slice(0, 2).toUpperCase()}</span>
                  <div className="adm-log-main"><span><b>{l[0]}</b> {l[1]}</span><div className="muted">{l[2]}</div></div>
                </div>
              ))}
            </div>
          )}

          {tab === "workspaces" && (
            <>
              <p className="muted adm-p" style={{ marginTop: 0 }}>
                Inspect any coordinator's live workspace (read-only, audited) to troubleshoot what they see.
              </p>
              <div className="adm-ws">
                {TCS.map((t) => (
                  <button key={t.id} className="adm-ws-card" onClick={() => toast(`Loads ${t.n}'s Home in read-only mode`)}>
                    <div className="adm-ws-h"><span className="adm-hdot" style={{ background: HCOLOR[t.h] }} /> {t.n} <span className="muted" style={{ marginLeft: "auto" }}>{t.st}</span></div>
                    <div className="adm-ws-open">Open workspace <Icon name="chevron" size={13} /></div>
                    <div className="muted adm-ws-s">{t.s}</div>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Kpi({ k, v, s }: { k: string; v: string; s: string }) {
  return (
    <div className="adm-kpi">
      <div className="adm-kpi-k">{k}</div>
      <div className="adm-kpi-v tnum">{v}</div>
      <div className="adm-kpi-s">{s}</div>
    </div>
  );
}
