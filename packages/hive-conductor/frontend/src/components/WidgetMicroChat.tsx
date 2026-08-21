import { useState, useRef, type KeyboardEvent } from "react";

type Props = {
  widgetId: string;
  widgetTitle: string;
  widgetConfig: Record<string, any>;
  widgetData?: any;
  editing: boolean;
  onSubmit: (context: { widgetId: string; widgetTitle: string; widgetConfig: Record<string, any>; widgetData?: any; text: string; mode: "ask" | "edit" }) => void;
};

export function WidgetMicroChat({ widgetId, widgetTitle, widgetConfig, widgetData, editing, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const [expanded, setExpanded] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    const text = value.trim();
    if (!text) return;
    onSubmit({ widgetId, widgetTitle, widgetConfig, widgetData, text, mode: editing ? "edit" : "ask" });
    setValue("");
    setExpanded(false);
  };

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Enter") submit();
    if (e.key === "Escape") { setValue(""); setExpanded(false); }
  };

  if (!expanded) {
    return (
      <button
        onClick={() => { setExpanded(true); setTimeout(() => inputRef.current?.focus(), 50); }}
        aria-label={editing ? "Refine this widget" : "Ask about this data"}
        title={editing ? "Refine this widget" : "Ask about this data"}
        style={{ background: "none", border: "none", cursor: "pointer", opacity: 0.4, fontSize: "0.65rem", padding: "4px 0", color: "var(--pencil)", transition: "opacity 0.15s" }}
        onMouseEnter={e => (e.currentTarget.style.opacity = "1")}
        onMouseLeave={e => (e.currentTarget.style.opacity = "0.4")}
      >
        {editing ? "✎ refine…" : "💬 ask…"}
      </button>
    );
  }

  return (
    <div style={{ display: "flex", gap: 4, marginTop: 6, borderTop: "1px solid var(--rule)", paddingTop: 6 }}>
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => { if (!value) setExpanded(false); }}
        placeholder={editing ? "Change this widget…" : "Ask about this data…"}
        maxLength={200}
        style={{ flex: 1, fontSize: "0.65rem", padding: "3px 6px", border: "1px solid var(--rule)", borderRadius: 4, background: "var(--paper)", color: "var(--ink)", outline: "none" }}
      />
      <button onClick={submit} disabled={!value.trim()} style={{ fontSize: "0.6rem", padding: "2px 8px", borderRadius: 4, border: "none", background: "var(--accent)", color: "#fff", cursor: "pointer", opacity: value.trim() ? 1 : 0.3 }}>
        →
      </button>
    </div>
  );
}
