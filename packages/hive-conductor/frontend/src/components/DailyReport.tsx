import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../lib/api";

type JiraIssue = {
  key: string;
  summary: string;
  status: string;
  updated: string;
  url: string;
};

type JiraSection = {
  status: "ok" | "no_pat" | "auth_failed" | "error";
  detail?: string;
  credential_id?: string;
  help_url?: string;
  source?: string;
  count?: number;
  issues: JiraIssue[];
};

type AirtableRecord = { id: string; fields: Record<string, unknown> };
type AirtableSection = {
  status: "ok" | "no_pat" | "needs_config" | "auth_failed" | "error";
  detail?: string;
  credential_id?: string;
  help_url?: string;
  count?: number;
  records: AirtableRecord[];
};

type ResearchItem = {
  task_type: string;
  tool_name: string;
  success: boolean;
  recorded_at: string;
  summary: string;
};

type ResearchSection = {
  status: "ok" | "no_data";
  detail?: string;
  count?: number;
  items: ResearchItem[];
};

type SuggestedAction = {
  title: string;
  reason: string;
  link_label: string;
  link_href: string;
};

type DailyReportResponse = {
  generated_at: string;
  window_hours: number;
  jira: JiraSection;
  airtable: AirtableSection;
  research: ResearchSection;
  suggested_actions: SuggestedAction[];
};

const REFRESH_MS = 60_000;

/**
 * Strip the Vite BASE_URL prefix so React Router's <Link to=...> doesn't
 * double-prepend the basename. Backend emits `/pm/credentials`; router
 * (basename="/pm") wants `/credentials`.
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

const cardStyle: CSSProperties = {
  border: "1.3px solid var(--rule)",
  borderRadius: 6,
  padding: 14,
  marginBottom: 16,
  background: "var(--paper)",
};

const sectionHeader: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  color: "var(--pencil)",
  marginBottom: 6,
};

const sectionTitle: CSSProperties = {
  fontFamily: "var(--hand)",
  fontSize: 14,
  fontWeight: 600,
  marginBottom: 4,
};

const ctaBox: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 10,
  color: "var(--pencil)",
  padding: "8px 10px",
  border: "1px dashed var(--rule)",
  borderRadius: 4,
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 8,
};

const linkBtnStyle: CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  padding: "3px 8px",
  textDecoration: "none",
  whiteSpace: "nowrap",
};

function externalOrInternalLink(href: string, label: string) {
  if (href.startsWith("http")) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer noopener"
        className="btn"
        style={linkBtnStyle}
      >
        {label} ↗
      </a>
    );
  }
  return (
    <Link to={stripBasename(href)} className="btn" style={linkBtnStyle}>
      {label} →
    </Link>
  );
}

function formatRelativeTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diffMs = Date.now() - t;
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function DailyReport() {
  const [data, setData] = useState<DailyReportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const load = useCallback(async () => {
    try {
      const resp = await apiGet<DailyReportResponse>("/v1/daily-report");
      setData(resp);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Daily report unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (loading) {
    return (
      <div className="card" style={cardStyle}>
        <div style={sectionHeader}>DAILY STATUS REPORT</div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)" }}>
          gathering signals…
        </div>
      </div>
    );
  }
  if (error || !data) {
    return null;
  }

  const generated = new Date(data.generated_at);

  return (
    <div className="card" style={cardStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div>
          <div style={sectionHeader}>DAILY STATUS REPORT</div>
          <div style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 600 }}>
            Last {data.window_hours}h across your fleet
          </div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginTop: 2 }}>
            generated {formatRelativeTime(data.generated_at)} ({generated.toLocaleString()})
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

      {!collapsed && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
          {/* Jira */}
          <div>
            <div style={sectionTitle}>📋 Jira ({data.jira.count ?? 0})</div>
            {data.jira.status === "ok" ? (
              data.jira.issues.length === 0 ? (
                <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)" }}>
                  No issues assigned to you updated in the last 24h.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {data.jira.issues.slice(0, 8).map((it) => (
                    <a
                      key={it.key}
                      href={it.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      style={{ fontFamily: "var(--mono)", fontSize: 10, textDecoration: "none", color: "var(--ink)" }}
                    >
                      <span style={{ color: "var(--accent)" }}>{it.key}</span>{" "}
                      <span style={{ color: "var(--pencil)" }}>[{it.status}]</span>{" "}
                      {it.summary}
                    </a>
                  ))}
                </div>
              )
            ) : (
              <div style={ctaBox}>
                <span>{data.jira.detail || "Jira not connected"}</span>
                {data.jira.help_url && externalOrInternalLink(data.jira.help_url, "Add PAT")}
              </div>
            )}
          </div>

          {/* Airtable */}
          <div>
            <div style={sectionTitle}>🗂️ Airtable ({data.airtable.count ?? 0})</div>
            {data.airtable.status === "ok" ? (
              data.airtable.records.length === 0 ? (
                <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)" }}>
                  No record changes in the last 24h.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {data.airtable.records.slice(0, 8).map((r) => (
                    <div key={r.id} style={{ fontFamily: "var(--mono)", fontSize: 10 }}>
                      <span style={{ color: "var(--pencil)" }}>{r.id.slice(0, 8)}</span>{" "}
                      {Object.entries(r.fields)
                        .slice(0, 2)
                        .map(([k, v]) => `${k}=${String(v).slice(0, 40)}`)
                        .join(" · ")}
                    </div>
                  ))}
                </div>
              )
            ) : (
              <div style={ctaBox}>
                <span>{data.airtable.detail || "Airtable not connected"}</span>
                {data.airtable.help_url
                  ? externalOrInternalLink(data.airtable.help_url, "Add PAT")
                  : externalOrInternalLink("/pm/credentials", "Open Credentials")}
              </div>
            )}
          </div>

          {/* Research */}
          <div>
            <div style={sectionTitle}>🔬 Research ({data.research.count ?? 0})</div>
            {data.research.status === "ok" && data.research.items.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {data.research.items.slice(0, 6).map((it, i) => (
                  <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10 }}>
                    <span style={{ color: it.success ? "var(--accent)" : "var(--danger)" }}>
                      {it.success ? "✓" : "✗"}
                    </span>{" "}
                    <span style={{ color: "var(--pencil)" }}>{it.task_type}</span>{" "}
                    {it.summary || it.tool_name}
                  </div>
                ))}
              </div>
            ) : (
              <div style={ctaBox}>
                <span>{data.research.detail || "No research recorded yet"}</span>
                {externalOrInternalLink("/pm/agents", "Run pulse")}
              </div>
            )}
          </div>
        </div>
      )}

      {!collapsed && data.suggested_actions.length > 0 && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px dashed var(--rule)" }}>
          <div style={sectionHeader}>SUGGESTED ACTIONS</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.suggested_actions.slice(0, 6).map((a, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 8,
                  fontFamily: "var(--mono)",
                  fontSize: 10,
                }}
              >
                <div>
                  <div style={{ fontWeight: 600 }}>{a.title}</div>
                  <div style={{ color: "var(--pencil)" }}>{a.reason}</div>
                </div>
                {externalOrInternalLink(a.link_href, a.link_label)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
