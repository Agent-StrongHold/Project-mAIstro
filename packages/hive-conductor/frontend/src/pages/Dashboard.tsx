import { useState, useEffect, useCallback, useRef, type KeyboardEvent } from "react";
import { SetupChecklist } from "../components/SetupChecklist";
import { TemplatePicker } from "../components/TemplatePicker";

const JIRA_BASE = (import.meta as any).env?.VITE_JIRA_BASE_URL || "";

// ─── Types ──────────────────────────────────────────────────────────────────

interface Widget {
  id: string;
  type: string;
  title: string;
  size: "1" | "2" | "3" | "4" | "5" | "6";
  rows?: "1" | "2" | "3" | "4";
  config?: Record<string, any>;
}

// ─── Palette ────────────────────────────────────────────────────────────────

const C = {
  bg: "var(--paper)", card: "var(--paper-2)", border: "var(--rule)",
  gold: "var(--accent)", ink: "var(--ink)", muted: "var(--pencil)", dim: "var(--pencil)",
  ok: "var(--ok)", danger: "var(--danger)", accent: "var(--accent)",
};

// ─── Persistence ────────────────────────────────────────────────────────────

const DEFAULT_WIDGETS: Widget[] = [
  { id: "kpi-agents", type: "kpi", title: "Active Agents", size: "1", config: { field: "active_agents", sub: "vs last hour" } },
  { id: "kpi-runs", type: "kpi", title: "Runs Today", size: "1", config: { field: "runs_today", sub: "vs yesterday" } },
  { id: "kpi-latency", type: "kpi", title: "Avg Latency", size: "1", config: { field: "avg_latency", sub: "vs last hour" } },
  { id: "kpi-cost", type: "kpi", title: "Total Cost", size: "1", config: { field: "total_cost", sub: "vs yesterday" } },
  { id: "kpi-approval", type: "kpi", title: "Approval Rate", size: "1", config: { field: "approval_rate", sub: "vs last hour" } },
  { id: "kpi-ttft", type: "kpi", title: "TTFT", size: "1", config: { field: "ttft", sub: "p50 streaming" } },
  { id: "agents", type: "agent-orbs", title: "Agent Status", size: "6" },
  { id: "invocations", type: "invocations", title: "Invocations", size: "3" },
  { id: "cost-donut", type: "cost-donut", title: "Cost by Agent", size: "1" },
  { id: "trace", type: "trace", title: "Latest Trace", size: "2" },
];

type Tab = { name: string; widgets: Widget[] };
const DEFAULT_TABS: Tab[] = [{ name: "Overview", widgets: DEFAULT_WIDGETS }];

function saveTabs(tabs: Tab[], activeIdx: number) {
  fetch("/v1/dashboard/layout", { method: "PUT", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tabs, activeTab: activeIdx, updatedAt: new Date().toISOString() }) }).catch(() => {});
}
function useServerTabs(tabs: Tab[], setTabs: (t: Tab[]) => void, setActiveIdx: (i: number) => void) {
  const initialized = useRef(false);
  useEffect(() => {
    fetch("/v1/dashboard/layout", { credentials: "same-origin" })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.tabs?.length) {
          setTabs(d.tabs);
          if (typeof d.activeTab === "number") setActiveIdx(d.activeTab);
          initialized.current = true;
        } else if (d?.widgets?.length) {
          // Migrate legacy single-page layout to tabs
          setTabs([{ name: "Overview", widgets: d.widgets }]);
          initialized.current = true;
        } else if (!initialized.current) {
          saveTabs(tabs, 0);
          initialized.current = true;
        }
      })
      .catch(() => {});
  }, []);
}

// ─── Data ───────────────────────────────────────────────────────────────────

function useAgents() {
  const [a, setA] = useState<any[]>([]);
  useEffect(() => { fetch("/v1/agents", { credentials: "same-origin" }).then(r => r.json()).then(setA).catch(() => {}); }, []);
  return a;
}

function useMetrics() {
  const [m, setM] = useState<any>({});
  useEffect(() => {
    fetch("/v1/dashboard/metrics", { credentials: "same-origin" })
      .then(r => r.json()).then(setM).catch(() => {});
  }, []);
  return m;
}

// ─── Chat Bar ───────────────────────────────────────────────────────────────

