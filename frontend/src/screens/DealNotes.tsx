import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

/* Sticky notes on a deal — the digital equivalent of paper stickies on a desk.
 * Notes persist per-deal in localStorage (no schema change needed); Terra reads
 * them and proposes to-dos. Accepting a suggestion creates a REAL task on the deal
 * via the existing endpoint, so the AI's read of your notes turns into real work. */

type Note = { id: string; text: string; color: string; at: string };
const COLORS = ["y", "b", "p", "g"];
const key = (dealId: string) => `tc_notes_${dealId}`;

function load(dealId: string): Note[] {
  try {
    const raw = localStorage.getItem(key(dealId));
    if (raw) return JSON.parse(raw) as Note[];
  } catch {
    /* ignore */
  }
  // Seed a couple so the feature reads clearly on first open.
  return [
    { id: "seed1", text: "Seller hinted they may want a 2-week rent-back after close — confirm with the agent.", color: "y", at: "" },
    { id: "seed2", text: "Buyer prefers e-sign only — no wet signatures.", color: "b", at: "" },
  ];
}
function save(dealId: string, notes: Note[]) {
  try {
    localStorage.setItem(key(dealId), JSON.stringify(notes));
  } catch {
    /* ignore */
  }
}

// Lightweight, transparent heuristic standing in for the grounded assistant:
// scan note text for cues and propose a task title. Real wiring would send the
// notes to the same assistant seam that drafts everything else.
function suggestFrom(notes: Note[]): { noteId: string; title: string; because: string }[] {
  const out: { noteId: string; title: string; because: string }[] = [];
  for (const n of notes) {
    const t = n.text.toLowerCase();
    if (t.includes("rent-back") || t.includes("rent back") || t.includes("possession")) {
      out.push({ noteId: n.id, title: "Draft Seller-in-Possession (rent-back) addendum for review", because: "your note about a rent-back" });
    }
    if (t.includes("apprais")) {
      out.push({ noteId: n.id, title: "Follow up on the appraisal report", because: "your note about the appraisal" });
    }
    if (t.includes("e-sign") || t.includes("esign") || t.includes("signature")) {
      out.push({ noteId: n.id, title: "Set signing preference to e-sign for this deal", because: "your note about signing" });
    }
    if (t.includes("hoa")) {
      out.push({ noteId: n.id, title: "Request HOA documents", because: "your note mentioning the HOA" });
    }
  }
  return out.slice(0, 3);
}

export function DealNotes({ id, onChanged }: { id: string; onChanged?: () => void }) {
  const [notes, setNotes] = useState<Note[]>(() => load(id));
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const suggestions = useMemo(
    () => suggestFrom(notes).filter((s, i, arr) => arr.findIndex((x) => x.title === s.title) === i && !dismissed.has(s.title)),
    [notes, dismissed],
  );

  function persist(next: Note[]) {
    setNotes(next);
    save(id, next);
  }
  function addNote() {
    const text = draft.trim();
    if (!text) return;
    const note: Note = { id: `n${Date.now()}`, text, color: COLORS[notes.length % COLORS.length], at: new Date().toISOString() };
    persist([...notes, note]);
    setDraft("");
    setAdding(false);
  }
  function removeNote(nid: string) {
    persist(notes.filter((n) => n.id !== nid));
  }
  async function addTask(title: string) {
    try {
      await api.post(`/transactions/${id}/tasks`, { title, priority: "normal" });
      toast("Added to Tasks on this deal");
      onChanged?.();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Couldn't add task", { error: true });
    }
  }

  return (
    <div className="card nt-card">
      <div className="card-h">
        <h2 style={{ margin: 0 }}><Icon name="pin" size={17} /> Notes on this deal</h2>
        <span className="badge" style={{ marginLeft: "auto" }}>only you &amp; your team</span>
      </div>

      <div className="nt-board">
        {notes.map((n) => (
          <div key={n.id} className={`nt-sticky ${n.color}`}>
            <span className="nt-pin" />
            <button className="nt-del" aria-label="Delete note" onClick={() => removeNote(n.id)}><Icon name="x" size={12} /></button>
            <div className="nt-text">{n.text}</div>
          </div>
        ))}

        {adding ? (
          <div className="nt-sticky y nt-editing">
            <textarea
              className="nt-input"
              autoFocus
              placeholder="Jot anything…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) addNote();
                if (e.key === "Escape") { setAdding(false); setDraft(""); }
              }}
            />
            <div className="nt-edit-actions">
              <button className="mini-btn" onClick={() => { setAdding(false); setDraft(""); }}>Cancel</button>
              <button className="mini-btn pri" onClick={addNote}>Add</button>
            </div>
          </div>
        ) : (
          <button className="nt-sticky add" onClick={() => setAdding(true)}>
            <Icon name="plus" size={18} /> Add a note
          </button>
        )}
      </div>

      {suggestions.length > 0 && (
        <div className="nt-ai">
          <div className="nt-ai-h">
            <Icon name="sparkle" size={14} /> Terra read your notes
            <span className="muted" style={{ marginLeft: "auto", fontSize: ".76rem" }}>{suggestions.length} suggestion{suggestions.length > 1 ? "s" : ""}</span>
          </div>
          {suggestions.map((s) => (
            <div key={s.title} className="nt-ai-row">
              <div className="nt-ai-t">
                {s.title}
                <small>from {s.because}</small>
              </div>
              <button className="mini-btn pri" onClick={() => addTask(s.title)}>Add task</button>
              <button className="mini-btn" onClick={() => setDismissed((d) => new Set(d).add(s.title))}>Dismiss</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
