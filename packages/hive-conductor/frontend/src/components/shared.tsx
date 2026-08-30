import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  // Aliased: the un-prefixed name would shadow the DOM `KeyboardEvent` this
  // file already uses for a window-level listener.
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

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

type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
  /** Announced with the title. Give a dialog whose whole content is one
   *  sentence — a confirmation, a warning — its sentence here, so a screen
   *  reader reads it on open rather than only when focus reaches it. */
  description?: string;
  /** Whether Escape and a backdrop click may close this dialog. Set false for
   *  a dialog holding unsaved or destructive work, where a stray Escape would
   *  discard it with no confirmation and no undo (#371). The close button is
   *  unaffected: a dialog with no way out is worse than a dismissible one. */
  dismissible?: boolean;
};

/**
 * A real `<dialog>`, opened with `showModal()` (#371).
 *
 * The previous implementation was two nested `<div>`s. It had no `role`, no
 * `aria-modal` and no accessible name, so assistive technology saw a stack of
 * generic containers appear; focus stayed wherever the invoking button left
 * it, Tab walked straight out into the page behind, and the background stayed
 * in the tab order and in the accessibility tree. Escape closed it, which was
 * the only dialog behaviour it had.
 *
 * Rebuilding those by hand means a focus trap, an inert background, top-layer
 * stacking for nested dialogs and focus restoration — four things the platform
 * already does, each with its own edge cases. `showModal()` gives all four,
 * and gives them to every consumer at once, which is what this issue's
 * definition of done asks for.
 *
 * Two things are still ours. The `cancel` event is always prevented, so the
 * browser never closes the dialog behind React's back and leaves `open` true
 * with nothing on screen; the close travels through `onClose` like every other
 * close. And focus restoration is done explicitly rather than relied on,
 * because a dialog that unmounts its invoker has nothing for the browser to
 * restore to and the caller is better placed to notice.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  wide,
  description,
  dismissible = true,
}: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const invoker = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      invoker.current = document.activeElement as HTMLElement | null;
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !open) return;
    // `cancel` fires for Escape. Preventing it unconditionally keeps the DOM
    // and React's `open` in step; whether the dialog then closes is the
    // `dismissible` decision, made in one place.
    const onCancel = (event: Event) => {
      event.preventDefault();
      if (dismissible) onClose();
    };
    dialog.addEventListener("cancel", onCancel);
    return () => dialog.removeEventListener("cancel", onCancel);
  }, [open, dismissible, onClose]);

  useEffect(() => {
    if (open) return;
    const previous = invoker.current;
    invoker.current = null;
    if (previous?.isConnected) previous.focus();
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      className="modal-dialog"
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      // The dialog element *is* the panel, so a click whose target is the
      // element itself landed on the backdrop around it. Comparing targets
      // rather than stopping propagation inside also fixes a drag that starts
      // in a text field and ends outside closing the dialog.
      onClick={(e) => { if (dismissible && e.target === dialogRef.current) onClose(); }}
      style={{ maxWidth: wide ? 640 : 420 }}
    >
      {open ? (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1.3px solid var(--rule)" }}>
            <h2 id={titleId} style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 700, margin: 0 }}>{title}</h2>
            <button onClick={onClose} aria-label={`Close ${title}`} style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "var(--pencil)", lineHeight: 1 }}>✕</button>
          </div>
          <div style={{ padding: 16 }}>
            {description ? (
              <div id={descriptionId} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink)", marginBottom: 16 }}>{description}</div>
            ) : null}
            {children}
          </div>
        </>
      ) : null}
    </dialog>
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

/* ── Credential fields (#375) ────────────────────────────────── */

/**
 * A labelled field, with the label associated rather than adjacent.
 *
 * Every credential surface in this app named its inputs with placeholder text.
 * A placeholder is not an accessible name: it disappears the moment there is a
 * value, so a screen-reader user who tabs back to a half-filled form is told
 * nothing, and it can change with state — the LLM key field said "API key" or
 * "key stored — replace?" depending on the server's answer, so the field's
 * *name* changed under the user. The setup wizard had two fields whose whole
 * name was "password", one for the admin account and one for the daily user,
 * indistinguishable to anything that cannot see the layout.
 *
 * So the name comes from a real `<label htmlFor>` that stays on screen, and
 * everything else a user needs — the hint, the error, whether a secret is
 * already stored — is associated through `aria-describedby` instead of being
 * squeezed into the name.
 */
export type FieldProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Standing help. Announced with the field, not instead of its name. */
  hint?: string;
  /** Set when this field is why the form failed; sets `aria-invalid` too. */
  error?: string;
  required?: boolean;
  autoComplete?: string;
  autoFocus?: boolean;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  style?: CSSProperties;
  onKeyDown?: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
};

