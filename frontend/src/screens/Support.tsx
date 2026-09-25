import { useState } from "react";
import { Icon } from "../lib/icons";
import { toast } from "../lib/ui";
import { recentErrors } from "../lib/errorlog";

/* Help & support drawer. Shows the errors Terra captured in this browser this
 * session (with their references) and a report-a-problem box. Reports go out
 * by email: to the deployment's support address when one is configured
 * (VITE_SUPPORT_EMAIL), otherwise as copyable text for the TC's Terra contact.
 * Nothing here pretends to file tickets or page anyone. */

const DAY_FMT = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const SUPPORT_EMAIL: string = (import.meta.env.VITE_SUPPORT_EMAIL as string | undefined) ?? "";

export function Support({ onClose }: { onClose: () => void }) {
  const [msg, setMsg] = useState("");
  const errors = recentErrors();

  function reportText(): string {
    const refs = errors.map((e) => e.ref).join(", ");
    return [msg.trim(), refs ? `Error references: ${refs}` : "", `Page: ${window.location.href}`]
      .filter(Boolean)
      .join("\n\n");
  }

  function send() {
    const text = reportText();
    if (SUPPORT_EMAIL) {
      window.location.href =
        `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent("Terra problem report")}` +
        `&body=${encodeURIComponent(text)}`;
      return;
    }
    void navigator.clipboard
      ?.writeText(text)
      .then(() => toast("Report copied. Email it to your Terra contact."))
      .catch(() => toast("Could not copy. Select the text and copy it manually."));
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

        <div className="sup-block">
          <div className="sup-bt"><Icon name="warning" size={14} /> Captured this session</div>
          <p className="muted sup-p">
            Errors Terra catches in this browser are listed here with a reference you can
            include when reporting a problem.
          </p>
          {errors.length === 0 ? (
            <div className="sup-empty">No issues captured this session.</div>
          ) : (
            errors.map((e) => (
              <div key={e.ref} className="sup-err">
                <span className="sup-err-id">{e.ref}</span>
                <div className="sup-err-main">
                  <div className="sup-err-msg">{e.message}</div>
                  <div className="muted sup-err-when">{DAY_FMT.format(new Date(e.at))}</div>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="sup-block">
          <div className="sup-bt">Report a problem</div>
          <textarea
            className="sup-ta"
            placeholder="What went wrong? Any error references above are attached automatically."
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
          />
          <button className="kbtn pri sup-send" disabled={!msg.trim()} onClick={send}>
            {SUPPORT_EMAIL ? "Email support" : "Copy report"}
          </button>
          {!SUPPORT_EMAIL && (
            <p className="muted sup-p" style={{ marginTop: "0.5rem" }}>
              Copies the report so you can email it to your Terra contact.
            </p>
          )}
        </div>
      </aside>
    </>
  );
}
