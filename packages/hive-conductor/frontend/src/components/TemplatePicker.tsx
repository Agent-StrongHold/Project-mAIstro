import { useEffect, useState } from "react";

type Template = { id: string; name: string; description: string; widget_count: number };

export function TemplatePicker({ onSelect, onClose }: { onSelect: (id: string) => void; onClose: () => void }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/v1/dashboard/demos", { credentials: "same-origin" })
      .then(r => r.json())
      .then(d => setTemplates(Array.isArray(d) ? d : []))
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <h2 style={{ margin: "0 0 4px", fontSize: "1rem", fontWeight: 700 }}>Load Template</h2>
        <p style={{ margin: "0 0 16px", fontSize: "0.75rem", color: "var(--pencil)" }}>Pick a curated dashboard layout. You can customize it after loading.</p>

        {loading && <div className="skeleton skeleton-card" />}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {templates.map(t => (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderRadius: 8, border: "1px solid var(--rule)", background: "var(--paper-2)", cursor: "pointer", textAlign: "left", transition: "border-color 0.12s" }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--accent)")}
              onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--rule)")}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--ink)" }}>{t.name}</div>
                <div style={{ fontSize: "0.68rem", color: "var(--pencil)", marginTop: 2 }}>{t.description}</div>
              </div>
              <span className="hex-badge">{t.widget_count} widgets</span>
            </button>
          ))}
          {!loading && templates.length === 0 && (
            <div className="empty-state"><span className="empty-state-text">No templates available</span></div>
          )}
        </div>

        <button onClick={onClose} className="btn-secondary" style={{ marginTop: 16, width: "100%" }}>Cancel</button>
      </div>
    </div>
  );
}
