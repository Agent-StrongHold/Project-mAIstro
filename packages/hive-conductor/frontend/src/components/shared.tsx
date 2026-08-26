import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export function PageHeader({ title, subtitle, actions, helpHref }: { title: string; subtitle?: string; actions?: ReactNode; helpHref?: string }) {
  return (
    <header className="page-header">
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <h1>{title}</h1>
        {helpHref && (
          <a
            href={helpHref}
            onClick={(e) => { e.preventDefault(); window.location.hash = ""; window.location.href = helpHref; }}
            style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              width: 20, height: 20, borderRadius: "50%",
              border: "1.3px solid var(--pencil)", color: "var(--pencil)",
              fontFamily: "var(--mono)", fontSize: 10, fontWeight: 700,
              textDecoration: "none", lineHeight: 1, flexShrink: 0,
            }}
            title="Learn more"
          >?</a>
        )}
      </div>
      {subtitle ? <div className="subtitle">{subtitle}</div> : null}
      {actions ? <div style={{ display: "flex", gap: 6 }}>{actions}</div> : null}
    </header>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`.trim()}>{children}</section>;
}

export function Hex({ children, variant = "" }: { children: ReactNode; variant?: "ok" | "danger" | "warn" | "purple" | "muted" | "accent" | "" }) {
  return <span className={`hex-badge${variant ? ` hex-badge-${variant}` : ""}`}>{children}</span>;
}

export function Bee({ role }: { role: "queen" | "worker" | "drone" | "scout" }) {
  const icons: Record<string, string> = {
    queen: "\uD83D\uDC1D",
    worker: "\uD83D\uDC1D",
    drone: "\uD83D\uDD0D",
    scout: "\uD83D\uDD0D",
  };
  return <span className={`bee-${role}`} style={{ fontSize: 18 }}>{icons[role]}</span>;
}

export function StatCard({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div className="stat-card" style={highlight ? { border: "1.3px solid var(--accent)" } : undefined}>
      <div className="label">{label}</div>
      <div className="value" style={highlight ? { color: "var(--accent)" } : undefined}>{value}</div>
    </div>
  );
}

/* ── Modal ───────────────────────────────────────────────────── */

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--paper)", color: "var(--ink)", borderRadius: 8,
          width: "100%", maxWidth: wide ? 640 : 420, maxHeight: "80vh",
          overflow: "auto", position: "relative", boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1.3px solid var(--rule)" }}>
          <div style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 700 }}>{title}</div>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "var(--pencil)", lineHeight: 1 }}>✕</button>
        </div>
        <div style={{ padding: 16 }}>{children}</div>
      </div>
    </div>
  );
}

/* ── Toast system ────────────────────────────────────────────── */

interface ToastItem { id: number; msg: string; type: string }

const ToastCtx = createContext<(msg: string, type?: "ok" | "error" | "warn") => void>(() => {});

export function useToast() {
  return useContext(ToastCtx);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);

  const addToast = useCallback((msg: string, type: "ok" | "error" | "warn" = "ok") => {
    const id = nextId.current++;
    setToasts((prev) => [...prev, { id, msg, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3000);
  }, []);

  const colorMap: Record<string, string> = { ok: "var(--ok)", error: "var(--danger)", warn: "var(--warn, #d4a017)" };

  return (
    <ToastCtx.Provider value={addToast}>
      {children}
      <div style={{ position: "fixed", bottom: 16, right: 16, zIndex: 2000, display: "flex", flexDirection: "column", gap: 6 }}>
        {toasts.map((t) => (
          <div key={t.id} style={{
            background: "var(--paper)", border: `1.3px solid ${colorMap[t.type] || colorMap.ok}`,
            borderLeftWidth: 4, borderRadius: 5, padding: "8px 14px",
            fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink)",
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
          }}>
            {t.msg}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ── Tabs ────────────────────────────────────────────────────── */

export function Tabs({ tabs, active, onChange }: { tabs: string[]; active: number; onChange: (i: number) => void }) {
  return (
    <div style={{ display: "flex", borderBottom: "1.3px solid var(--rule)", marginBottom: 12 }}>
      {tabs.map((tab, i) => (
        <button
          key={tab}
          onClick={() => onChange(i)}
          style={{
            background: "none", border: "none",
            borderBottom: i === active ? "2px solid var(--accent)" : "2px solid transparent",
            padding: "6px 14px", cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10,
            color: i === active ? "var(--ink)" : "var(--pencil)", fontWeight: i === active ? 600 : 400,
          }}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

/* ── EmptyState ──────────────────────────────────────────────── */

export function EmptyState({ icon, title, action, onAction }: { icon?: string; title: string; action?: string; onAction?: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "40px 20px", color: "var(--pencil)" }}>
      {icon && <div style={{ fontSize: 36, marginBottom: 12 }}>{icon}</div>}
      <div style={{ fontFamily: "var(--hand)", fontSize: 20, color: "var(--ink)", marginBottom: 16 }}>{title}</div>
      {action && onAction && (
        <button onClick={onAction} style={{
          background: "var(--accent)", color: "var(--paper)",
          border: "1.3px solid var(--accent)", borderRadius: 4,
          padding: "6px 16px", cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10,
        }}>
          {action}
        </button>
      )}
    </div>
  );
}

/* ── SearchInput ─────────────────────────────────────────────── */

export function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, background: "var(--paper-2)", border: "1.3px solid var(--ink)", borderRadius: 5, padding: "4px 8px" }}>
      <span style={{ fontSize: 13 }}>🔍</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder || "Search..."}
        style={{ background: "transparent", border: "none", outline: "none", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink)", width: "100%" }}
      />
    </div>
  );
}

/* ── ConfirmDialog ───────────────────────────────────────────── */

export function ConfirmDialog({ open, onClose, onConfirm, title, message }: { open: boolean; onClose: () => void; onConfirm: () => void; title: string; message: string }) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink)", marginBottom: 16 }}>{message}</div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={onClose} style={{ border: "1.3px solid var(--ink)", background: "var(--paper)", color: "var(--ink)", padding: "5px 14px", borderRadius: 4, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10 }}>Cancel</button>
        <button onClick={() => { onConfirm(); onClose(); }} style={{ border: "1.3px solid var(--danger, #c4452a)", background: "var(--danger, #c4452a)", color: "var(--paper)", padding: "5px 14px", borderRadius: 4, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10 }}>Confirm</button>
      </div>
    </Modal>
  );
}

/* ── Toggle ──────────────────────────────────────────────────── */

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink)" }}>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        style={{
          width: 28, height: 16, borderRadius: 8, border: "none", padding: 0,
          background: checked ? "var(--accent)" : "var(--rule)",
          position: "relative", cursor: "pointer", transition: "background 0.15s",
        }}
      >
        <span style={{
          position: "absolute", top: 2, width: 12, height: 12, borderRadius: "50%",
          background: "var(--paper)", border: "1px solid rgba(0,0,0,0.2)",
          left: checked ? 14 : 2, transition: "left 0.15s",
        }} />
      </button>
      {label}
    </label>
  );
}

/* ── TrustBadge ──────────────────────────────────────────────── */

export function TrustBadge({ tier }: { tier: "T0" | "T1" | "T2" | "T3" | "SKULL" }) {
  const palette: Record<string, { bg: string; fg: string }> = {
    T0: { bg: "rgba(90,154,74,0.18)", fg: "#4a7a3a" },
    T1: { bg: "rgba(212,160,23,0.15)", fg: "var(--honey-dark)" },
    T2: { bg: "rgba(91,143,179,0.18)", fg: "#3a6a9a" },
    T3: { bg: "rgba(107,93,73,0.12)", fg: "var(--pencil)" },
    SKULL: { bg: "rgba(196,69,42,0.18)", fg: "#c4452a" },
  };
  const c = palette[tier] || palette.T3;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      padding: "3px 10px", minWidth: 40, height: 24,
      fontFamily: "var(--mono)", fontSize: 8, fontWeight: 600,
      letterSpacing: "0.03em",
      clipPath: "polygon(10% 0%, 90% 0%, 100% 50%, 90% 100%, 10% 100%, 0% 50%)",
      background: c.bg, color: c.fg, textTransform: "uppercase",
    }}>
      {tier}
    </span>
  );
}

/* ── StatusDot ───────────────────────────────────────────────── */

const DOT_COLORS: Record<string, string> = {
  running: "var(--accent)", idle: "var(--pencil)", error: "#c4452a",
  busy: "var(--accent)", connected: "#5a9a4a", disconnected: "var(--pencil)", watching: "#5b8fb3",
};

export function StatusDot({ status, pulse }: { status: "running" | "idle" | "error" | "busy" | "connected" | "disconnected" | "watching"; pulse?: boolean }) {
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: "50%",
      background: DOT_COLORS[status] || "var(--pencil)",
      animation: pulse ? "hc-pulse 1.5s ease-in-out infinite" : "none",
    }} />
  );
}

/* ── LoadingSpinner ──────────────────────────────────────────── */

export function LoadingSpinner() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
      <div style={{
        width: 40, height: 40, border: "3px solid var(--rule)",
        borderTopColor: "var(--accent)", borderRadius: "50%",
        animation: "hc-spin 0.8s linear infinite",
      }} />
    </div>
  );
}