function ChatBar({ widgets, onWidgetsChange, editing, tabs, activeIdx }: { widgets: Widget[]; onWidgetsChange: (w: Widget[]) => void; editing: boolean; tabs: Tab[]; activeIdx: number }) {
  const [value, setValue] = useState("");
  const [msgs, setMsgs] = useState<{ role: string; content: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [msgs]);

  const widgetSummary = JSON.stringify(widgets.map(w => ({ id: w.id, type: w.type, title: w.title, size: w.size, config: w.config })), null, 2);
  const tabSummary = tabs.map((t, i) => `${i === activeIdx ? "→" : " "} "${t.name}" (${t.widgets.length} widgets)`).join("\n");

  const BUILD_PROMPT = `You are a dashboard builder. Help the user explore their data and build deterministic widgets.

IMPORTANT: Widgets are DETERMINISTIC — they call fixed API endpoints at render time. NO LLM in the loop when the widget displays. Your job is to:
1. Help the user explore their data (use tools: search_jira, airtable_query, airtable_describe, query_metrics)
2. Show them what the data looks like
3. Then SAVE a widget with a fixed config that calls a direct API endpoint

CONNECTED SOURCES: Jira (on-prem), Airtable, runtime metrics.
TABS:\n${tabSummary}
CURRENT TAB: "${tabs[activeIdx]?.name}" — WIDGETS:\n${widgetSummary}

WIDGET CONFIGS — STRICT SCHEMA (do NOT invent fields):

TYPE "jira":
  config = {project: "DEMO", status?: "Open", days?: 7, assignee?: "currentUser()", jql_extra?: "type = Bug", jira_display: "count"|"list"|"status-breakdown", refresh_minutes?: 15}
  Example: create_dashboard_widget(title="Open Bugs", type="jira", size="2", config={project:"DEMO", jql_extra:"type = Bug AND resolution = Unresolved", jira_display:"count"}, tab="Overview")

TYPE "custom" with AIRTABLE BREAKDOWN (bar chart):
  config = {source: "airtable", table: "<exact table name>", field: "<column to group by>", group_by: "<same column>", max_records: "100", refresh_minutes?: 30}
  The widget will call /v1/widgets/airtable?table=X&group_by=Y and render a bar chart of counts.
  Example: create_dashboard_widget(title="Status Pipeline", type="custom", size="3", config={source:"airtable", table:"Use Case Submission", field:"Status", group_by:"Status", max_records:"100"})

TYPE "custom" with AIRTABLE DONUT:
  Same as breakdown but add display: "donut"
  config = {source: "airtable", table: "...", field: "...", group_by: "...", max_records: "100", display: "donut"}

TYPE "custom" with AIRTABLE LIST (scrollable names):
  config = {source: "airtable", table: "<table>", filter_formula?: "{Field}='Value'", display_field?: "Use Case Name/ Project", max_records: "50", refresh_minutes?: 30}
  The widget will call /v1/widgets/airtable?table=X&filter_formula=Y&display_field=Z and render a scrollable list.
  Example: create_dashboard_widget(title="Next Candidates", type="custom", size="2", config={source:"airtable", table:"Use Case Submission", filter_formula:"{V2 Migration Status}='Next Candidates'", display_field:"Use Case Name/ Project", max_records:"50"})

TYPE "custom" with METRICS:
  config = {source: "metrics", metric: "latency"|"ttft"|"cost"|"tokens"|"invocations"|"errors"}

TYPE "kpi":
  config = {field: "active_agents"|"runs_today"|"avg_latency"|"total_cost"|"approval_rate"|"ttft", sub: "description text"}

TYPE "agent-orbs": config = {} (no config needed)
TYPE "invocations": config = {} 
TYPE "cost-donut": config = {}
TYPE "trace": config = {}

CHART SELECTION GUIDE — pick the RIGHT display for the data:
- "bar" (default): Best for COUNTS where you compare absolute numbers (e.g., 40 Open, 5 Closed). Use when values vary widely.
- "donut": Best for PARTS OF A WHOLE where you want to show proportions of a total (e.g., 60% Development, 20% Commercialized). Use when there are 3-7 categories.
- "stacked" / "proportional": A single 100% bar showing all segments. Best for comparing composition at a glance. Good for status pipelines.
- "progress": A single progress bar toward a goal (e.g., 75% migrated). Use when there's a clear target.
- "ranked": Numbered leaderboard with medals for top 3. Best for people/team rankings (PM load, top contributors).
- "list": Scrollable list of named items. Best for showing actual records with names/details.
- "table": Full data table with column headers. Best when users need to see multiple fields per record.
- KPI (type "kpi"): A single big number. Best for one key metric.

RULES:
- If data has 2-7 categories with counts → donut or stacked (proportional view)
- If data has 8+ categories with counts → bar chart
- If comparing people/assignees → ranked
- If showing a pipeline with a target → progress
- If user wants to see actual names → list
- If user wants columns → table
- If just one number matters → KPI

NEVER DO:
- Do NOT put colors in breakdown values (wrong: {breakdown: {"Dev": "#ff0000"}})
- Do NOT put objects in breakdown values (wrong: {breakdown: {"Dev": {count: 5, color: "blue"}}})
- Do NOT use type "jira" for Airtable data. Use type "custom" with source "airtable"
- Do NOT invent display modes that don't exist. Only "donut" and default (bar chart) exist.
- Do NOT create widgets without querying the data first.

WORKFLOW:
1. Call suggest_widgets(source="airtable"|"jira"|"metrics", display="bar"|"donut"|"list"|"count") to get the EXACT config template
2. Query the data source to understand what's available (airtable_query, airtable_describe, search_jira)
3. Fill in the template placeholders with real values from the data
4. Call create_dashboard_widget with the filled-in config — DO NOT deviate from the template schema

To EDIT existing: \`\`\`widget_update\n{"action": "update", "id": "<id>", "changes": {...}}\`\`\`
To REMOVE existing: \`\`\`widget_update\n{"action": "remove", "id": "<id>"}\`\`\`

Sizes: 1-6 columns. Use "tab" param to target a specific tab (creates it if new).
TABS: The dashboard has tabs. Use the "tab" parameter in create_dashboard_widget to target a specific tab by name. If the tab doesn't exist, it will be created.

LAYOUT SUGGESTIONS:
When asked to suggest a layout or rearrange widgets:
1. Call memory_search with query "dashboard preferences" to check if the user has saved layout preferences.
2. Analyze the current widgets — look for: redundancies, poor grouping, wrong sizes, missing data.
3. Suggest specific changes using widget_update commands: reorder (by position in the array), resize, group related widgets, add missing views, remove redundancies.
4. After the user accepts, call memory_add to save their preferences (e.g., "User prefers: KPIs at top, charts in middle, lists at bottom. Likes donuts for <5 categories. Prefers 3-column charts.").
5. On ALL future widget creation, check memory first for these preferences and follow them.

ALWAYS call memory_search("dashboard preferences layout style") at the START of any build conversation to load user preferences.`;

  const QUERY_PROMPT = `You are a data analyst for this dashboard. Answer questions about the data being displayed and the underlying systems.

DISPLAYED WIDGETS:\n${widgetSummary}
TABS: ${tabs.map(t => t.name).join(", ")} (currently viewing: ${tabs[activeIdx]?.name})

TOOLS AVAILABLE: search_jira, airtable_query, airtable_describe, query_metrics, memory_search.

BEHAVIOR:
- First try to answer from the displayed widget data/config (you can see what each widget queries).
- If the user asks something not covered by current widgets, query the underlying data sources directly.
- Give concise, data-driven answers. Numbers, comparisons, trends.
- If they ask "why" questions, search Jira/Confluence for context.
- If they ask to drill into a specific widget's data, run the same query with more detail.
- Don't suggest creating widgets in this mode. Just answer questions.
- Keep responses short (2-4 sentences) unless listing data.`;

  const SYSTEM_PROMPT = editing ? BUILD_PROMPT : QUERY_PROMPT;

  const submit = async () => {
    if (!value.trim() || loading) return;
    const next = [...msgs, { role: "user", content: value }];
    setMsgs(next); setValue(""); setOpen(true); setLoading(true);
    try {
      const allMsgs = [{ role: "system", content: SYSTEM_PROMPT }, ...next];
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 120000);
      const r = await fetch("/v1/chat/stream", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ tools_scope: editing ? "dashboard_edit" : "dashboard_view", messages: allMsgs }), signal: controller.signal });
      clearTimeout(timeout);
      if (!r.ok) { const t = await r.text(); throw new Error(`${r.status}: ${t.slice(0,200)}`); }
      const reader = r.body?.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          for (const line of chunk.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try {
              const event = JSON.parse(line.slice(6));
              if (event.type === "token" || event.type === "content") {
                accumulated += event.content || event.token || "";
                setMsgs([...next, { role: "assistant", content: accumulated }]);
              } else if (event.type === "done") {
                if (event.content && !accumulated) accumulated = event.content;
              }
            } catch {
              // Deliberate: an SSE chunk can split a JSON payload mid-object,
              // so a parse failure here means "wait for the rest", not an error.
            }
          }
        }
      }
      const content = accumulated || "No response";
      setMsgs([...next, { role: "assistant", content }]);
      // Parse widget_update commands from response
      const updates = content.match(/```widget_update\n([\s\S]*?)```/g);
      if (updates) {
        let current = [...widgets];
        // `needsConfirm` was tracked alongside this and never read: it was set
        // true exactly when a push happened, so `pendingRemoves.length > 0`
        // below is the same predicate. The confirm prompt was always wired.
        const pendingRemoves: string[] = [];
        for (const block of updates) {
          try {
            const json = block.replace(/```widget_update\n?/, "").replace(/```/, "");
            const cmd = JSON.parse(json);
            if (cmd.action === "remove") {
              pendingRemoves.push(cmd.id);
            } else if (cmd.action === "update" && cmd.id) {
              current = current.map(w => w.id === cmd.id ? { ...w, ...cmd.changes } : w);
            }
          } catch { /* skip malformed */ }
        }
        // Apply non-destructive updates immediately
        if (current !== widgets) onWidgetsChange(current);
        // Queue removes for confirmation
        if (pendingRemoves.length > 0) {
          const names = pendingRemoves.map(id => widgets.find(w => w.id === id)?.title || id).join(", ");
          if (window.confirm(`Remove widget(s): ${names}?`)) {
            onWidgetsChange(current.filter(w => !pendingRemoves.includes(w.id)));
          }
        }
      }
    } catch (e: any) { setMsgs([...next, { role: "assistant", content: e?.name === "AbortError" ? "Request timed out (>2min). Try a simpler request." : "Connection error — check that the backend is running." }]); }
    finally { setLoading(false); }
  };

  return (
    <div style={{ marginBottom: "1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: C.card, border: `1px solid ${C.border}`, borderRadius: 10 }}>
        <span style={{ color: C.gold, fontSize: "0.75rem" }}>✦</span>
        <input value={value} onChange={e => setValue(e.target.value)} onKeyDown={(e: KeyboardEvent) => e.key === "Enter" && submit()}
          placeholder={editing ? "Build: add widgets, resize, configure..." : "Ask: drill into data, compare, explain trends..."}  disabled={loading}
          style={{ flex: 1, border: "none", background: "transparent", color: "var(--ink)", fontSize: "0.82rem", outline: "none" }} />
        {msgs.length > 0 && <button onClick={() => setOpen(!open)} style={{ background: "none", border: "none", color: C.muted, cursor: "pointer", fontSize: "0.63rem" }}>{open ? "▾" : `▸${msgs.length}`}</button>}
        {loading && <span style={{ fontSize: "0.63rem", color: C.muted }}>…</span>}
      </div>
      {open && msgs.length > 0 && (
        <div ref={ref} style={{ maxHeight: 160, overflowY: "auto", background: "var(--paper-2)", border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 10px", marginTop: 6 }}>
          {msgs.map((m, i) => (
            <div key={i} style={{ marginBottom: 6 }}>
              <div style={{ fontSize: "0.56rem", color: m.role === "user" ? C.gold : C.ok, fontWeight: 600, textTransform: "uppercase" }}>{m.role === "user" ? "You" : "Fantasia"}</div>
              <div style={{ fontSize: "0.74rem", color: C.ink, whiteSpace: "pre-wrap", lineHeight: 1.4 }}>{m.content}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Widget Renderers ───────────────────────────────────────────────────────

// No `title` prop: WidgetCard's header already renders `widget.title`, and this
// body never read the copy it was passed.
function KpiWidget({ config, agents, metrics }: { config?: Record<string, any>; agents: any[]; metrics: any }) {
  const field = config?.field || "";
  let value: string | number = "—";

  if (field === "active_agents") value = agents.length || 0;
  else if (field === "runs_today") value = metrics?.count || 0;
  else if (field === "avg_latency") { const ms = metrics?.latency_ms_mean || 0; value = ms ? `${(ms / 1000).toFixed(2)}s` : "0ms"; }
  else if (field === "total_cost") { const c = metrics?.cost_usd_total || 0; value = `$${c.toFixed(2)}`; }
  else if (field === "approval_rate") { const r = metrics?.approval_rate; value = r ? `${Math.round(r * 100)}%` : "—"; }
  else if (field === "ttft") { const ms = metrics?.latency_ms_p50 || 0; value = ms ? `${Math.round(ms)}ms` : "0ms"; }

  return (
    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%", position: "relative", paddingLeft: 10 }}>
      <div style={{ position: "absolute", left: 0, top: 8, bottom: 8, width: 3, borderRadius: 2, background: "var(--accent-gradient)" }} />
      <div style={{ fontSize: "2.2rem", fontWeight: 800, color: "var(--ink)", fontVariantNumeric: "tabular-nums", lineHeight: 1, letterSpacing: "-0.02em" }}>{typeof value === "number" ? value.toLocaleString() : value}</div>
      <div style={{ fontSize: "0.62rem", color: "var(--pencil)", marginTop: 6, letterSpacing: "0.02em", fontWeight: 500 }}>{config?.sub || field}</div>
    </div>
  );
}

function AgentOrbsWidget({ agents }: { agents: any[] }) {
  const cards = agents.length > 0 ? agents.slice(0, 6) : [{ name: "No agents", status: "idle" }];
  const statusColor = (s: string) => s === "active" ? C.ok : s === "error" ? C.danger : C.dim;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 8 }}>
      {cards.map((a: any, i: number) => (
        <div key={i} style={{ textAlign: "center" }}>
          <div style={{ width: 44, height: 44, borderRadius: "50%", margin: "0 auto", background: `radial-gradient(circle at 40% 40%, ${statusColor(a.status)}33, transparent)`, border: `2px solid ${statusColor(a.status)}`, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: statusColor(a.status), boxShadow: `0 0 6px ${statusColor(a.status)}` }} />
          </div>
          <div style={{ fontSize: "0.7rem", fontWeight: 600, color: C.ink, marginTop: 6 }}>{a.name || "Agent"}</div>
          <div style={{ fontSize: "0.56rem", color: statusColor(a.status) }}>● {a.status || "idle"}</div>
        </div>
      ))}
    </div>
  );
}

function InvocationsWidget({ metrics }: { metrics: any }) {
  const count = metrics?.count || 0;
  if (count === 0) return <div style={{ color: C.muted, fontSize: "0.72rem" }}>No invocations yet. Start a conversation to generate data.</div>;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: "1.2rem", fontWeight: 800, color: C.ink }}>{count}</span>
        <span style={{ fontSize: "0.65rem", color: C.muted }}>total invocations</span>
      </div>
      <div style={{ fontSize: "0.68rem", color: C.muted }}>
        <div>p50: {Math.round(metrics.latency_ms_p50 || 0)}ms · p95: {Math.round(metrics.latency_ms_p95 || 0)}ms</div>
        <div>Tokens in: {metrics.tokens_in_total || 0} · out: {metrics.tokens_out_total || 0}</div>
      </div>
    </div>
  );
}

function CostDonutWidget({ metrics }: { metrics: any }) {
  const total = metrics?.cost_usd_total || 0;
  if (total === 0) return <div style={{ color: C.muted, fontSize: "0.72rem" }}>No cost data yet.</div>;
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: "1.3rem", fontWeight: 800, color: C.ink }}>${total.toFixed(2)}</div>
      <div style={{ fontSize: "0.62rem", color: C.muted }}>Total estimated cost</div>
      <div style={{ fontSize: "0.6rem", color: C.dim, marginTop: 4 }}>{metrics?.count || 0} invocations</div>
    </div>
  );
}

function JiraWidget({ widget }: { widget: Widget }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const cfg = widget.config || {};

  useEffect(() => {
    const mins = cfg.refresh_minutes;
    if (!mins || mins < 1) return;
    const id = setInterval(() => setTick(t => t + 1), mins * 60000);
    return () => clearInterval(id);
  }, [cfg.refresh_minutes]);

  useEffect(() => {
    if (!cfg.project) { setLoading(false); return; }
    const params = new URLSearchParams({ project: cfg.project });
    if (cfg.status) params.set("status", cfg.status);
    if (cfg.assignee) params.set("assignee", cfg.assignee);
    if (cfg.days) params.set("days", cfg.days);
    if (cfg.jql_extra) params.set("jql_extra", cfg.jql_extra);

    fetch(`/v1/widgets/jira?${params}`, { credentials: "same-origin" })
      .then(r => r.json()).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [cfg.project, cfg.status, cfg.days, cfg.assignee, cfg.jql_extra, tick]);

  const display = cfg.jira_display || "count";

  if (!cfg.project) return <div style={{ color: C.muted, fontSize: "0.72rem" }}>Configure: set a Jira project key.</div>;
  if (loading) return <div style={{ color: C.muted, fontSize: "0.72rem" }}>Querying Jira...</div>;
  if (!data || data.error) return <div style={{ color: C.danger, fontSize: "0.72rem" }}>{data?.error || "No data"}</div>;

  // Status breakdown → horizontal bars
  if (display === "status-breakdown" && data.statuses) {
    const entries = Object.entries(data.statuses as Record<string, number>).sort((a, b) => b[1] - a[1]);
    const max = Math.max(...entries.map(([, v]) => v), 1);
    const statusColors: Record<string, string> = { "Open": "#3b82f6", "In Progress": "#eab308", "Done": "#22c55e", "Closed": "#6b7280", "To Do": "#8b5cf6", "In Review": "#f97316" };
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {entries.map(([name, count]) => (
          <div key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "0.6rem", color: C.muted, width: 80, textAlign: "right", flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
            <div style={{ flex: 1, height: 14, background: "var(--track)", borderRadius: 4, overflow: "hidden" }}>
              <div style={{ width: `${(count / max) * 100}%`, height: "100%", background: statusColors[name] || C.gold, borderRadius: 4 }} />
            </div>
            <span style={{ fontSize: "0.6rem", color: C.ink, width: 30, flexShrink: 0 }}>{count}</span>
          </div>
        ))}
        <div style={{ fontSize: "0.55rem", color: C.dim, textAlign: "right" }}>{data.shown && data.shown < data.total ? `${data.shown} of ${data.total}` : `${data.total}`} total</div>
      </div>
    );
  }

  // Issue list
  if (display === "list") {
    return (
      <div style={{ fontSize: "0.68rem" }}>
        <div style={{ color: C.muted, marginBottom: 4 }}>{data.total} issues</div>
        {(data.issues || []).slice(0, 8).map((iss: any, i: number) => (
          <div key={i} style={{ display: "flex", gap: 6, padding: "3px 0", borderBottom: `1px solid ${C.border}` }}>
            <a href={`${JIRA_BASE}/browse/${iss.key}`} target="_blank" rel="noopener noreferrer" style={{ color: C.gold, fontWeight: 600, flexShrink: 0, textDecoration: "none" }}>{iss.key}</a>
            <span style={{ color: C.ink, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{iss.summary}</span>
            <span style={{ color: C.muted, flexShrink: 0, fontSize: "0.58rem" }}>{iss.status}</span>
          </div>
        ))}
      </div>
    );
  }

  // Count → big number
  return (
    <div style={{ textAlign: "center", padding: "8px 0" }}>
      <div style={{ fontSize: "1.8rem", fontWeight: 700, color: C.gold }}>{(data.total || 0).toLocaleString()}</div>
      <div style={{ fontSize: "0.6rem", color: C.muted }}>tickets{cfg.days ? ` (last ${cfg.days}d)` : ""}</div>
    </div>
  );
}

function TraceWidget() {
  const steps = [{ s: "Input Received", t: "2.1s" }, { s: "Agent Selected", t: "0.8s" }, { s: "Tool Invoked", t: "1.4s" }, { s: "Knowledge Retrieved", t: "2.7s" }, { s: "Drafted", t: "1.9s" }, { s: "Review", t: "15.2s" }, { s: "Delivered", t: "0.6s" }];
  return (
    <div>{steps.map((st, i) => (
      <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 0", borderBottom: `1px solid ${C.border}`, fontSize: "0.7rem" }}>
        <span style={{ color: i === 5 ? C.gold : C.ok }}>●</span>
        <span style={{ flex: 1, color: C.ink }}>{st.s}</span>
        <span style={{ color: C.muted }}>{st.t}</span>
      </div>
    ))}</div>
  );
}

function UnknownWidget({ widget }: { widget: Widget }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const cfg = widget.config || {};
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const mins = cfg.refresh_minutes;
    if (!mins || mins < 1) return;
    const id = setInterval(() => setTick(t => t + 1), mins * 60000);
    return () => clearInterval(id);
  }, [cfg.refresh_minutes]);

  useEffect(() => {
    setLoading(true); setData(null);
    const endpoint = cfg.endpoint;
    // If config has inline data (baked in by the builder), use it directly
    if ((cfg.breakdown && Object.keys(cfg.breakdown).length > 0) || (cfg.records && cfg.records.length > 0) || (cfg.count !== undefined && cfg.count > 0)) {
      if (cfg.breakdown && Object.keys(cfg.breakdown).length > 0) setData({ breakdown: cfg.breakdown, total: Object.values(cfg.breakdown as Record<string,number>).reduce((a: number, b: number) => a + b, 0) });
      else if (cfg.records && cfg.records.length > 0) setData({ records: cfg.records, count: cfg.records.length });
      else setData({ value: cfg.count, unit: "records" });
      setLoading(false);
      return;
    }
    if (endpoint) {
      const url = cfg.params ? `${endpoint}?${new URLSearchParams(cfg.params)}` : endpoint;
      fetch(url, { method: cfg.method || "GET", credentials: "same-origin" })
        .then(r => r.json()).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    } else if (cfg.source === "airtable" && cfg.table) {
      const params = new URLSearchParams({ table: cfg.table });
      if (cfg.filter_formula) params.set("filter_formula", cfg.filter_formula);
      if (cfg.max_records) params.set("max_records", cfg.max_records);
      if (cfg.field || cfg.group_by) params.set("group_by", cfg.field || cfg.group_by);
      if (cfg.display_field) params.set("display_field", cfg.display_field);
      fetch(`/v1/widgets/airtable?${params}`, { credentials: "same-origin" })
        .then(r => r.json()).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    } else if (cfg.source === "metrics" && cfg.metric) {
      fetch(`/v1/widgets/metrics?metric=${cfg.metric}&period=${cfg.period || "1h"}`, { credentials: "same-origin" })
        .then(r => r.json()).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    } else if (cfg.query) {
      // Legacy: natural-language query widgets (pre-deterministic)
      fetch("/v1/chat/complete", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: [{ role: "system", content: "You are a data widget. Return concise data only. No markdown headers." }, { role: "user", content: cfg.query }] })
      }).then(r => r.json()).then(d => setData(d?.choices?.[0]?.message?.content || null)).catch(() => setData(null)).finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [cfg.endpoint, cfg.source, cfg.table, cfg.metric, cfg.filter_formula, cfg.query, tick]);

  if (!cfg.endpoint && !cfg.source && !cfg.query) {
    return <div style={{ color: C.muted, fontSize: "0.72rem" }}>
      <p style={{ margin: "0 0 4px" }}>Not configured.</p>
      <p style={{ margin: 0, fontSize: "0.65rem" }}>Use the chat in Edit mode to build this widget.</p>
    </div>;
  }
  if (loading) return <div style={{ color: C.muted, fontSize: "0.72rem" }}>Loading...</div>;
  if (!data) return <div style={{ color: C.danger, fontSize: "0.72rem" }}>No data</div>;
  if (data.error) return <div style={{ color: C.danger, fontSize: "0.72rem" }}>{data.error}</div>;

  // Legacy: string response from LLM query
  if (typeof data === "string") {
    // Try to parse as bar chart (markdown table with numbers)
    const lines = data.split("\n").filter((l: string) => l.includes("|") && !l.match(/^\|[-\s|]+\|$/));
    if (lines.length >= 2) {
      const rows = lines.slice(1).map((l: string) => l.split("|").map((c: string) => c.trim()).filter(Boolean));
      const nums = rows.map((r: string[]) => ({ label: r[0] || "", value: parseFloat((r[r.length - 1] || "0").replace(/[,\s]/g, "")) || 0 })).filter((r: {value: number}) => r.value > 0);
      if (nums.length >= 2) {
        const max = Math.max(...nums.map((n: {value: number}) => n.value));
        return (<div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {nums.map((n: {label: string; value: number}, i: number) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: "0.6rem", color: C.muted, width: 70, textAlign: "right", flexShrink: 0 }}>{n.label}</span>
              <div style={{ flex: 1, height: 16, background: "var(--track)", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: `${(n.value / max) * 100}%`, height: "100%", background: C.gold, borderRadius: 4 }} />
              </div>
              <span style={{ fontSize: "0.6rem", color: C.ink, width: 50, flexShrink: 0 }}>{n.value.toLocaleString()}</span>
            </div>
          ))}
        </div>);
      }
    }
    return <div style={{ fontSize: "0.75rem", color: C.ink, whiteSpace: "pre-wrap", lineHeight: 1.5 }}>{data}</div>;
  }

  // Table data → full data table with columns, sortable, filterable
  if (data.table_data && data.columns) {
    const rows: Record<string, string>[] = data.table_data;
    // Only show columns that have actual data (>30% non-empty)
    const allCols: string[] = data.columns;
    const usefulCols = allCols.filter(c => {
      const filled = rows.filter(r => r[c] && r[c] !== "—" && r[c].length > 0).length;
      return filled > rows.length * 0.3;
    }).slice(0, 6); // max 6 columns
    const cols = usefulCols.length > 0 ? usefulCols : allCols.slice(0, 4);
    return (
      <div style={{ fontSize: "0.65rem", display: "flex", flexDirection: "column", height: "100%" }}>
        <div style={{ overflowX: "auto", overflowY: "auto", flex: 1 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: cols.length * 100 }}>
            <thead>
              <tr style={{ position: "sticky", top: 0, background: "var(--paper-2)", zIndex: 1 }}>
                {cols.map(c => (
                  <th key={c} style={{ textAlign: "left", padding: "6px 8px", borderBottom: "2px solid var(--accent-light)", color: "var(--accent)", fontSize: "0.58rem", fontWeight: 700, whiteSpace: "nowrap", textTransform: "uppercase", letterSpacing: "0.05em" }}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 50).map((row, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? "transparent" : "var(--track)" }}>
                  {cols.map(c => (
                    <td key={c} style={{ padding: "4px 8px", color: "var(--ink)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 180, borderBottom: "1px solid var(--track)" }}>{(row[c] || "—").slice(0, 60)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ fontSize: "0.55rem", color: "var(--pencil)", marginTop: 4 }}>{data.count} rows × {cols.length} columns</div>
      </div>
    );
  }

  // Count display — show total as a big number (KPI-style)
  if (cfg.display === "count") {
    const total = data.total ?? data.count ?? (data.records && data.records.length) ?? (data.breakdown ? Object.values(data.breakdown as Record<string, number>).reduce((a: number, b: number) => a + b, 0) : 0);
    return (
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%" }}>
        <div style={{ fontSize: "2.2rem", fontWeight: 800, color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>{total.toLocaleString()}</div>
        {cfg.sub && <div style={{ fontSize: "0.6rem", color: "var(--pencil)", marginTop: 4 }}>{cfg.sub}</div>}
      </div>
    );
  }

  // List display — show record names
  if (cfg.display === "list" && data.records) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2, overflowY: "auto", maxHeight: 240 }}>
        {data.records.length === 0 && <div style={{ fontSize: "0.65rem", color: "var(--pencil)" }}>No records</div>}
        {data.records.map((r: { name?: string; id?: string }, i: number) => (
          <div key={i} style={{ fontSize: "0.68rem", padding: "4px 0", borderBottom: "1px solid var(--track)", color: "var(--ink)" }}>
            {r.name || r.id || "(untitled)"}
          </div>
        ))}
        <div style={{ fontSize: "0.55rem", color: "var(--pencil)", marginTop: 4 }}>{data.records.length} records</div>
      </div>
    );
  }

  // Breakdown response from airtable group_by → bar chart or donut
  if (data.breakdown && typeof data.breakdown === "object") {
    const entries = Object.entries(data.breakdown as Record<string, number>).filter(([k, v]) => v > 0 && k !== "(unset)").sort((a, b) => b[1] - a[1]);
    const max = Math.max(...entries.map(([, v]) => v), 1);
    const total = entries.reduce((s, [, v]) => s + v, 0);
    const palette = ({
      default: ["#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6", "#a78bfa", "#fb7185", "#fbbf24", "#34d399", "#67e8f9", "#c084fc"],
      midnight: ["#1e40af", "#3730a3", "#1d4ed8", "#4338ca", "#2563eb", "#4f46e5", "#6366f1", "#818cf8", "#93c5fd", "#60a5fa", "#a5b4fc", "#c7d2fe"],
      aurora: ["#059669", "#10b981", "#34d399", "#6ee7b7", "#14b8a6", "#2dd4bf", "#5eead4", "#99f6e4", "#a7f3d0", "#d1fae5", "#0d9488", "#0f766e"],
      sunset: ["#ea580c", "#f97316", "#fb923c", "#fdba74", "#dc2626", "#ef4444", "#f87171", "#fca5a5", "#db2777", "#ec4899", "#f472b6", "#f9a8d4"],
      ocean: ["#0284c7", "#0ea5e9", "#38bdf8", "#7dd3fc", "#0891b2", "#06b6d4", "#22d3ee", "#67e8f9", "#0369a1", "#0284c7", "#bae6fd", "#e0f2fe"],
      forest: ["#166534", "#15803d", "#16a34a", "#22c55e", "#4d7c0f", "#65a30d", "#84cc16", "#a3e635", "#854d0e", "#a16207", "#ca8a04", "#eab308"],
      royal: ["#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd", "#b45309", "#d97706", "#f59e0b", "#fbbf24", "#6d28d9", "#5b21b6", "#4c1d95", "#ddd6fe"],
      minimal: ["#6b7280", "#9ca3af", "#d1d5db", "#e5e7eb", "#4b5563", "#374151", "#f3f4f6", "#f9fafb", "#1f2937", "#111827", "#d1d5db", "#9ca3af"],
      neon: ["#f0abfc", "#e879f9", "#d946ef", "#c026d3", "#a855f7", "#7c3aed", "#22d3ee", "#06b6d4", "#10b981", "#84cc16", "#facc15", "#fb923c"],
    } as Record<string, string[]>)[cfg.theme || "default"] || ["#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6"];

    // Proportional stacked bar (100% width, segments)
    if (cfg.display === "stacked" || cfg.display === "proportional") {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", height: 28, borderRadius: 8, overflow: "hidden" }}>
            {entries.map(([label, count], i) => (
              <div key={label} style={{ width: `${(count / total) * 100}%`, background: palette[i % palette.length], minWidth: 2, position: "relative" }} title={`${label}: ${count} (${Math.round(count/total*100)}%)`} />
            ))}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", fontSize: "0.58rem" }}>
            {entries.slice(0, 8).map(([label, count], i) => (
              <span key={label} style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--pencil)" }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: palette[i % palette.length] }} />
                {label} <span style={{ fontWeight: 700, color: "var(--ink)" }}>{Math.round(count/total*100)}%</span>
              </span>
            ))}
          </div>
        </div>
      );
    }

    // Progress / goal tracking
    if (cfg.display === "progress") {
      const target = cfg.target || total;
      const achieved = entries[0]?.[1] || 0;
      const pct = Math.min(100, Math.round((achieved / target) * 100));
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, justifyContent: "center", height: "100%" }}>
          <div style={{ fontSize: "1.8rem", fontWeight: 800, color: "var(--ink)" }}>{pct}%</div>
          <div style={{ height: 10, background: "var(--track)", borderRadius: 6, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent-gradient)", borderRadius: 6, transition: "width 0.4s cubic-bezier(0.4, 0, 0.2, 1)" }} />
          </div>
          <div style={{ fontSize: "0.58rem", color: "var(--pencil)" }}>{achieved} / {target}</div>
        </div>
      );
    }

    // Ranked list with numbers (like a leaderboard)
    if (cfg.display === "ranked") {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {entries.slice(0, 10).map(([label, count], i) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
              <span style={{ width: 20, height: 20, borderRadius: "50%", background: i < 3 ? palette[i] : "var(--rule)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.55rem", fontWeight: 700, color: i < 3 ? "#fff" : "var(--pencil)", flexShrink: 0 }}>{i + 1}</span>
              <span style={{ flex: 1, fontSize: "0.68rem", color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
              <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>{count}</span>
            </div>
          ))}
        </div>
      );
    }

    // Donut chart
    if (cfg.display === "donut") {
      let angle = 0;
      const slices = entries.map(([label, count], i) => {
        const pct = count / total;
        const start = angle;
        angle += pct * 360;
        return { label, count, pct, start, end: angle, color: palette[i % palette.length] };
      });
      const r = 50, cx = 60, cy = 60, inner = 30;
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <svg width={120} height={120} viewBox="0 0 120 120">
            {slices.map((s, i) => {
              const startRad = (s.start - 90) * Math.PI / 180;
              const endRad = (s.end - 90) * Math.PI / 180;
              const largeArc = s.pct > 0.5 ? 1 : 0;
              const x1 = cx + r * Math.cos(startRad), y1 = cy + r * Math.sin(startRad);
              const x2 = cx + r * Math.cos(endRad), y2 = cy + r * Math.sin(endRad);
              const ix1 = cx + inner * Math.cos(endRad), iy1 = cy + inner * Math.sin(endRad);
              const ix2 = cx + inner * Math.cos(startRad), iy2 = cy + inner * Math.sin(startRad);
              return <path key={i} d={`M${x1},${y1} A${r},${r} 0 ${largeArc} 1 ${x2},${y2} L${ix1},${iy1} A${inner},${inner} 0 ${largeArc} 0 ${ix2},${iy2} Z`} fill={s.color} />;
            })}
            <text x={cx} y={cy + 4} textAnchor="middle" style={{ fontSize: "14px", fontWeight: 700, fill: "var(--ink)" }}>{total}</text>
          </svg>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.62rem" }}>
            {slices.slice(0, 8).map((s, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color, flexShrink: 0, boxShadow: `0 0 6px ${s.color}44` }} />
                <span style={{ color: "var(--pencil)", flex: 1 }}>{s.label}</span>
                <span style={{ color: "var(--ink)", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      );
    }

    // Default: bar chart
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {entries.slice(0, 10).map(([label, count], i) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "0.62rem", color: "var(--pencil)", width: 80, textAlign: "right", flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }} title={label}>{label}</span>
            <div style={{ flex: 1, height: 20, background: "var(--track)", borderRadius: 6, overflow: "hidden" }}>
              <div style={{ width: `${(count / max) * 100}%`, height: "100%", background: `linear-gradient(90deg, ${palette[i % palette.length]}cc, ${palette[i % palette.length]})`, borderRadius: 6, minWidth: 4, transition: "width 0.4s ease" }} />
            </div>
            <span style={{ fontSize: "0.65rem", color: "var(--ink)", width: 32, flexShrink: 0, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{count}</span>
          </div>
        ))}
        {data.total && <div style={{ fontSize: "0.55rem", color: "var(--pencil)", textAlign: "right", marginTop: 2 }}>{data.total} total</div>}
      </div>
    );
  }

  // Single metric value → big number
  if (data.value !== undefined) {
    return (
      <div style={{ textAlign: "center", padding: "8px 0" }}>
        <div style={{ fontSize: "1.6rem", fontWeight: 700, color: C.gold }}>{typeof data.value === "number" ? data.value.toLocaleString() : data.value}</div>
        <div style={{ fontSize: "0.6rem", color: C.muted }}>{data.unit || ""}{data.period ? ` (${data.period})` : ""}</div>
      </div>
    );
  }

  // Airtable records → list
  if (data.records) {
    return (
      <div style={{ fontSize: "0.7rem" }}>
        <div style={{ color: "var(--pencil)", marginBottom: 6, fontSize: "0.58rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{data.count || data.records.length} records</div>
        {data.records.slice(0, 12).map((rec: any, i: number) => {
          const name = rec.name || rec.Name || rec.Title || rec.use_case || rec.Summary || rec["Use Case Name/ Project"] || Object.values(rec).find(v => typeof v === "string" && (v as string).length > 3 && v !== rec.id && v !== rec.status) || rec.id;
          return (
            <div key={i} style={{ display: "flex", gap: 8, padding: "6px 4px", borderBottom: "1px solid var(--track)", alignItems: "center" }}>
              <span style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--accent)", flexShrink: 0, opacity: 0.7 }} />
              <span style={{ color: "var(--ink)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "0.68rem" }}>{name as string}</span>
              {rec.status && <span style={{ color: "var(--accent)", flexShrink: 0, fontSize: "0.56rem", padding: "2px 8px", borderRadius: 6, background: "var(--accent-light)", fontWeight: 600 }}>{rec.status}</span>}
            </div>
          );
        })}
      </div>
    );
  }

  // Object with numeric values → bar chart
  if (typeof data === "object" && !Array.isArray(data)) {
    const numEntries = Object.entries(data).filter(([, v]) => typeof v === "number") as [string, number][];
    if (numEntries.length >= 2) {
      const max = Math.max(...numEntries.map(([, v]) => v), 1);
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {numEntries.slice(0, 10).map(([label, value]) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: "0.6rem", color: C.muted, width: 70, textAlign: "right", flexShrink: 0 }}>{label}</span>
              <div style={{ flex: 1, height: 14, background: "var(--track)", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: `${(value / max) * 100}%`, height: "100%", background: C.gold, borderRadius: 4 }} />
              </div>
              <span style={{ fontSize: "0.6rem", color: C.ink, width: 40, flexShrink: 0 }}>{value.toLocaleString()}</span>
            </div>
          ))}
        </div>
      );
    }
  }

  // Array → list
  if (Array.isArray(data)) {
    return (<div style={{ fontSize: "0.7rem", maxHeight: 120, overflowY: "auto" }}>
      {data.slice(0, 8).map((item: any, i: number) => (
        <div key={i} style={{ padding: "2px 0", borderBottom: `1px solid ${C.border}`, color: C.ink }}>
          {item.key || item.title || item.name || item.Name || JSON.stringify(item).slice(0, 60)}
        </div>
      ))}
    </div>);
  }

  // Fallback
  return <pre style={{ fontSize: "0.6rem", color: C.ink, whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(data, null, 2).slice(0, 300)}</pre>;
}

