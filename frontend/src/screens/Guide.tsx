import { useState } from "react";
import { Icon, IconName } from "../lib/icons";

/* Terra's built-in instruction manual. Two entry points share the same content:
 *  - <GuideModal>  — a first-run walkthrough shown once (localStorage-gated).
 *  - <GuidePage>   — the always-available reference under Help in the sidebar.
 * Everything here is static, self-contained documentation — no data fetching. */

const SEEN_KEY = "tc_guide_seen_v1";
export function guideSeen(): boolean {
  return localStorage.getItem(SEEN_KEY) === "1";
}
export function markGuideSeen(): void {
  localStorage.setItem(SEEN_KEY, "1");
}

type Feature = { icon: IconName; term: string; what: string; can: string[] };

const SECTIONS: { id: string; title: string; blurb: string; features: Feature[] }[] = [
  {
    id: "orient",
    title: "The workspace",
    blurb:
      "Terra is one place to run a residential transaction from contract to close. You navigate on the left, work in the center, and inspect or act in the right-hand rail. Everything connects: a deadline knows its document, a task knows its party, an AI suggestion knows its source.",
    features: [
      { icon: "home", term: "Home", what: "Your cross-deal command center — what's due, what's at risk, and this week's deadlines across every active transaction.", can: ["See a morning briefing", "Jump straight into any deal that needs attention", "Scan your open work queue"] },
      { icon: "search", term: "Ask Terra (⌘K)", what: "A command bar and assistant in one. Search a deal or ask a plain-English question grounded only in your data.", can: ["\"What needs my attention today?\"", "Jump to any deal or screen", "Draft a follow-up for review"] },
    ],
  },
  {
    id: "deals",
    title: "Transactions & the deal workspace",
    blurb:
      "A transaction (a \"deal\") is a single property sale you're coordinating. Open one and you get a mini-workspace with its own tabs: timeline, tasks, documents, parties, communication, and notes.",
    features: [
      { icon: "deals", term: "Transaction", what: "One property, one escrow, one side (buyer or seller). Its header shows the stage, close-of-escrow countdown, price, and any risks.", can: ["Track a deal through its stages", "See the next contractual deadline", "Open everything related to it in one place"] },
      { icon: "calendar", term: "Timeline & deadlines", what: "The contractual dates Terra computed from the contract — inspection, loan and appraisal contingencies, close of escrow. Fixed dates you schedule work around.", can: ["See every deadline in order", "Tell fixed contract dates from flexible work", "Build the timeline once key fields are confirmed"] },
      { icon: "check", term: "Tasks", what: "The work items on a deal — yours and ones assigned to a party. Each moves through not-started → in-progress → done.", can: ["Check items off inline", "Assign a task to a party", "Set a due date and priority"] },
      { icon: "doc", term: "Documents", what: "Everything filed against the deal — the purchase agreement, disclosures, appraisal, escrow instructions. Terra reads them and extracts key fields.", can: ["Upload and open documents", "Review AI-extracted fields", "See exceptions like a missing disclosure or a price mismatch"] },
      { icon: "users", term: "Parties", what: "Everyone involved — buyer, seller, both agents, escrow, lender, inspectors, appraiser. Each can be invited to their own scoped workspace.", can: ["See the full cast of the deal", "Invite a party to their own view", "Track who still owes you something"] },
      { icon: "mail", term: "Communication", what: "The deal's message history and drafts. Terra can prepare a draft, but nothing ever sends without your explicit approval.", can: ["Review and approve drafts", "See what's awaiting a reply", "Keep internal notes separate from outbound"] },
      { icon: "pin", term: "Sticky notes", what: "Quick notes you jot on a deal, like paper stickies on a desk. Terra reads them and suggests to-dos you can accept.", can: ["Jot anything, anytime", "Let Terra turn a note into a task", "Keep context that doesn't fit a field"] },
    ],
  },
  {
    id: "cross",
    title: "Across all your deals",
    blurb: "Some surfaces pull work together from every transaction so nothing slips between deals.",
    features: [
      { icon: "calendar", term: "Calendar", what: "Every contractual deadline and your scheduled work in one grid. Drag unscheduled work onto a day, or let auto-schedule place it around fixed dates.", can: ["See all deadlines at once", "Drag work onto a day", "Preview an auto-schedule before applying it"] },
      { icon: "inbox", term: "Deals & Inbox", what: "The pipeline board of active deals plus incoming documents waiting to be filed to the right transaction.", can: ["Scan the pipeline by stage", "Confirm an inbound document into a deal", "Open any deal"] },
      { icon: "board", term: "My quarter", what: "Your personal scorecard — deals closed, on-time rate, cycle time, and how this quarter compares to the last. Visible only to you.", can: ["See how you're trending", "Spot your slowest recurring task", "Review the quarter at a glance"] },
    ],
  },
  {
    id: "help",
    title: "AI, help & safety",
    blurb:
      "Terra prepares work; you stay in control. Every consequential AI action shows what it found, why, and its source — and waits for your review. Nothing sends or changes silently.",
    features: [
      { icon: "sparkle", term: "Recommendations", what: "Source-backed suggestions in the right rail — a risk flag, a document mismatch, a follow-up. Each has Review, Approve, and Dismiss.", can: ["See the evidence behind every suggestion", "Approve, edit, or dismiss", "Undo where possible"] },
      { icon: "shield", term: "Help & support", what: "Report a problem, check system status, and see any errors Terra captured automatically. If something breaks, your work is saved and the issue is logged for engineering.", can: ["Report a problem with context attached", "See auto-captured error references", "Reach support fast"] },
    ],
  },
];

