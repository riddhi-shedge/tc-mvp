import { useState } from "react";
import { Icon } from "../lib/icons";
import { toast } from "../lib/ui";
import { recentErrors } from "../lib/errorlog";

/* Help & support drawer. Slides in from the right. Shows system status, the
 * errors Terra captured automatically this session (with their references), and
 * a report-a-problem box that would attach the current screen + those refs. */

const DAY_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function Support({ onClose }: { onClose: () => void }) {
  const [msg, setMsg] = useState("");
  const errors = recentErrors();

  function send() {
    toast(`Sent to support with ticket #TERRA-${Math.floor(1000 + Math.random() * 9000)} — we'll email you an update.`);
    setMsg("");
    onClose();
  }

  return (
    <>
      <div className="sup-scrim" onClick={onClose} />
      <aside className="sup" role="dialog" aria-modal="true" aria-label="Help and support">
        <div className="sup-head">
          <span className="sup-head-ic"><Icon name="shield" size={16} /></span>
          <h2>Help &amp; support</h2>
          <button className="sup-x" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button>
        </div>

        <div className="sup-status">
          <span className="dot ok" />
          <b>All systems operational</b>
          <span className="muted" style={{ marginLeft: "auto" }}>status.terra.app</span>
        </div>

        <div className="sup-block">
          <div className="sup-bt"><Icon name="warning" size={14} /> Auto-captured this session</div>
          <p className="muted sup-p">
            If something breaks, Terra captures it and routes it to engineering automatically — your work is saved first.
          </p>
          {errors.length === 0 ? (
            <div className="sup-empty">No issues captured. Everything's running smoothly.</div>
          ) : (
            errors.map((e) => (
              <div key={e.ref} className="sup-err">
                <span className="sup-err-id">{e.ref}</span>
                <div className="sup-err-main">
                  <div className="sup-err-msg">{e.message}</div>
                  <div className="muted sup-err-when">{DAY_FMT.format(new Date(e.at))}</div>
                </div>
                <span className="sup-err-tag">{e.status === "sent" ? "SENT" : "OK"}</span>
              </div>
            ))
          )}
        </div>

        <div className="sup-block">
          <div className="sup-bt">Report a problem</div>
          <textarea
            className="sup-ta"
            placeholder="What went wrong? Terra attaches your current screen and any error references above automatically."
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
          />
          <button className="kbtn pri sup-send" disabled={!msg.trim()} onClick={send}>Send to support</button>
        </div>

        <div className="sup-block">
          <div className="sup-bt">More</div>
          <button className="sup-link" onClick={() => toast("Opens the help center")}>
            <Icon name="doc" size={14} /> Help center &amp; guides <Icon name="chevron" size={14} />
          </button>
          <button className="sup-link" onClick={() => toast("Live chat — average reply under 5 minutes")}>
            <Icon name="mail" size={14} /> Chat with support · avg 4 min <Icon name="chevron" size={14} />
          </button>
        </div>
      </aside>
    </>
  );
}
