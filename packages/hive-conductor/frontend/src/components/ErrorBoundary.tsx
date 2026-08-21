import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; fallback?: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error) { return { error }; }

  render() {
    if (this.state.error) {
      return this.props.fallback || (
        <div role="alert" className="card" style={{ margin: 24, padding: 24, background: "#fdecea", border: "1px solid #f44336" }}>
          <h2 style={{ fontFamily: "var(--hand)", color: "#b71c1c", margin: "0 0 8px" }}>Something went wrong</h2>
          <p style={{ fontFamily: "var(--mono)", fontSize: 12, color: "#333" }}>{this.state.error.message}</p>
          <button
            onClick={() => { this.setState({ error: null }); window.location.reload(); }}
            style={{ marginTop: 12, padding: "8px 16px", borderRadius: 6, border: "1px solid #b71c1c", background: "white", cursor: "pointer", fontFamily: "var(--hand)" }}
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
