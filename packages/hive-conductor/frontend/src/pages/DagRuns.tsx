// Day 9 v0 — PM DAG live-run viewer.
//
// Subscribes to /v1/dag-runs/{id}/events (SSE) and renders the 6-node PM
// DAG as plain SVG (no react-flow / @xyflow dep — keeps the OSS-approval
// surface and bundle size small). The PM_GRAPH_CONFIG topology is fixed,
// so node positions are hard-laid into a tidy grid.
//
// State per node: idle (gray) → running (amber, pulsing) → completed
// (green if source=llm; blue if source=no_data) | failed (red).
//
// Click a node → expand panel showing the event payload (LLM summary,
// duration_ms, tool result preview). Day 9 ships this read-only view;
// Day 13 will overlay eval-judge scores on each node.
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet } from "../lib/api";

type EventType = "pm_node_started" | "pm_node_completed" | "pm_node_failed";

interface DagEvent {
  event_type: EventType;
  role: string;
  capability: string;
  payload: Record<string, unknown>;
  timestamp: number;
}

interface RunSummary {
  id: string;
  user_id: string;
  started_at: number;
  finished_at: number | null;
  event_count: number;
  node_states: Record<string, string>;
}

interface RunDetail extends RunSummary {
  events: DagEvent[];
}

// Hard-laid topology — matches graph/pm_domain.PM_GRAPH_CONFIG.
const NODES: { role: string; label: string; col: number; row: number }[] = [
  { role: "intake",           label: "Intake",            col: 1, row: 0 },
  { role: "program_manager",  label: "Program Manager",   col: 1, row: 1 },
  { role: "research",         label: "Research",          col: 0, row: 2 },
  { role: "risk_dependency",  label: "Risk & Dependency", col: 1, row: 2 },
  { role: "delivery",         label: "Delivery",          col: 2, row: 2 },
  { role: "reporting",        label: "Reporting",         col: 1, row: 3 },
];

const EDGES: { from: string; to: string }[] = [
  { from: "intake",          to: "program_manager" },
  { from: "program_manager", to: "research" },
  { from: "program_manager", to: "risk_dependency" },
  { from: "program_manager", to: "delivery" },
  { from: "research",        to: "reporting" },
  { from: "risk_dependency", to: "reporting" },
  { from: "delivery",        to: "reporting" },
];

const COL_WIDTH = 220;
const ROW_HEIGHT = 130;
const X_OFFSET = 60;
const Y_OFFSET = 40;
const NODE_W = 180;
const NODE_H = 70;

function nodeCenter(col: number, row: number): { x: number; y: number } {
  return {
    x: X_OFFSET + col * COL_WIDTH + NODE_W / 2,
    y: Y_OFFSET + row * ROW_HEIGHT + NODE_H / 2,
  };
}

function statusColor(state: string): { fill: string; stroke: string; label: string } {
  switch (state) {
    case "running":
      return { fill: "#fef3c7", stroke: "#f59e0b", label: "running" };
    case "llm":
      return { fill: "#dcfce7", stroke: "#16a34a", label: "completed (llm)" };
    case "no_data":
      return { fill: "#dbeafe", stroke: "#2563eb", label: "completed (no_data)" };
    case "failed":
      return { fill: "#fee2e2", stroke: "#dc2626", label: "failed" };
    default:
      return { fill: "#f3f4f6", stroke: "#9ca3af", label: "idle" };
  }
}