// ─── Widget Card ────────────────────────────────────────────────────────────

// Dynamic cascading Airtable config: Base → Table → Columns
function AirtableCascade({ cfgTable, setCfgTable, cfgGroupBy, setCfgGroupBy, cfgDisplayField, setCfgDisplayField, cfgFilter, setCfgFilter, cfgMaxRecords, setCfgMaxRecords, cfgFields }: any) {
  const [bases, setBases] = useState<{id:string;name:string}[]>([]);
  const [tables, setTables] = useState<{id:string;name:string}[]>([]);
  const [selectedBase, setSelectedBase] = useState("");
  const [loadingTables, setLoadingTables] = useState(false);
  const inputStyle = { background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 6, color: "var(--ink)", padding: "4px 8px", fontSize: "0.72rem", width: "100%" };

  // Load bases on mount
  useEffect(() => {
    fetch("/v1/widgets/airtable/bases", { credentials: "same-origin" })
      .then(r => r.json()).then(d => setBases(d.bases || [])).catch(() => {});
  }, []);

  // Load tables when base selected
  useEffect(() => {
    if (!selectedBase) return;
    setLoadingTables(true);
    fetch(`/v1/widgets/airtable/tables?base_id=${selectedBase}`, { credentials: "same-origin" })
      .then(r => r.json()).then(d => { setTables(d.tables || []); setLoadingTables(false); }).catch(() => setLoadingTables(false));
  }, [selectedBase]);

  // Auto-select first base if only one
  useEffect(() => { if (bases.length === 1 && !selectedBase) setSelectedBase(bases[0].id); }, [bases]);

  return (<>
    <label style={{ fontSize: "0.58rem", color: "var(--pencil)" }}>Base</label>
    <select value={selectedBase} onChange={e => { setSelectedBase(e.target.value); setCfgTable(""); }} style={inputStyle}>
      <option value="">Select base...</option>
      {bases.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
    </select>

    <label style={{ fontSize: "0.58rem", color: "var(--pencil)" }}>Table</label>
    <select value={cfgTable} onChange={e => setCfgTable(e.target.value)} style={inputStyle} disabled={!selectedBase}>
      <option value="">{loadingTables ? "Loading..." : "Select table..."}</option>
      {tables.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
      {/* Fallback: show current value if not in list */}
      {cfgTable && !tables.find(t => t.name === cfgTable) && <option value={cfgTable}>{cfgTable}</option>}
    </select>

    {cfgTable && (<>
      <label style={{ fontSize: "0.58rem", color: "var(--pencil)" }}>Group By (chart column)</label>
      <select value={cfgGroupBy} onChange={e => setCfgGroupBy(e.target.value)} style={inputStyle}>
        <option value="">None (show as list/table)</option>
        {cfgFields.map((f: string) => <option key={f} value={f}>{f}</option>)}
      </select>

      <label style={{ fontSize: "0.58rem", color: "var(--pencil)" }}>Display Column</label>
      <select value={cfgDisplayField} onChange={e => setCfgDisplayField(e.target.value)} style={inputStyle}>
        <option value="">Auto-detect</option>
        {cfgFields.map((f: string) => <option key={f} value={f}>{f}</option>)}
      </select>

      <label style={{ fontSize: "0.58rem", color: "var(--pencil)" }}>Filter</label>
      <input value={cfgFilter} onChange={(e: any) => setCfgFilter(e.target.value)} placeholder="{Status} = 'Development'" style={inputStyle} />

      <label style={{ fontSize: "0.58rem", color: "var(--pencil)" }}>Max Records</label>
      <input type="number" value={cfgMaxRecords} onChange={(e: any) => setCfgMaxRecords(e.target.value)} style={{...inputStyle, width: 80}} />
    </>)}
  </>);
}

// `onResize` used to be threaded in here and was never called: the config
// panel's size slider (`cfgSize`) already saves through `onUpdate`, so resizing
// has one working path and had a second, dead one.
function WidgetCard({ widget, agents, metrics, editing, onRemove, onUpdate }: {
  widget: Widget; agents: any[]; metrics: any; editing: boolean;
  onRemove: () => void; onUpdate: (w: Widget) => void;
}) {
  const [configOpen, setConfigOpen] = useState(false);
  const span = { "1": "span 1", "2": "span 2", "3": "span 3", "4": "span 4", "5": "span 5", "6": "1 / -1" };

  // Config panel state

  const [cfgTitle, setCfgTitle] = useState(widget.title);
  const [cfgType, setCfgType] = useState(widget.type);
  const [cfgSize, setCfgSize] = useState(widget.size);
  const [cfgRows, setCfgRows] = useState(widget.rows || "1");
  const [cfgTable, setCfgTable] = useState(widget.config?.table || "");
  const [cfgGroupBy, setCfgGroupBy] = useState(widget.config?.field || widget.config?.group_by || "");
  const [cfgFilter, setCfgFilter] = useState(widget.config?.filter_formula || "");
  const [cfgDisplayField, setCfgDisplayField] = useState(widget.config?.display_field || "");
  const [cfgMaxRecords, setCfgMaxRecords] = useState(widget.config?.max_records || "20");
  const [cfgFields, setCfgFields] = useState<string[]>([]);

  useEffect(() => {
    if (!cfgTable) { setCfgFields([]); return; }
    fetch(`/v1/widgets/airtable/fields?table=${encodeURIComponent(cfgTable)}`, { credentials: "same-origin" })
      .then(r => r.json()).then(d => setCfgFields(d.fields || [])).catch(() => setCfgFields([]));
  }, [cfgTable]);
  const [cfgField, setCfgField] = useState(widget.config?.field || "");
  const [cfgSub, setCfgSub] = useState(widget.config?.sub || "");
  // Read-only on purpose, for now: the legacy-custom-widget `endpoint`/`query`
  // fields are loaded from the saved config and written straight back at save
  // time (see `config.endpoint = cfgEndpoint` below), but the config panel
  // renders no input bound to either, so nothing can call a setter. Dropping
  // the setters says that plainly; dropping the state would stop round-tripping
  // the values and silently erase them on the next save.
  const [cfgEndpoint] = useState(widget.config?.endpoint || "");
  const [cfgDisplay, setCfgDisplay] = useState(widget.config?.display || "auto");
  const [cfgQuery] = useState(widget.config?.query || "");
  const [cfgProject, setCfgProject] = useState(widget.config?.project || "");
  const [cfgStatus, setCfgStatus] = useState(widget.config?.status || "");
  const [cfgDays, setCfgDays] = useState(widget.config?.days || "7");
  const [cfgAssignee, setCfgAssignee] = useState(widget.config?.assignee || "");
  const [cfgJqlExtra, setCfgJqlExtra] = useState(widget.config?.jql_extra || "");
  const [cfgJiraDisplay, setCfgJiraDisplay] = useState(widget.config?.jira_display || "count");
  const [cfgRefresh, setCfgRefresh] = useState(widget.config?.refresh_minutes || "0");
  const [cfgTheme, setCfgTheme] = useState(widget.config?.theme || "default");
  // Dynamic variables for any widget type
  const [vars, setVars] = useState<Record<string, string>>(() => {
    const v: Record<string, string> = {};
    (widget.config?.variables || []).forEach((vr: any) => { v[vr.id] = vr.value || ""; });
    return v;
  });
  const [cfgDisplayType, setCfgDisplayType] = useState(widget.config?.display || "list");

  const saveConfig = () => {
    const config: Record<string, any> = { ...widget.config };
    if (cfgType === "kpi") { config.field = cfgField; config.sub = cfgSub; }
    else if (cfgType === "jira") {
      config.project = cfgProject; config.status = cfgStatus; config.days = cfgDays;
      config.assignee = cfgAssignee; config.jql_extra = cfgJqlExtra; config.jira_display = cfgJiraDisplay;
    } else {
      // Save variable values back into the schema
      if (config.variables) {
        config.variables = config.variables.map((v: any) => ({ ...v, value: vars[v.id] ?? v.value }));
      }
      config.display = cfgDisplayType;
      // For legacy custom widgets
      if (!config.variables) { config.endpoint = cfgEndpoint; config.query = cfgQuery; }
    }
    onUpdate({ ...widget, title: cfgTitle, type: cfgType, size: cfgSize as Widget["size"], rows: cfgRows as Widget["rows"], config: { ...config, refresh_minutes: Number(cfgRefresh) || 0, theme: cfgTheme, display: cfgDisplay !== "auto" ? cfgDisplay : undefined, ...(cfgTable ? { table: cfgTable, source: "airtable", filter_formula: cfgFilter || undefined, display_field: cfgDisplayField || undefined, max_records: cfgMaxRecords || "20" } : {}), ...(cfgGroupBy ? { field: cfgGroupBy, group_by: cfgGroupBy } : {}) } });
    setConfigOpen(false);
  };

  let content;
  switch (widget.type) {
    case "kpi": content = <KpiWidget config={widget.config} agents={agents} metrics={metrics} />; break;
    case "jira": content = widget.config?.source === "airtable" ? <UnknownWidget widget={widget} /> : <JiraWidget widget={widget} />; break;
    case "agent-orbs": content = <AgentOrbsWidget agents={agents} />; break;
    case "invocations": content = <InvocationsWidget metrics={metrics} />; break;
    case "cost-donut": content = <CostDonutWidget metrics={metrics} />; break;
    case "trace": content = <TraceWidget />; break;
    default: content = <UnknownWidget widget={widget} />;
  }

  return (
    <div className="dashboard-widget-card" style={{ gridColumn: span[widget.size], background: "var(--paper)", border: `1px solid ${editing ? C.gold : "var(--rule)"}`, borderRadius: 16, padding: "0.8rem", position: "relative", maxHeight: 320, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: "0.62rem", fontWeight: 600, color: "var(--pencil)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{widget.title}</span>
        {editing && <button onClick={() => setConfigOpen(true)} style={{ background: "none", border: "none", color: C.muted, cursor: "pointer", fontSize: "0.9rem" }}>⋯</button>}
      </div>
      {configOpen && (
        <div style={{ position: "fixed", inset: 0, zIndex: 999 }}>
          <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.25)" }} onClick={() => setConfigOpen(false)} />
          <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", zIndex: 1000, background: "var(--paper)", borderRadius: 16, padding: 20, display: "flex", flexDirection: "column", gap: 10, overflowY: "auto", border: "1px solid var(--rule)", width: 340, maxHeight: "85vh", boxShadow: "0 12px 40px rgba(0,0,0,0.15)" }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ fontSize: "0.6rem", fontWeight: 600, color: C.gold, textTransform: "uppercase" }}>Configure Widget</span>
            <button onClick={() => setConfigOpen(false)} style={{ background: "none", border: "none", color: C.muted, cursor: "pointer" }}>✕</button>
          </div>
          <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Title</label>
          <input value={cfgTitle} onChange={e => setCfgTitle(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }} />
          <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Type</label>
          <select value={cfgType} onChange={e => setCfgType(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }}>
            <option value="kpi">KPI Card</option>
            <option value="jira">Jira Query</option>
            <option value="agent-orbs">Agent Status</option>
            <option value="invocations">Invocations</option>
            <option value="cost-donut">Cost</option>
            <option value="trace">Trace View</option>
            <option value="custom">Custom (free query)</option>
          </select>
          <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Size (columns)</label>
          <input type="range" min="1" max="6" value={cfgSize} onChange={e => setCfgSize(e.target.value as Widget["size"])} style={{ width: "100%" }} />
          <span style={{ fontSize: "0.58rem", color: C.ink, textAlign: "center" }}>{cfgSize} col{Number(cfgSize) > 1 ? "s" : ""}</span>
          <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Height (rows)</label>
          <input type="range" min="1" max="4" value={cfgRows} onChange={e => setCfgRows(e.target.value as "1"|"2"|"3"|"4")} style={{ width: "100%" }} />
          <span style={{ fontSize: "0.58rem", color: C.ink, textAlign: "center" }}>{cfgRows} row{Number(cfgRows) > 1 ? "s" : ""}</span>
          {cfgType === "kpi" && (<>
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Data Field</label>
            <select value={cfgField} onChange={e => setCfgField(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }}>
              <option value="active_agents">Active Agents</option>
              <option value="runs_today">Runs Today</option>
              <option value="avg_latency">Avg Latency</option>
              <option value="total_cost">Total Cost</option>
              <option value="approval_rate">Approval Rate</option>
              <option value="ttft">TTFT</option>
            </select>
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Subtitle</label>
            <input value={cfgSub} onChange={e => setCfgSub(e.target.value)} placeholder="vs last hour" style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }} />
          </>)}
          {cfgType !== "kpi" && widget.config?.variables && (<>
            {(widget.config.variables as any[]).map((v: any) => (
              <div key={v.id}>
                <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>{v.label}</label>
                {v.type === "select" ? (
                  <select value={vars[v.id] || ""} onChange={e => setVars({ ...vars, [v.id]: e.target.value })} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, color: C.ink, padding: "4px 8px", fontSize: "0.72rem", width: "100%" }}>
                    {(v.options || []).map((o: string) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : v.type === "number" ? (
                  <input type="number" value={vars[v.id] || ""} onChange={e => setVars({ ...vars, [v.id]: e.target.value })} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, color: C.ink, padding: "4px 8px", fontSize: "0.72rem", width: "100%" }} />
                ) : (
                  <input value={vars[v.id] || ""} onChange={e => setVars({ ...vars, [v.id]: e.target.value })} placeholder={v.placeholder || ""} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, color: C.ink, padding: "4px 8px", fontSize: "0.72rem", width: "100%" }} />
                )}
              </div>
            ))}
            {widget.config.display_options && (<>
              <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Visualization</label>
              <select value={cfgDisplayType} onChange={e => setCfgDisplayType(e.target.value)} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, color: C.ink, padding: "4px 8px", fontSize: "0.72rem", width: "100%" }}>
                {(widget.config.display_options as string[]).map((o: string) => <option key={o} value={o}>{o}</option>)}
              </select>
            </>)}
          </>)}
          {cfgType === "jira" && !widget.config?.variables && (<>
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Project Key</label>
            <input value={cfgProject} onChange={e => setCfgProject(e.target.value)} placeholder="e.g. DEMO" style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }} />
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Status</label>
            <input value={cfgStatus} onChange={e => setCfgStatus(e.target.value)} placeholder="Open, In Progress, Done..." style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }} />
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Assignee</label>
            <input value={cfgAssignee} onChange={e => setCfgAssignee(e.target.value)} placeholder="currentUser() or username" style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }} />
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Days Back</label>
            <input type="number" value={cfgDays} onChange={e => setCfgDays(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }} />
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Extra JQL</label>
            <input value={cfgJqlExtra} onChange={e => setCfgJqlExtra(e.target.value)} placeholder="AND labels = ..." style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }} />
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Display</label>
            <select value={cfgJiraDisplay} onChange={e => setCfgJiraDisplay(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }}>
              <option value="count">Count (bar chart)</option>
              <option value="list">Issue List</option>
              <option value="status-breakdown">Status Breakdown</option>
            </select>
          </>)}
          {cfgType !== "kpi" && cfgType !== "jira" && !widget.config?.variables && (<>
            <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Data Source</label>
            <select value={cfgTable ? "airtable" : (widget.config?.source || "none")} onChange={e => { if (e.target.value === "none") setCfgTable(""); }} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }}>
              <option value="none">None</option>
              <option value="airtable">Airtable</option>
              <option value="metrics">Metrics</option>
            </select>
            {(cfgTable || widget.config?.source === "airtable") && (<AirtableCascade cfgTable={cfgTable} setCfgTable={setCfgTable} cfgGroupBy={cfgGroupBy} setCfgGroupBy={setCfgGroupBy} cfgDisplayField={cfgDisplayField} setCfgDisplayField={setCfgDisplayField} cfgFilter={cfgFilter} setCfgFilter={setCfgFilter} cfgMaxRecords={cfgMaxRecords} setCfgMaxRecords={setCfgMaxRecords} cfgFields={cfgFields} />)}
          </>)}
          <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Chart Type</label>
          <select value={cfgDisplay} onChange={e => setCfgDisplay(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }}>
            <option value="auto">Auto (based on data)</option>
            <option value="bar">Horizontal Bars</option>
            <option value="donut">Donut / Pie</option>
            <option value="stacked">Stacked Proportional</option>
            <option value="ranked">Ranked Leaderboard</option>
            <option value="progress">Progress Bar</option>
            <option value="list">Record List</option>
            <option value="table">Data Table</option>
          </select>
          <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Theme</label>
          <select value={cfgTheme} onChange={e => setCfgTheme(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }}>
            <option value="default">Default (Dark)</option>
            <option value="midnight">Midnight Blue</option>
            <option value="aurora">Aurora (Green/Teal)</option>
            <option value="sunset">Sunset (Orange/Pink)</option>
            <option value="ocean">Ocean (Blue/Cyan)</option>
            <option value="forest">Forest (Green/Earth)</option>
            <option value="royal">Royal (Purple/Gold)</option>
            <option value="minimal">Minimal (Monochrome)</option>
            <option value="neon">Neon (Vivid)</option>
          </select>
          <label style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>Auto-refresh</label>
          <select value={cfgRefresh} onChange={e => setCfgRefresh(e.target.value)} style={{ background: "var(--paper-2)", border: "1px solid var(--rule)", borderRadius: 8, color: "var(--ink)", padding: "6px 10px", fontSize: "0.72rem", outline: "none", width: "100%", caretColor: "var(--accent)" }}>
            <option value="0">Off</option>
            <option value="1">Every 1 min</option>
            <option value="5">Every 5 min</option>
            <option value="15">Every 15 min</option>
            <option value="30">Every 30 min</option>
            <option value="60">Every 60 min</option>
          </select>
          <button onClick={saveConfig} style={{ marginTop: 4, padding: "6px 0", borderRadius: 8, border: "none", background: C.gold, color: "#fff", fontSize: "0.68rem", fontWeight: 600, cursor: "pointer" }}>Save</button>
          <button onClick={() => { if (window.confirm(`Remove "${widget.title}"?`)) { onRemove(); setConfigOpen(false); } }} style={{ marginTop: 4, padding: "5px 0", borderRadius: 8, border: `1px solid ${C.danger}`, background: "transparent", color: C.danger, fontSize: "0.62rem", cursor: "pointer" }}>Delete Widget</button>
        </div></div>
      )}
      <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", scrollbarWidth: "thin", scrollbarColor: "var(--scroll-thumb) transparent" }}>{content}</div>
    </div>
  );
}

