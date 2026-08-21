import { useState, useEffect } from "react";
import BookWizard from "./components/BookWizard";
import BookWorkspace from "./components/BookWorkspace";
import { listSaved, clearState, clearAll } from "./lib/persistence";

export default function App() {
  const [bookSpec, setBookSpec] = useState(null);
  const [savedBooks, setSavedBooks] = useState([]);
  const [view, setView] = useState("loading");

  useEffect(() => {
    (async () => {
      try {
        const list = await listSaved();
        setSavedBooks(list);
        if (list.length === 1) {
          const b = list[0];
          setBookSpec({ ...(b.bookSpec || {}), _storageKey: b.key });
          setView("workspace");
        } else if (list.length > 1) {
          setView("landing");
        } else {
          setView("wizard");
        }
      } catch {
        setView("wizard");
      }
    })();
  }, []);

  const refreshSaved = async () => {
    try { setSavedBooks(await listSaved()); } catch { /* a stale saved-books list is better than a crash on refresh */ }
  };

  const resumeBook = (entry) => {
    setBookSpec({ ...(entry.bookSpec || {}), _storageKey: entry.key });
    setView("workspace");
  };

  const startNew = () => setView("wizard");

  const resetToLanding = async () => {
    setBookSpec(null);
    await refreshSaved();
    setView(savedBooks.length > 0 ? "landing" : "wizard");
  };

  // ── Loading ──────────────────────────────────────────────────────────────
  if (view === "loading") {
    return (
      <div className="app-shell">
        <div className="topbar"><span className="logo">CANVAS STUDIO</span><div className="spacer" /></div>
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ color: "var(--text-dim)", fontSize: 13 }}>Loading...</div>
        </div>
      </div>
    );
  }

  // ── Landing: Saved Books Picker ──────────────────────────────────────────
  if (view === "landing" && !bookSpec) {
    return (
      <div className="app-shell">
        <div className="topbar"><span className="logo">CANVAS STUDIO</span><div className="spacer" /><button onClick={startNew}>New Book</button></div>
        <div style={{ flex: 1, overflow: "auto", padding: 32, maxWidth: 800, margin: "0 auto", width: "100%" }}>
          <h2 style={{ color: "var(--text)", fontSize: 20, marginBottom: 4 }}>Your Books</h2>
          <p style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 24 }}>Pick up where you left off, or start something new.</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {savedBooks.map((b) => (
              <div key={b.key} style={{ display: "flex", alignItems: "center", gap: 16, background: "var(--ink-1)", padding: "14px 18px", borderRadius: 6, border: "1px solid var(--border)", cursor: "pointer" }} onClick={() => resumeBook(b)}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>{b.bookSpec?.title || b.title}</div>
                  <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>
                    Step: {(b.step || "").replace(/([A-Z])/g, " $1").trim()}
                    {b.savedAt ? ` — ${new Date(b.savedAt).toLocaleString()}` : ""}
                  </div>
                </div>
                <button className="primary" style={{ fontSize: 12 }}>Resume</button>
                <button className="danger" style={{ fontSize: 12 }} onClick={async (e) => { e.stopPropagation(); await clearState(b.key); await refreshSaved(); if (savedBooks.length <= 1) setView("wizard"); }}>Delete</button>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16 }}>
            <button className="danger" onClick={async () => { await clearAll(); setSavedBooks([]); setView("wizard"); }}>Clear All Books</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Workspace ────────────────────────────────────────────────────────────
  if (bookSpec) {
    return (
      <div className="app-shell">
        <div className="topbar">
          <span className="logo">CANVAS STUDIO</span>
          <span className="breadcrumb">&gt; {bookSpec.title || bookSpec.premise?.slice(0, 40) + "..."}</span>
          <div className="spacer" />
          <button onClick={resetToLanding}>My Books</button>
        </div>
        <BookWorkspace bookSpec={bookSpec} onReset={resetToLanding} />
      </div>
    );
  }

  // ── Wizard ───────────────────────────────────────────────────────────────
  return (
    <div className="app-shell">
      <div className="topbar">
        <span className="logo">CANVAS STUDIO</span>
        <div className="spacer" />
        {savedBooks.length > 0 && <button onClick={() => setView("landing")}>My Books ({savedBooks.length})</button>}
      </div>
      <BookWizard onComplete={(spec) => { setBookSpec(spec); setView("workspace"); }} />
    </div>
  );
}