const FIELD_LABEL: CSSProperties = {
  display: "block",
  fontFamily: "var(--mono)",
  fontSize: 9,
  color: "var(--pencil)",
  marginBottom: 3,
};

const FIELD_NOTE: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  color: "var(--pencil)",
  marginTop: 3,
};

function useFieldIds(hint?: string, error?: string) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return { id, hintId, errorId, describedBy };
}

function FieldNotes({
  hintId,
  hint,
  errorId,
  error,
}: {
  hintId?: string;
  hint?: string;
  errorId?: string;
  error?: string;
}) {
  return (
    <>
      {hint ? <div id={hintId} style={FIELD_NOTE}>{hint}</div> : null}
      {error ? (
        // `role="alert"` so a failure that appears after submit is announced.
        // Without it the message is on screen and silent, which is the state a
        // sighted user never experiences and every other user always does.
        <div id={errorId} role="alert" style={{ ...FIELD_NOTE, color: "var(--danger)" }}>
          {error}
        </div>
      ) : null}
    </>
  );
}

export function TextField({
  label,
  value,
  onChange,
  hint,
  error,
  required,
  autoComplete,
  autoFocus,
  placeholder,
  disabled,
  className = "input-field",
  style,
  onKeyDown,
}: FieldProps) {
  const { id, hintId, errorId, describedBy } = useFieldIds(hint, error);
  return (
    <div style={style}>
      <label htmlFor={id} style={FIELD_LABEL}>{label}</label>
      <input
        id={id}
        className={className}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        required={required}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        placeholder={placeholder}
        disabled={disabled}
      />
      <FieldNotes hintId={hintId} hint={hint} errorId={errorId} error={error} />
    </div>
  );
}

export type SecretFieldProps = FieldProps & {
  /**
   * Whether the server already holds a secret for this field. Announced as a
   * description — never folded into the label, and never showing any part of
   * the stored value, which the client does not have and must not display.
   */
  stored?: boolean;
  storedNote?: string;
};

export function SecretField({
  label,
  value,
  onChange,
  hint,
  error,
  required,
  autoComplete = "off",
  autoFocus,
  placeholder,
  disabled,
  className = "input-field",
  style,
  onKeyDown,
  stored,
  storedNote = "A secret is already stored. Entering a new one replaces it.",
}: SecretFieldProps) {
  const [revealed, setRevealed] = useState(false);
  const { id, hintId, errorId } = useFieldIds(hint, error);
  const storedId = stored ? `${id}-stored` : undefined;
  const describedBy = [storedId, hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div style={style}>
      <label htmlFor={id} style={FIELD_LABEL}>{label}</label>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          id={id}
          className={className}
          // Revealing changes the input's `type`, which is what actually shows
          // the characters. `autoComplete` is passed through unchanged either
          // way: a password manager keys off it, and a field that silently
          // stopped being a password field would stop being offered a
          // credential.
          type={revealed ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          required={required}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          placeholder={placeholder}
          disabled={disabled}
          style={{ flex: 1, minWidth: 0 }}
        />
        <button
          type="button"
          onClick={() => setRevealed((shown) => !shown)}
          // Named for the field, because a page with several secret fields
          // otherwise has several buttons all called "Show".
          //
          // A changing action name and no `aria-pressed`, which is one of the
          // two coherent choices (raised in review of #375). The first version
          // had both: the name went "Show Password" -> "Hide Password" *and*
          // `aria-pressed` flipped, which announces as "Hide Password,
          // pressed" and leaves the listener to work out which half is the
          // state. The other choice -- a fixed name plus `aria-pressed` --
          // would make the accessible name disagree with the visible "hide",
          // which is its own failure (WCAG 2.5.3, label in name).
          aria-label={`${revealed ? "Hide" : "Show"} ${label}`}
          disabled={disabled}
          style={{
            background: "none", border: "1.3px solid var(--rule)", borderRadius: 4,
            padding: "3px 8px", cursor: "pointer", color: "var(--pencil)",
            fontFamily: "var(--mono)", fontSize: 9, flexShrink: 0,
          }}
        >
          {revealed ? "hide" : "show"}
        </button>
      </div>
      {stored ? <div id={storedId} style={FIELD_NOTE}>{storedNote}</div> : null}
      <FieldNotes hintId={hintId} hint={hint} errorId={errorId} error={error} />
    </div>
  );
}

/* ── ConfirmDialog ───────────────────────────────────────────── */

export function ConfirmDialog({ open, onClose, onConfirm, title, message }: { open: boolean; onClose: () => void; onConfirm: () => void; title: string; message: string }) {
  return (
    // The message is the dialog's description rather than loose content: a
    // confirmation whose whole point is the sentence should have that sentence
    // read out when the dialog opens, not only if focus happens to reach it.
    <Modal open={open} onClose={onClose} title={title} description={message}>
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
