import { useState } from "react";
import { defineTerm } from "./caLibrary";

/** A jargon term with a dotted underline; tapping reveals a one-sentence, plain-
 *  language definition inline. The single feature that most replaces the agent.
 *  Keyboard-accessible; if the term isn't in the library it renders as plain text. */
export function Define({ children }: { children: string }) {
  const [open, setOpen] = useState(false);
  const def = defineTerm(children);
  if (!def) return <>{children}</>;
  return (
    <span className="bw-define">
      <button
        type="button"
        className="bw-term"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {children}
      </button>
      {open && <span className="bw-def" role="note">{def}</span>}
    </span>
  );
}