// ─── Add Widget ─────────────────────────────────────────────────────────────

const CATALOG = [
  { type: "kpi", label: "KPI Card", size: "1" as const },
  { type: "jira", label: "Jira Query", size: "2" as const },
  { type: "agent-orbs", label: "Agent Status", size: "6" as const },
  { type: "invocations", label: "Invocations", size: "3" as const },
  { type: "cost-donut", label: "Cost", size: "1" as const },
  { type: "trace", label: "Latest Trace", size: "2" as const },
  { type: "custom", label: "Custom (free query)", size: "2" as const },
];

function AddWidget({ onAdd }: { onAdd: (type: string, size: Widget["size"], config?: any, title?: string) => void }) {
  const [open, setOpen] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [examples, setExamples] = useState<any[]>([]);
  const [filter, setFilter] = useState("");

  const loadExamples = () => {
    if (examples.length) { setBrowsing(true); return; }
    fetch("/v1/dashboard/widget-examples", { credentials: "same-origin" })
      .then(r => r.json()).then(d => { setExamples(d); setBrowsing(true); }).catch(() => {});
  };

  const categories = [...new Set(examples.map(e => e.category))];
  const filtered = filter ? examples.filter(e => e.category === filter) : examples;

  return (
    <div style={{ gridColumn: "span 1", position: "relative" }}>
      <button onClick={() => setOpen(!open)} style={{ width: "100%", padding: 16, borderRadius: 14, border: `2px dashed ${C.border}`, background: "transparent", color: C.muted, fontSize: "0.72rem", cursor: "pointer" }}>+ Add</button>
      {open && !browsing && (
        <>
        <div style={{ position: "fixed", inset: 0, zIndex: 19 }} onClick={() => setOpen(false)} />
        <div style={{ position: "absolute", zIndex: 40, marginTop: 4, background: "var(--paper)", border: `1px solid ${C.border}`, borderRadius: 8, padding: 6, width: 180, boxShadow: "0 8px 24px rgba(0,0,0,0.12)" }}>
          {CATALOG.map(c => (
            <button key={c.type} onClick={() => { onAdd(c.type, c.size); setOpen(false); }}
              style={{ display: "block", width: "100%", textAlign: "left", padding: "5px 8px", background: "none", border: "none", color: C.ink, fontSize: "0.72rem", cursor: "pointer", borderRadius: 4 }}
              onMouseOver={e => (e.currentTarget.style.background = "var(--accent-light)")} onMouseOut={e => (e.currentTarget.style.background = "none")}>
              {c.label}
            </button>
          ))}
          <hr style={{ border: "none", borderTop: `1px solid ${C.border}`, margin: "4px 0" }} />
          <button onClick={loadExamples}
            style={{ display: "block", width: "100%", textAlign: "left", padding: "5px 8px", background: "none", border: "none", color: C.gold, fontSize: "0.72rem", cursor: "pointer", borderRadius: 4, fontWeight: 600 }}>
            Browse Examples...
          </button>
        </div>
        </>
      )}
      {open && browsing && (
        <>
        <div style={{ position: "fixed", inset: 0, zIndex: 19 }} onClick={() => { setBrowsing(false); setOpen(false); }} />
        <div style={{ position: "absolute", zIndex: 40, marginTop: 4, background: "var(--paper)", border: `1px solid ${C.border}`, borderRadius: 12, padding: 10, width: 360, maxHeight: 420, overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 8px 24px rgba(0,0,0,0.12)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <span style={{ fontSize: "0.65rem", fontWeight: 600, color: C.gold, textTransform: "uppercase" }}>Widget Examples ({filtered.length})</span>
            <button onClick={() => { setBrowsing(false); setOpen(false); setFilter(""); }} style={{ background: "none", border: "none", color: C.muted, cursor: "pointer" }}>✕</button>
          </div>
          <select value={filter} onChange={e => setFilter(e.target.value)} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, color: C.ink, padding: "4px 8px", fontSize: "0.68rem", marginBottom: 8 }}>
            <option value="">All Categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
            {filtered.map((ex, i) => (
              <button key={i} onClick={() => { onAdd(ex.type, ex.size, ex.config, ex.title); setOpen(false); setBrowsing(false); setFilter(""); }}
                style={{ display: "block", width: "100%", textAlign: "left", padding: "6px 8px", background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, color: C.ink, cursor: "pointer" }}
                onMouseOver={e => (e.currentTarget.style.borderColor = C.gold)} onMouseOut={e => (e.currentTarget.style.borderColor = C.border)}>
                <div style={{ fontSize: "0.7rem", fontWeight: 600 }}>{ex.title}</div>
                <div style={{ fontSize: "0.62rem", color: "var(--pencil)", fontWeight: 500, marginTop: 4 }}>{ex.description}</div>
              </button>
            ))}
          </div>
        </div>
        </>
      )}
    </div>
  );
}