function fmtDuration(ms: unknown): string {
  if (typeof ms !== "number") return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function DagRuns() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // List recent runs.
  const loadRuns = useCallback(async () => {
    try {
      const data = await apiGet<RunSummary[]>("/v1/dag-runs");
      setRuns(data);
      if (data.length > 0 && !selectedRunId) {
        setSelectedRunId(data[0].id);
      }
    } catch (e) {
      setError((e as Error).message ?? "failed to load runs");
    }
  }, [selectedRunId]);

  useEffect(() => {
    void loadRuns();
    const i = setInterval(() => void loadRuns(), 10_000);
    return () => clearInterval(i);
  }, [loadRuns]);

  // Initial detail load + live SSE subscription for selectedRunId.
  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null);
      return;
    }
    let active = true;
    let es: EventSource | null = null;
    void (async () => {
      try {
        const d = await apiGet<RunDetail>(`/v1/dag-runs/${selectedRunId}`);
        if (active) setDetail(d);
      } catch (e) {
        if (active) setError((e as Error).message ?? "detail load failed");
        return;
      }
      es = new EventSource(`/v1/dag-runs/${selectedRunId}/events`);
      const handler = (ev: MessageEvent) => {
        if (!active) return;
        try {
          const parsed = JSON.parse(ev.data) as DagEvent;
          setDetail((cur) =>
            cur
              ? {
                  ...cur,
                  events: [...cur.events, parsed],
                  event_count: cur.event_count + 1,
                  node_states: deriveStates([...cur.events, parsed]),
                }
              : cur,
          );
        } catch {
          /* malformed event, skip */
        }
      };
      es.addEventListener("pm_node_started", handler as EventListener);
      es.addEventListener("pm_node_completed", handler as EventListener);
      es.addEventListener("pm_node_failed", handler as EventListener);
    })();
    return () => {
      active = false;
      es?.close();
    };
  }, [selectedRunId]);

  const nodeStates = useMemo(() => detail?.node_states ?? {}, [detail]);

  const selectedNodeEvents = useMemo(
    () => (detail && selectedNode
      ? detail.events.filter((e) => `${e.role}.${e.capability}` === selectedNode || e.role === selectedNode)
      : []),
    [detail, selectedNode],
  );

  const width = X_OFFSET * 2 + COL_WIDTH * 3 - 20;
  const height = Y_OFFSET * 2 + ROW_HEIGHT * 4 - 40;

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ marginTop: 0 }}>Live DAG Runs</h2>
      <p style={{ color: "#6b7280", marginTop: -6 }}>
        Live view of the bundled demo pipeline (intake → research → delivery → reporting). Each node = one
        (role, capability) invocation. States stream over SSE from /v1/dag-runs/{`{id}`}/events. This view
        shows that fixed pipeline only — workflows you create yourself (via Chat or the DAG Builder) run, but
        aren't visualized here yet.
      </p>

      {error && (
        <div style={{ background: "#fee2e2", border: "1px solid #fca5a5", padding: 10, margin: "8px 0", borderRadius: 6 }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", gap: 16, marginTop: 12 }}>
        <aside style={{ width: 220, flexShrink: 0 }}>
          <h3 style={{ marginTop: 0, fontSize: 14 }}>Recent runs</h3>
          {runs.length === 0 && <div style={{ color: "#9ca3af" }}>No runs yet. Trigger the demo pipeline to start.</div>}
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {runs.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => { setSelectedRunId(r.id); setSelectedNode(null); }}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: 8,
                    border: selectedRunId === r.id ? "2px solid #2563eb" : "1px solid #e5e7eb",
                    borderRadius: 4,
                    marginBottom: 4,
                    background: "white",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontFamily: "monospace", fontSize: 12 }}>{r.id.slice(0, 8)}…</div>
                  <div style={{ fontSize: 11, color: "#6b7280" }}>
                    {new Date(r.started_at * 1000).toLocaleTimeString()} · {r.event_count} events
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section style={{ flex: 1 }}>
          <svg
            width={width}
            height={height}
            style={{ background: "#fafafa", border: "1px solid #e5e7eb", borderRadius: 8 }}
          >
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af" />
              </marker>
            </defs>
            {EDGES.map((e, i) => {
              const fromNode = NODES.find((n) => n.role === e.from)!;
              const toNode = NODES.find((n) => n.role === e.to)!;
              const a = nodeCenter(fromNode.col, fromNode.row);
              const b = nodeCenter(toNode.col, toNode.row);
              return (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y + NODE_H / 2}
                  x2={b.x}
                  y2={b.y - NODE_H / 2 + 6}
                  stroke="#9ca3af"
                  strokeWidth={2}
                  markerEnd="url(#arrow)"
                />
              );
            })}
            {NODES.map((n) => {
              const x = X_OFFSET + n.col * COL_WIDTH;
              const y = Y_OFFSET + n.row * ROW_HEIGHT;
              // Find any matching node_state key (e.g. "intake.create_initiative").
              const stateKey = Object.keys(nodeStates).find((k) => k.startsWith(`${n.role}.`)) ?? n.role;
              const state = nodeStates[stateKey] ?? "idle";
              const { fill, stroke, label } = statusColor(state);
              const isSelected = selectedNode === n.role;
              return (
                <g
                  key={n.role}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelectedNode(isSelected ? null : n.role)}
                >
                  <rect
                    x={x}
                    y={y}
                    width={NODE_W}
                    height={NODE_H}
                    rx={8}
                    fill={fill}
                    stroke={isSelected ? "#0f172a" : stroke}
                    strokeWidth={isSelected ? 3 : 2}
                  />
                  <text
                    x={x + 12}
                    y={y + 22}
                    fontSize={14}
                    fontWeight={600}
                    fill="#0f172a"
                  >
                    {n.label}
                  </text>
                  <text
                    x={x + 12}
                    y={y + 42}
                    fontSize={11}
                    fill="#374151"
                  >
                    {label}
                  </text>
                  <text
                    x={x + 12}
                    y={y + 60}
                    fontSize={10}
                    fill="#6b7280"
                  >
                    {stateKey.includes(".") ? stateKey.split(".")[1] : "—"}
                  </text>
                </g>
              );
            })}
          </svg>

          {selectedNode && detail && (
            <div
              style={{
                marginTop: 12,
                padding: 12,
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                background: "white",
              }}
            >
              <h3 style={{ marginTop: 0 }}>
                Node: {selectedNode} ({selectedNodeEvents.length} events)
              </h3>
              {selectedNodeEvents.length === 0 && (
                <div style={{ color: "#9ca3af" }}>No events for this node yet.</div>
              )}
              {selectedNodeEvents.map((ev, i) => (
                <div
                  key={i}
                  style={{
                    padding: 8,
                    margin: "6px 0",
                    background: "#f9fafb",
                    borderLeft: `3px solid ${statusColor(ev.payload?.source as string ?? ev.event_type === "pm_node_failed" ? "failed" : "running").stroke}`,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#374151" }}>
                    <strong>{ev.event_type}</strong>
                    <span>{new Date(ev.timestamp * 1000).toLocaleTimeString()} · {fmtDuration(ev.payload?.duration_ms)}</span>
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    <span style={{ color: "#6b7280" }}>capability:</span> {ev.capability}
                  </div>
                  {typeof ev.payload?.summary === "string" && (
                    <div style={{ fontSize: 13, marginTop: 4, whiteSpace: "pre-wrap" }}>
                      {ev.payload.summary as string}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

// Local replica of services/dag_run_store.DagRun.to_summary's node_states
// derivation. Lets us update the live view without re-fetching the detail.
function deriveStates(events: DagEvent[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const ev of events) {
    const key = `${ev.role}.${ev.capability}`;
    if (ev.event_type === "pm_node_completed") {
      const source = (ev.payload as Record<string, unknown>)?.source;
      out[key] = typeof source === "string" ? source : "llm";
    } else if (ev.event_type === "pm_node_failed") {
      out[key] = "failed";
    } else if (!(key in out)) {
      out[key] = "running";
    }
  }
  return out;
}
