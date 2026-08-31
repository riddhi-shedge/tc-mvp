import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { toast } from "../lib/ui";
import { Icon } from "../lib/icons";

/* Sticky notes on a deal — part of the System of Record (P3). Notes live in the
 * SOR (deal_notes), sync across devices, feed the deal assistant's grounded
 * context, and are never shown to parties. Any notes a browser still holds from
 * the old localStorage era are migrated up once, then the local copy is cleared. */

type Note = { id: string; body: string; color: string; created_at?: string };
const COLORS = ["y", "b", "p", "g"];
const lsKey = (dealId: string) => `tc_notes_${dealId}`;

/** Old-format localStorage notes worth migrating (skip the demo seeds). */
function localLeftovers(dealId: string): { text: string; color: string }[] {
  try {
    const raw = localStorage.getItem(lsKey(dealId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { id: string; text: string; color: string }[];
    return parsed.filter((n) => n.text?.trim() && !n.id.startsWith("seed"));
  } catch {
    return [];
  }
}

// Lightweight, transparent heuristic standing in for the grounded assistant:
// scan note text for cues and propose a task title.
function suggestFrom(notes: Note[]): { noteId: string; title: string; because: string }[] {
  const out: { noteId: string; title: string; because: string }[] = [];
  for (const n of notes) {
    const t = n.body.toLowerCase();
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
  const [notes, setNotes] = useState<Note[]>([]);
  const [available, setAvailable] = useState(true);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ available: boolean; notes: Note[] }>(`/transactions/${id}/notes`);
      setAvailable(r.available);
      if (!r.available) return;
      // One-time migration: push any real localStorage notes into the SOR.
      const leftovers = localLeftovers(id);
      if (leftovers.length > 0) {
        for (const n of leftovers) {
          await api.post(`/transactions/${id}/notes`, { body: n.text, color: n.color || "y" });
        }
        localStorage.removeItem(lsKey(id));
        toast(`Moved ${leftovers.length} note${leftovers.length > 1 ? "s" : ""} from this browser into the deal record`);
        const again = await api.get<{ available: boolean; notes: Note[] }>(`/transactions/${id}/notes`);
        setNotes(again.notes);
        return;
      }
      setNotes(r.notes);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Couldn't load notes", { error: true });
    }
  }, [id]);
  useEffect(() => { void load(); }, [load]);

  const suggestions = useMemo(
    () => suggestFrom(notes).filter((s, i, arr) => arr.findIndex((x) => x.title === s.title) === i && !dismissed.has(s.title)),
    [notes, dismissed],
  );

  async function addNote() {
    const body = draft.trim();
    if (!body) return;
    try {
      await api.post(`/transactions/${id}/notes`, { body, color: COLORS[notes.length % COLORS.length] });
      setDraft("");
      setAdding(false);
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Couldn't save the note", { error: true });
    }
  }
  async function removeNote(nid: string) {
    try {
      await api.del(`/transactions/${id}/notes/${nid}`);
      setNotes((n) => n.filter((x) => x.id !== nid));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Couldn't delete the note", { error: true });
    }
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
        <span className="badge" style={{ marginLeft: "auto" }}>part of the deal record · only you</span>
      </div>

      {!available && (
        <div className="hm-empty" style={{ textAlign: "left" }}>
          Notes need the <code>deal_notes</code> migration applied to the database. Until then, nothing typed here can be saved.
        </div>
      )}

      <div className="nt-board">
        {notes.map((n) => (
          <div key={n.id} className={`nt-sticky ${n.color}`}>
            <span className="nt-pin" />
            <button className="nt-del" aria-label="Delete note" onClick={() => void removeNote(n.id)}><Icon name="x" size={12} /></button>
            <div className="nt-text">{n.body}</div>
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
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void addNote();
                if (e.key === "Escape") { setAdding(false); setDraft(""); }
              }}
            />
            <div className="nt-edit-actions">
              <button className="mini-btn" onClick={() => { setAdding(false); setDraft(""); }}>Cancel</button>
              <button className="mini-btn pri" onClick={() => void addNote()}>Add</button>
            </div>
          </div>
        ) : (
          <button className="nt-sticky add" disabled={!available} onClick={() => setAdding(true)}>
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
              <button className="mini-btn pri" onClick={() => void addTask(s.title)}>Add task</button>
              <button className="mini-btn" onClick={() => setDismissed((d) => new Set(d).add(s.title))}>Dismiss</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
