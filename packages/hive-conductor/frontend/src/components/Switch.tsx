/** A native button exposed as a switch, drawn with the existing `.toggle` style. */
export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`toggle${checked ? " on" : ""}`}
      onClick={() => onChange(!checked)}
      // Inline background: the global `button:hover` rule outranks `.toggle.on`.
      style={{ border: "none", padding: 0, boxShadow: "none", transform: "none", background: checked ? "var(--accent)" : "var(--rule)" }}
    />
  );
}
