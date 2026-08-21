import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../lib/api";

type ChecklistItem = {
  id: string;
  title: string;
  description: string;
  link_label: string;
  link_href: string;
  external_help?: string;
  category?: string;
  context?: string;
  status: "incomplete" | "dismissed";
  dismissed_at?: string;
  expires_at?: string;
  seconds_until_expiry?: number;
};

type ChecklistResponse = {
  items: ChecklistItem[];
  dismiss_ttl_days: number;
  generated_at: string;
};

const POLL_INTERVAL_MS = 30_000;
const TICK_INTERVAL_MS = 1_000;

/**
 * Strip the Vite BASE_URL prefix from an absolute path so React Router's
 * <Link to=...> doesn't double-prepend the basename. The backend emits
 * `/pm/credentials` for clarity, but the router (basename="/pm") expects
 * the path RELATIVE to the basename, so we want `/credentials`.
 */
function stripBasename(href: string): string {
  if (!href || href.startsWith("http")) return href;
  const base = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");
  if (base && href.startsWith(base + "/")) {
    return href.slice(base.length);
  }
  if (base && href === base) {
    return "/";
  }
  return href;
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "expiring…";
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  const secs = seconds % 60;
  if (days > 0) return `${days}d ${hours}h until removed`;
  if (hours > 0) return `${hours}h ${minutes}m until removed`;
  if (minutes > 0) return `${minutes}m ${secs}s until removed`;
  return `${secs}s until removed`;
}

const cardStyle: CSSProperties = {
  border: "1.3px solid var(--rule)",
  borderRadius: 6,
  padding: 14,
  marginBottom: 16,
  background: "var(--paper)",
};

const headerRow: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 12,
};

const itemRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "20px 1fr auto",
  gap: 10,
  padding: "10px 0",
  borderTop: "1px dashed var(--rule)",
  alignItems: "start",
};

const titleStyle: CSSProperties = {
  fontFamily: "var(--hand)",
  fontSize: 14,
  fontWeight: 600,
  lineHeight: 1.3,
};

const descStyle: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 10,
  color: "var(--pencil)",
  marginTop: 3,
  lineHeight: 1.45,
};

const linkBtnStyle: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  padding: "3px 8px",
  textDecoration: "none",
  whiteSpace: "nowrap",
};

const countdownStyle: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  color: "var(--accent)",
  marginTop: 4,
};

export function SetupChecklist() {
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    try {
      const data = await apiGet<ChecklistResponse>("/v1/setup-checklist");
      setItems(data.items ?? []);
    } catch {
      // If the user isn't authenticated yet, hide the panel entirely.
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const reload = setInterval(load, POLL_INTERVAL_MS);
    const tick = setInterval(() => setNow(Date.now()), TICK_INTERVAL_MS);
    return () => {
      clearInterval(reload);
      clearInterval(tick);
    };
  }, [load]);

  async function handleToggle(item: ChecklistItem) {
    const path =
      item.status === "dismissed"
        ? `/v1/setup-checklist/${item.id}/undismiss`
        : `/v1/setup-checklist/${item.id}/dismiss`;
    try {
      await apiPost(path);
    } catch {
      // ignore — load() will reconcile state
    }
    load();
  }

  if (loading || items.length === 0) {
    return null;
  }

  const incompleteCount = items.filter((i) => i.status === "incomplete").length;
  const dismissedCount = items.filter((i) => i.status === "dismissed").length;

  return (
    <div className="card" style={cardStyle}>
      <div style={headerRow}>
        <div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>
            SETUP CHECKLIST
          </div>
          <div style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600 }}>
            {incompleteCount} thing{incompleteCount === 1 ? "" : "s"} left to do
            {dismissedCount > 0 && (
              <span style={{ fontSize: 12, color: "var(--pencil)", marginLeft: 8 }}>
                ({dismissedCount} pending removal)
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => setCollapsed((c) => !c)}
          style={{ fontFamily: "var(--mono)", fontSize: 9, padding: "3px 8px" }}
        >
          {collapsed ? "show" : "hide"}
        </button>
      </div>

      {!collapsed &&
        items.map((item) => {
          const checked = item.status === "dismissed";
          // Recompute remaining seconds locally so the countdown ticks each second
          // without hitting the API.
          let remaining = item.seconds_until_expiry ?? 0;
          if (item.expires_at) {
            const expMs = Date.parse(item.expires_at);
            if (!Number.isNaN(expMs)) {
              remaining = Math.max(0, Math.floor((expMs - now) / 1000));
            }
          }
          return (
            <div key={item.id} style={itemRow}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => handleToggle(item)}
                style={{ marginTop: 4, cursor: "pointer" }}
                title={
                  checked
                    ? "Uncheck to keep the reminder visible"
                    : "Check to dismiss for 7 days"
                }
              />
              <div>
                <div style={{ ...titleStyle, textDecoration: checked ? "line-through" : "none", color: checked ? "var(--pencil)" : "var(--ink)" }}>
                  {item.title}
                </div>
                <div style={descStyle}>{item.description}</div>
                {item.context && (
                  <div style={{ ...descStyle, fontStyle: "italic", marginTop: 2 }}>
                    {item.context}
                  </div>
                )}
                {checked && (
                  <div style={countdownStyle}>
                    ⏳ {formatCountdown(remaining)} — uncheck to keep this reminder
                  </div>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <Link to={stripBasename(item.link_href)} className="btn" style={linkBtnStyle}>
                  {item.link_label} →
                </Link>
                {item.external_help && (
                  <a
                    href={item.external_help}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="btn"
                    style={{ ...linkBtnStyle, opacity: 0.8 }}
                  >
                    How to get one ↗
                  </a>
                )}
              </div>
            </div>
          );
        })}
    </div>
  );
}
