import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import {
  Card,
  EmptyState,
  LoadingSpinner,
  Modal,
  PageHeader,
  SearchInput,
  useToast,
} from "../components/shared";

type Severity = "info" | "warning" | "critical";

type AuditEntry = {
  id: string;
  action: string;
  actor: string;
  target: string | null;
  detail: Record<string, unknown>;
  severity: Severity;
  created_at: string;
};

const ACTION_OPTIONS = [
  { value: "", label: "All Actions" },
  { value: "login", label: "Login" },
  { value: "elevate", label: "Elevate" },
  { value: "revoke", label: "Revoke" },
  { value: "dag_run", label: "DAG Run" },
  { value: "agent_create", label: "Agent Create" },
  { value: "gate_block", label: "Gate Block" },
  { value: "scan", label: "Scan" },
  { value: "config_change", label: "Config Change" },
];

const SEVERITY_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "info", label: "Info" },
  { value: "warning", label: "Warning" },
  { value: "critical", label: "Critical" },
];

const SEVERITY_COLORS: Record<Severity, { bg: string; fg: string }> = {
  info: { bg: "rgba(120,120,120,0.15)", fg: "#888" },
  warning: { bg: "rgba(212,160,23,0.15)", fg: "#b8860b" },
  critical: { bg: "rgba(196,69,42,0.15)", fg: "#c4452a" },
};

const ACTION_ICONS: Record<string, string> = {
  login: "\uD83D\uDD11",
  elevate: "\u2B06\uFE0F",
  revoke: "\u2B07\uFE0F",
  dag_run: "\u26A1",
  agent_create: "\uD83E\uDD16",
  gate_block: "\uD83D\uDEE1\uFE0F",
  scan: "\uD83D\uDD0D",
  config_change: "\u2699\uFE0F",
};

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function severityBadge(s: Severity) {
  const c = SEVERITY_COLORS[s];
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 3, fontSize: 8,
      fontFamily: "var(--mono)", fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {s}
    </span>
  );
}

function truncateJson(obj: Record<string, unknown>, maxLen = 60): string {
  const s = JSON.stringify(obj);
  return s.length > maxLen ? s.slice(0, maxLen) + "..." : s;
}

const selectStyle: React.CSSProperties = {
  padding: "5px 10px", fontFamily: "var(--mono)", fontSize: 10,
  background: "var(--paper-2, #f5f5f0)", border: "1.3px solid var(--rule)",
  borderRadius: 4, color: "var(--ink)", cursor: "pointer",
};

export default function AuditLog() {
  const toast = useToast();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [detailEntry, setDetailEntry] = useState<AuditEntry | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (actionFilter) params.set("action", actionFilter);
      if (severityFilter) params.set("severity", severityFilter);
      if (actorFilter) params.set("actor", actorFilter);
      const qs = params.toString();
      const data = await apiGet<AuditEntry[]>(`/v1/audit${qs ? `?${qs}` : ""}`);
      setEntries(data);
    } catch {
      toast("Failed to load audit log", "error");
    } finally {
      setLoading(false);
    }
  }, [actionFilter, severityFilter, actorFilter, toast]);

  useEffect(() => { load(); }, [load]);

  const handleRefresh = () => { load(); };

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader
        title="Audit Log"
        subtitle={`${entries.length} entries — a record of every action taken in the system`}
        helpHref="/docs#audit"
        actions={[
          <button
            key="refresh"
            onClick={handleRefresh}
            style={{
              padding: "5px 14px", borderRadius: 4, cursor: "pointer",
              fontFamily: "var(--mono)", fontSize: 10,
              border: "1.3px solid var(--rule)",
              background: "var(--paper)", color: "var(--ink)",
            }}
          >
            Refresh
          </button>,
        ]}
      />

      <Card>
        <div style={{
          display: "flex", gap: 8, alignItems: "center",
          padding: "10px 12px", borderBottom: "1.3px solid var(--rule)",
          flexWrap: "wrap",
        }}>
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={selectStyle}
          >
            {ACTION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            style={selectStyle}
          >
            {SEVERITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <div style={{ width: 180 }}>
            <SearchInput
              value={actorFilter}
              onChange={setActorFilter}
              placeholder="Filter actor..."
            />
          </div>
        </div>

        {loading ? (
          <LoadingSpinner />
        ) : entries.length === 0 ? (
          <EmptyState icon="📜" title="No audit entries" />
        ) : (
          <div style={{ overflow: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: 10 }}>
              <thead>
                <tr style={{ borderBottom: "1.3px solid var(--rule)" }}>
                  <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", whiteSpace: "nowrap" }}>Time</th>
                  <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", whiteSpace: "nowrap" }}>Action</th>
                  <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", whiteSpace: "nowrap" }}>Actor</th>
                  <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", whiteSpace: "nowrap" }}>Target</th>
                  <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", whiteSpace: "nowrap" }}>Severity</th>
                  <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase", whiteSpace: "nowrap" }}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => {
                  const icon = ACTION_ICONS[entry.action] || "\uD83D\uDCCB";
                  return (
                    <tr
                      key={entry.id}
                      style={{ borderBottom: "1px solid var(--rule)" }}
                    >
                      <td style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>
                        <span title={new Date(entry.created_at).toLocaleString()}>
                          {relativeTime(entry.created_at)}
                        </span>
                      </td>
                      <td style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>
                        <span style={{ fontFamily: "var(--mono)", fontSize: 10 }}>
                          {icon} {entry.action}
                        </span>
                      </td>
                      <td style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>
                        {entry.actor}
                      </td>
                      <td style={{ padding: "8px 12px", whiteSpace: "nowrap", color: entry.target ? "var(--ink)" : "var(--pencil)" }}>
                        {entry.target || "\u2014"}
                      </td>
                      <td style={{ padding: "8px 12px" }}>
                        {severityBadge(entry.severity)}
                      </td>
                      <td style={{ padding: "8px 12px" }}>
                        <button
                          onClick={() => setDetailEntry(entry)}
                          style={{
                            background: "none", border: "none", cursor: "pointer",
                            fontFamily: "var(--mono)", fontSize: 9,
                            color: "var(--accent)", padding: 0, textAlign: "left",
                          }}
                        >
                          {truncateJson(entry.detail)}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={detailEntry !== null}
        onClose={() => setDetailEntry(null)}
        title="Audit Detail"
        wide
      >
        {detailEntry && (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px", marginBottom: 12, fontFamily: "var(--mono)", fontSize: 10 }}>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Action</span>
              <span style={{ fontWeight: 600 }}>{ACTION_ICONS[detailEntry.action] || ""} {detailEntry.action}</span>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Actor</span>
              <span>{detailEntry.actor}</span>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Target</span>
              <span>{detailEntry.target || "\u2014"}</span>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Severity</span>
              <div>{severityBadge(detailEntry.severity)}</div>
              <span style={{ color: "var(--pencil)", textTransform: "uppercase", fontSize: 9 }}>Time</span>
              <span>{new Date(detailEntry.created_at).toLocaleString()}</span>
            </div>
            <div style={{
              background: "var(--paper-2, #f5f5f0)", border: "1.3px solid var(--rule)",
              borderRadius: 4, padding: 12, fontFamily: "var(--mono)", fontSize: 9,
              whiteSpace: "pre-wrap" as const, overflow: "auto", maxHeight: 400,
            }}>
              {JSON.stringify(detailEntry.detail, null, 2)}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
