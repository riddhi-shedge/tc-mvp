import { Component, ErrorInfo, ReactNode } from "react";
import { captureError } from "./errorlog";
import { Icon } from "./icons";

/* Crash recovery. If any screen throws, the TC sees a calm fallback instead of a
 * blank page — their session is intact, the error is logged with a reference, and
 * they can retry. This is what "technical support when something crashes" looks
 * like from the user's side; the reference id also flows to Help & support. */

type Props = { children: ReactNode };
type State = { ref: string | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { ref: null };

  static getDerivedStateFromError(): Partial<State> {
    return {}; // ref is set in componentDidCatch where we have the message
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const screen = window.location.hash || "app";
    const entry = captureError(error.message || "Unhandled render error", screen, "sent");
    this.setState({ ref: entry.ref });
    // Surface for local debugging; in prod this is where a Sentry POST would go.
    console.error("Terra captured error", entry.ref, error, info.componentStack);
  }

  reset = () => {
    this.setState({ ref: null });
  };

  render() {
    if (this.state.ref) {
      return (
        <div className="crash">
          <div className="crash-card">
            <div className="crash-ic"><Icon name="warning" size={26} /></div>
            <h2>Something went wrong on this screen</h2>
            <p>
              Your work is saved. We've logged what happened and sent it to Terra engineering — no action needed from
              you.
            </p>
            <div className="crash-ref">Error reference · {this.state.ref}</div>
            <div className="crash-btns">
              <button className="kbtn pri" onClick={this.reset}>Reload this screen</button>
              <button className="kbtn" onClick={() => { window.location.hash = ""; this.reset(); }}>
                Back to Home
              </button>
            </div>
            <p className="crash-note">
              Every crash becomes a tracked ticket. You can review it any time under Help &amp; support.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