// ─── Dashboard Page ─────────────────────────────────────────────────────────

export default function Dashboard() {
  const [tabs, setTabs] = useState<Tab[]>(DEFAULT_TABS);
  const [activeIdx, setActiveIdx] = useState(0);
  const [editing, setEditing] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [history, setHistory] = useState<Tab[][]>([]);
  const [future, setFuture] = useState<Tab[][]>([]);
  const agents = useAgents();
  const metrics = useMetrics();
  useServerTabs(tabs, setTabs, setActiveIdx);

  const widgets = tabs[activeIdx]?.widgets || [];

  const update = useCallback((next: Widget[]) => {
    setHistory(h => [...h.slice(-20), tabs]);
    setFuture([]);
    const newTabs = tabs.map((t, i) => i === activeIdx ? { ...t, widgets: next } : t);
    setTabs(newTabs);
    saveTabs(newTabs, activeIdx);
  }, [tabs, activeIdx]);

  const undo = () => {
    if (history.length === 0) return;
    const prev = history[history.length - 1];
    setFuture(f => [...f, tabs]);
    setHistory(h => h.slice(0, -1));
    setTabs(prev);
    saveTabs(prev, activeIdx);
  };

  const redo = () => {
    if (future.length === 0) return;
    const next = future[future.length - 1];
    setHistory(h => [...h, tabs]);
    setFuture(f => f.slice(0, -1));
    setTabs(next);
    saveTabs(next, activeIdx);
  };

  const addTab = () => {
    const name = prompt("Tab name:");
    if (!name) return;
    const newTabs = [...tabs, { name, widgets: [] }];
    setTabs(newTabs);
    setActiveIdx(newTabs.length - 1);
    saveTabs(newTabs, newTabs.length - 1);
  };

  const renameTab = (i: number) => {
    const name = prompt("New name:", tabs[i].name);
    if (!name) return;
    const newTabs = tabs.map((t, idx) => idx === i ? { ...t, name } : t);
    setTabs(newTabs);
    saveTabs(newTabs, activeIdx);
  };

  const removeTab = (i: number) => {
    if (tabs.length <= 1) return;
    if (!confirm(`Remove tab "${tabs[i].name}"?`)) return;
    const newTabs = tabs.filter((_, idx) => idx !== i);
    const newIdx = Math.min(activeIdx, newTabs.length - 1);
    setTabs(newTabs);
    setActiveIdx(newIdx);
    saveTabs(newTabs, newIdx);
  };
  const addWidget = (type: string, size: Widget["size"], config?: any, title?: string) => update([...widgets, { id: `w-${Date.now()}`, type, title: title || CATALOG.find(c => c.type === type)?.label || type, size, config }]);
  const removeWidget = (id: string) => update(widgets.filter(w => w.id !== id));
  const updateWidget = (id: string, w: Widget) => update(widgets.map(x => x.id === id ? w : x));

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.ink, fontFamily: "'Inter Variable', 'Inter', -apple-system, system-ui, sans-serif", padding: "1.5rem 2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.1rem" }}>
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 800, letterSpacing: "-0.02em", margin: 0 }}>Live Operations</h1>
          <p style={{ fontSize: "0.72rem", color: C.muted, margin: "3px 0 0" }}>Real-time visibility into your orchestration</p>
        </div>
        <div className="dashboard-header-actions" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="dashboard-status-pill">
            <span className="dashboard-status-dot" />
            Operational
          </span>
          <button onClick={() => window.location.reload()} style={{ padding: "4px 8px", borderRadius: 8, border: `1px solid ${C.border}`, background: "transparent", color: C.muted, fontSize: "0.63rem", cursor: "pointer" }}>↻ Refresh</button>
          {editing && (<>
            <button onClick={undo} disabled={history.length === 0} style={{ padding: "4px 8px", borderRadius: 8, border: `1px solid ${C.border}`, background: history.length ? C.card : "transparent", color: history.length ? C.ink : C.dim, fontSize: "0.7rem", cursor: history.length ? "pointer" : "default", opacity: history.length ? 1 : 0.4 }}>← Undo</button>
            <button onClick={redo} disabled={future.length === 0} style={{ padding: "4px 8px", borderRadius: 8, border: `1px solid ${C.border}`, background: future.length ? C.card : "transparent", color: future.length ? C.ink : C.dim, fontSize: "0.7rem", cursor: future.length ? "pointer" : "default", opacity: future.length ? 1 : 0.4 }}>Redo →</button>
          </>)}
          <button onClick={() => setEditing(!editing)} style={{
            padding: "4px 12px", borderRadius: 12, border: `1px solid ${editing ? C.gold : C.border}`,
            background: editing ? "var(--accent-light)" : "transparent",
            color: editing ? C.gold : C.muted, fontSize: "0.63rem", fontWeight: 600, cursor: "pointer",
          }}>{editing ? "✓ Done" : "✎ Edit"}</button>
          <button onClick={() => setShowTemplates(true)} style={{ padding: "4px 10px", borderRadius: 12, border: `1px solid ${C.border}`, background: "transparent", color: C.accent, fontSize: "0.63rem", cursor: "pointer" }}>📂 Templates</button>
          <button onClick={() => update(DEFAULT_WIDGETS)} style={{ padding: "4px 10px", borderRadius: 12, border: `1px solid ${C.border}`, background: "transparent", color: C.ok, fontSize: "0.63rem", cursor: "pointer" }}>Reset Default</button>
          <button onClick={() => {
            const input = document.querySelector("input[placeholder*='Build'],input[placeholder*='Ask']") as HTMLInputElement;
            if (input) {
              const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
              nativeSet.call(input, "Use analyze_dashboard to screenshot my dashboard and visually review it. Then suggest specific widget changes — what to add, remove, resize, or retype. Be specific with widget configs I can apply.");
              input.dispatchEvent(new Event('input', { bubbles: true }));
              setTimeout(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })), 50);
            }
          }} style={{ padding: "4px 10px", borderRadius: 12, border: "1px solid rgba(37,99,235,0.3)", background: "var(--accent-light)", color: "var(--accent)", fontSize: "0.63rem", cursor: "pointer" }}>✨ Suggest Layout</button>
        </div>
      </div>

      <SetupChecklist />

      <ChatBar widgets={widgets} onWidgetsChange={(w) => update(w)} editing={editing} tabs={tabs} activeIdx={activeIdx} />

      {/* Tabs */}
      <div style={{ display: "flex", alignItems: "center", gap: 2, marginBottom: "0.8rem", borderBottom: `1px solid ${C.border}`, paddingBottom: 6, overflowX: "auto", scrollbarWidth: "none" }}>
        {tabs.map((t, i) => (
          <button key={i} onClick={() => setActiveIdx(i)} onDoubleClick={() => editing && renameTab(i)}
            style={{ padding: "4px 12px", borderRadius: "8px 8px 0 0", border: "none", background: i === activeIdx ? C.card : "transparent", color: i === activeIdx ? C.gold : C.muted, fontSize: "0.68rem", fontWeight: i === activeIdx ? 600 : 400, cursor: "pointer", position: "relative", whiteSpace: "nowrap", flexShrink: 0 }}>
            {t.name}
            {editing && tabs.length > 1 && i === activeIdx && (
              <span onClick={(e) => { e.stopPropagation(); removeTab(i); }} style={{ marginLeft: 6, color: C.danger, fontSize: "0.55rem", cursor: "pointer" }}>✕</span>
            )}
          </button>
        ))}
        {editing && <button onClick={addTab} style={{ padding: "4px 8px", border: "none", background: "transparent", color: C.muted, fontSize: "0.68rem", cursor: "pointer" }}>+ Tab</button>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: "0.6rem" }}>
        {widgets.map(w => (
          <WidgetCard key={w.id} widget={w} agents={agents} metrics={metrics} editing={editing}
            onRemove={() => removeWidget(w.id)}
            onUpdate={(updated) => updateWidget(w.id, updated)} />
        ))}
        {editing && <AddWidget onAdd={addWidget} />}
      </div>
      {showTemplates && <TemplatePicker onClose={() => setShowTemplates(false)} onSelect={(id) => {
        fetch(`/v1/dashboard/demos/${id}`, { credentials: "same-origin" })
          .then(r => r.json()).then(d => { if (d.widgets) update(d.widgets); });
        setShowTemplates(false);
      }} />}
    </div>
  );
}