const STEPS = [
  { icon: "home" as IconName, title: "Welcome to Terra", body: "This is your transaction workspace — everything you need to run a deal from contract to close, in one place. Here's a 60-second tour." },
  { icon: "deals" as IconName, title: "Navigate on the left", body: "Home shows what needs attention today. Transactions, Tasks, Calendar, Documents and Parties pull work together across every deal you're running." },
  { icon: "doc" as IconName, title: "Each deal is its own workspace", body: "Open a transaction to get its timeline, tasks, documents, parties, communication and sticky notes — all connected, so a deadline knows its document and a task knows its party." },
  { icon: "sparkle" as IconName, title: "Terra prepares, you approve", body: "Terra reads your documents and notes and suggests next steps with the evidence attached. Nothing sends or changes without your tap — you're always in control." },
  { icon: "search" as IconName, title: "Ask anything with ⌘K", body: "Press ⌘K to search a deal or ask a plain-English question. You can reopen this guide any time from Help in the sidebar." },
];

/** First-run walkthrough. Renders nothing once dismissed; caller controls mount. */
export function GuideModal({ onClose, onOpenFull }: { onClose: () => void; onOpenFull: () => void }) {
  const [i, setI] = useState(0);
  const step = STEPS[i];
  const last = i === STEPS.length - 1;
  function done() {
    markGuideSeen();
    onClose();
  }
  return (
    <div className="gd-scrim" role="dialog" aria-modal="true" aria-label="Welcome to Terra">
      <div className="gd-modal">
        <div className="gd-contour" aria-hidden><ContourLines /></div>
        <div className="gd-modal-body">
          <div className="gd-step-ic"><Icon name={step.icon} size={22} /></div>
          <div className="gd-dots" aria-hidden>
            {STEPS.map((_, n) => (
              <span key={n} className={`gd-dot ${n === i ? "on" : ""}`} />
            ))}
          </div>
          <h2>{step.title}</h2>
          <p>{step.body}</p>
          <div className="gd-actions">
            <button className="gd-skip" onClick={done}>Skip tour</button>
            <div className="gd-nav">
              {i > 0 && <button className="kbtn" onClick={() => setI(i - 1)}>Back</button>}
              {!last && <button className="kbtn pri" onClick={() => setI(i + 1)}>Next</button>}
              {last && (
                <button className="kbtn pri" onClick={() => { markGuideSeen(); onOpenFull(); }}>
                  Explore the full guide
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** The always-available reference manual (a normal page). */
export function GuidePage() {
  return (
    <div className="gd-page">
      <div className="gd-hero">
        <div className="gd-hero-ic"><Icon name="clipboard" size={20} /></div>
        <div>
          <h1>How Terra works</h1>
          <p className="muted">
            A plain-English guide to every part of your workspace — what each thing is, and what you can do with it.
          </p>
        </div>
      </div>

      <nav className="gd-toc" aria-label="Guide sections">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#gd-${s.id}`} className="gd-toc-link">{s.title}</a>
        ))}
      </nav>

      {SECTIONS.map((s) => (
        <section key={s.id} id={`gd-${s.id}`} className="gd-section">
          <h2>{s.title}</h2>
          <p className="gd-blurb">{s.blurb}</p>
          <div className="gd-features">
            {s.features.map((f) => (
              <div key={f.term} className="gd-feature">
                <div className="gd-feat-ic"><Icon name={f.icon} size={18} /></div>
                <div className="gd-feat-main">
                  <h3>{f.term}</h3>
                  <p>{f.what}</p>
                  <ul className="gd-can">
                    {f.can.map((c, n) => (
                      <li key={n}><Icon name="check" size={13} /> <span>{c}</span></li>
                    ))}
                  </ul>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      <div className="gd-foot">
        <Icon name="shield" size={15} />
        <span>
          Terra never sends a message or changes a deal without your approval. Stuck? Open <b>Help &amp; support</b> from
          the sidebar to reach us or report a problem.
        </span>
      </div>
    </div>
  );
}

function ContourLines() {
  return (
    <svg viewBox="0 0 400 200" fill="none" stroke="currentColor" strokeWidth={1} preserveAspectRatio="none">
      {Array.from({ length: 7 }, (_, i) => (
        <path key={i} d={`M-20 ${40 + i * 26}C80 ${10 + i * 26} 160 ${80 + i * 26} 260 ${50 + i * 26} 360 ${20 + i * 26} 420 ${70 + i * 26} 460 ${40 + i * 26}`} opacity={0.5 - i * 0.04} />
      ))}
    </svg>
  );
}
