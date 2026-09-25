import { Component, ErrorInfo, ReactNode } from "react";
import { captureError } from "./errorlog";
import { Icon } from "./icons";

/* Crash recovery. If any screen throws, the TC sees a calm fallback instead of a
 * blank page — their session is intact, the error is logged with a reference, and
 * they can retry. This is what "technical support when something crashes" looks
 * like from the user's side; the reference id also flows to Help & support. */

type Props = { children: ReactNode };
type State = { crashed: boolean; ref: string | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { crashed: false, ref: null };

  static getDerivedStateFromError(): Partial<State> {
    // Flip to the fallback IN the error render pass — waiting for
    // componentDidCatch would re-render the throwing children first.
    return { crashed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const screen = window.location.hash || "app";
    const entry = captureError(error.message || "Unhandled render error", screen, "sent");
    this.setState({ ref: entry.ref });
    console.error("Terra captured error", entry.ref, error, info.componentStack);
  }

  reset = () => {
    this.setState({ crashed: false, ref: null });
  };

  render() {
    if (this.state.crashed) {
      return (
        <div className="crash">
          <div className="crash-card">
            <div className="crash-ic"><Icon name="warning" size={26} /></div>
            <h2>Something went wrong on this screen</h2>
            <p>
              Your work is saved. The error was captured with a reference you can include
              when reporting it under Help &amp; support.
            </p>
            {this.state.ref && <div className="crash-ref">Error reference · {this.state.ref}</div>}
            <div className="crash-btns">
              <button className="kbtn pri" onClick={this.reset}>Reload this screen</button>
              <button className="kbtn" onClick={() => { window.location.hash = ""; this.reset(); }}>
                Back to Home
              </button>
            </div>
            <p className="crash-note">
              Captured errors from this session are listed under Help &amp; support.
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
