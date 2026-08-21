import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import {
  ConfirmDialog,
  EmptyState,
  Hex,
  LoadingSpinner,
  Modal,
  PageHeader,
  useToast,
} from "../components/shared";

type Role = "queen" | "worker" | "scout" | "drone" | "guard";
type Strategy = "react" | "plan_execute" | "direct" | "delegate";
type DagStatus = "draft" | "active" | "archived";

type DAGNode = {
  id: string;
  role: string;
  name: string;
  agent_id: string | null;
  model: string | null;
  strategy: Strategy;
  prompt: string | null;
  config: Record<string, unknown>;
};

type DAGEdge = {
  id: string;
  from_node: string;
  to_node: string | null;
  condition: string | null;
};

type DAGFile = {
  id: string;
  name: string;
  description: string;
  nodes: DAGNode[];
  edges: DAGEdge[];
  entry_node: string | null;
  max_cycles: number;
  run_scout: boolean;
  status: DagStatus;
  created_at: string;
  updated_at: string;
};

type Agent = {
  id: string;
  name: string;
  model: string;
  status: string;
};

const ROLE_ICONS: Record<string, string> = {
  queen: "\u265B",
  worker: "\u25CF",
  scout: "\u25C7",
  drone: "\u25CB",
  guard: "\u25B2",
};

const NODE_W = 140;
const NODE_H = 64;
const CANVAS_PAD = 40;

const inp = {
  width: "100%",
  padding: "6px 10px",
  fontFamily: "var(--mono)" as const,
  fontSize: 10,
  background: "var(--paper-2, #f5f5f0)",
  border: "1.3px solid var(--rule)",
  borderRadius: 4,
  color: "var(--ink)",
  boxSizing: "border-box" as const,
};

const lbl = {
  fontFamily: "var(--mono)" as const,
  fontSize: 9,
  color: "var(--pencil)",
  textTransform: "uppercase" as const,
  marginBottom: 3,
  display: "block" as const,
};

const btn = {
  padding: "5px 14px",
  borderRadius: 4,
  cursor: "pointer" as const,
  fontFamily: "var(--mono)" as const,
  fontSize: 10,
  border: "1.3px solid",
};

function nodePos(node: DAGNode): { x: number; y: number } {
  const cfg = node.config as Record<string, unknown>;
  const pos = cfg._pos as { x: number; y: number } | undefined;
  return pos ?? { x: 100, y: 100 };
}

function setNodePos(node: DAGNode, x: number, y: number): DAGNode {
  return { ...node, config: { ...node.config, _pos: { x, y } } };
}

function statusVariant(s: DagStatus): "ok" | "warn" | "muted" | "accent" {
  if (s === "active") return "ok";
  if (s === "draft") return "warn";
  return "muted";
}

function fmtRelative(iso: string): string {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function DagBuilder() {
  const toast = useToast();
  const [dags, setDags] = useState<DAGFile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dag, setDag] = useState<DAGFile | null>(null);
  const [loading, setLoading] = useState(true);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [propsOpen, setPropsOpen] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [cName, setCName] = useState("");
  const [cDesc, setCDesc] = useState("");
  const [cBusy, setCBusy] = useState(false);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState<Role>("worker");
  const [editStrategy, setEditStrategy] = useState<Strategy>("react");
  const [editModel, setEditModel] = useState("");
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [editPrompt, setEditPrompt] = useState("");
  const [editAgentId, setEditAgentId] = useState<string>("");
  const [addEdgeTarget, setAddEdgeTarget] = useState<string | null>(null);
  const [execState, setExecState] = useState<{ running: boolean; nodeId: string | null; log: string[] }>({ running: false, nodeId: null, log: [] });
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ nodeId: string; offX: number; offY: number } | null>(null);

  const loadDags = useCallback(async () => {
    try {
      setLoading(true);
      setDags(await apiGet<DAGFile[]>("/v1/dags"));
    } catch {
      toast("Failed to load DAGs", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  const loadAgents = useCallback(async () => {
    try {
      setAgents(await apiGet<Agent[]>("/v1/agents"));
    } catch (e) {
      // Swallowing this left the node-type picker empty with no explanation:
      // the builder renders fine, offers no agents, and looks like the fleet
      // is empty rather than unreachable.
      toast(`Could not load agents: ${e instanceof Error ? e.message : String(e)}`, "error");
    }
  }, [toast]);

  useEffect(() => {
    loadDags();
    loadAgents();
    apiGet<{ models: string[] }>("/v1/settings/models").then((r) => setAvailableModels(r.models)).catch(() => {});
  }, [loadDags, loadAgents]);

  useEffect(() => {
    if (!selectedId) {
      setDag(null);
      setSelectedNode(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const d = await apiGet<DAGFile>(`/v1/dags/${selectedId}`);
        if (!cancelled) setDag(d);
      } catch {
        toast("Failed to load DAG", "error");
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId, toast]);

  useEffect(() => {
    if (!dag || !selectedNode) return;
    const node = dag.nodes.find((n) => n.id === selectedNode);
    if (!node) {
      setSelectedNode(null);
      return;
    }
    setEditName(node.name);
    setEditRole((node.role as Role) || "worker");
    setEditStrategy(node.strategy || "react");
    setEditModel(node.model ?? "");
    setEditPrompt(node.prompt ?? "");
    setEditAgentId(node.agent_id ?? "");
  }, [dag, selectedNode]);

  const handleSaveDag = useCallback(async (updated: DAGFile) => {
    setSaving(true);
    try {
      const saved = await apiPut<DAGFile>(`/v1/dags/${updated.id}`, updated);
      setDag(saved);
      setDags((prev) => prev.map((d) => (d.id === saved.id ? saved : d)));
      toast("DAG saved");
    } catch {
      toast("Save failed", "error");
    } finally {
      setSaving(false);
    }
  }, [toast]);

  const handleDeleteDag = useCallback(async () => {
    if (!deleteId) return;
    try {
      await apiDelete(`/v1/dags/${deleteId}`);
      toast("DAG deleted");
      if (selectedId === deleteId) {
        setSelectedId(null);
        setDag(null);
      }
      setDags((prev) => prev.filter((d) => d.id !== deleteId));
    } catch {
      toast("Delete failed", "error");
    }
    setDeleteId(null);
  }, [deleteId, selectedId, toast]);

  const handleCreate = useCallback(async () => {
    setCBusy(true);
    try {
      const created = await apiPost<DAGFile>("/v1/dags", { name: cName, description: cDesc });
      setDags((prev) => [...prev, created]);
      setSelectedId(created.id);
      setShowCreate(false);
      setCName("");
      setCDesc("");
      toast("DAG created");
    } catch {
      toast("Create failed", "error");
    } finally {
      setCBusy(false);
    }
  }, [cName, cDesc, toast]);

  const handleAddNode = useCallback(async () => {
    if (!dag) return;
    const offset = dag.nodes.length * 30;
    try {
      const node = await apiPost<DAGNode>(`/v1/dags/${dag.id}/nodes`, {
        name: `node_${dag.nodes.length + 1}`,
        role: "worker",
        strategy: "react",
        config: { _pos: { x: 160 + offset, y: 120 + offset } },
      });
      setDag((prev) => prev ? { ...prev, nodes: [...prev.nodes, node] } : prev);
      setSelectedNode(node.id);
      setPropsOpen(true);
      toast("Node added");
    } catch {
      toast("Failed to add node", "error");
    }
  }, [dag, toast]);

  const handleDeleteNode = useCallback(async () => {
    if (!dag || !selectedNode) return;
    try {
      await apiDelete(`/v1/dags/${dag.id}/nodes/${selectedNode}`);
      setDag((prev) => prev
        ? {
            ...prev,
            nodes: prev.nodes.filter((n) => n.id !== selectedNode),
            edges: prev.edges.filter((e) => e.from_node !== selectedNode && e.to_node !== selectedNode),
            entry_node: prev.entry_node === selectedNode ? null : prev.entry_node,
          }
        : prev);
      setSelectedNode(null);
      toast("Node deleted");
    } catch {
      toast("Delete node failed", "error");
    }
  }, [dag, selectedNode, toast]);

  const handleAddEdge = useCallback(async (targetId: string) => {
    if (!dag || !selectedNode) return;
    try {
      const edge = await apiPost<DAGEdge>(`/v1/dags/${dag.id}/edges`, {
        from_node: selectedNode,
        to_node: targetId,
      });
      setDag((prev) => prev ? { ...prev, edges: [...prev.edges, edge] } : prev);
      setAddEdgeTarget(null);
      toast("Edge added");
    } catch {
      toast("Add edge failed", "error");
    }
  }, [dag, selectedNode, toast]);

  const handleRun = useCallback(() => {
    if (!dag) return;
    const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${location.host}/v1/ws/dags/${dag.id}/run`;
    const ws = new WebSocket(wsUrl);
    setExecState({ running: true, nodeId: null, log: ["Connecting..."] });
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.error) {
          setExecState((prev) => ({ ...prev, running: false, log: [...prev.log, `Error: ${data.error}`] }));
          return;
        }
        if (data.status === "started") {
          setExecState((prev) => ({ ...prev, log: [...prev.log, `Started (${data.node_count} nodes)`] }));
        } else if (data.status === "node_complete") {
          setExecState((prev) => ({
            ...prev,
            nodeId: data.node_id,
            log: [...prev.log, `${data.role} (${data.node_id.slice(0, 8)}): ${data.success ? "OK" : "FAIL"}`],
          }));
        } else if (data.status === "completed") {
          setExecState((prev) => ({ ...prev, running: false, nodeId: null, log: [...prev.log, `Completed in ${data.cycles} cycles`] }));
          toast("DAG execution completed");
        } else if (data.status === "failed") {
          setExecState((prev) => ({ ...prev, running: false, log: [...prev.log, `Failed: ${data.error}`] }));
          toast("DAG execution failed", "error");
        }
      } catch { /* ignore parse errors */ }
    };
    ws.onerror = () => {
      setExecState((prev) => ({ ...prev, running: false, log: [...prev.log, "Connection error"] }));
      toast("WebSocket error", "error");
    };
    ws.onclose = () => {
      setExecState((prev) => prev.running ? { ...prev, running: false, log: [...prev.log, "Connection closed"] } : prev);
    };
  }, [dag, toast]);

  const handleActivate = useCallback(async () => {
    if (!dag) return;
    try {
      await apiPost(`/v1/dags/${dag.id}/activate`);
      setDag((prev) => prev ? { ...prev, status: "active" } : prev);
      setDags((prev) => prev.map((d) => (d.id === dag.id ? { ...d, status: "active" } : d)));
      toast("DAG activated");
    } catch {
      toast("Activate failed", "error");
    }
  }, [dag, toast]);

  const handleNodePropsSave = useCallback(() => {
    if (!dag || !selectedNode) return;
    const updatedNodes = dag.nodes.map((n) => {
      if (n.id !== selectedNode) return n;
      return {
        ...n,
        name: editName,
        role: editRole,
        strategy: editStrategy,
        model: editModel || null,
        prompt: editPrompt || null,
        agent_id: editAgentId || null,
      };
    });
    handleSaveDag({ ...dag, nodes: updatedNodes });
  }, [dag, selectedNode, editName, editRole, editStrategy, editModel, editPrompt, editAgentId, handleSaveDag]);

  const handleDagNameChange = useCallback((name: string) => {
    if (!dag) return;
    handleSaveDag({ ...dag, name });
  }, [dag, handleSaveDag]);

  const handleMouseDown = useCallback((nodeId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const node = dag?.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const pos = nodePos(node);
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    dragRef.current = {
      nodeId,
      offX: e.clientX - rect.left - pos.x,
      offY: e.clientY - rect.top - pos.y,
    };
    setSelectedNode(nodeId);
    setPropsOpen(true);
  }, [dag]);

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag || !dag) return;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left - drag.offX;
    const y = e.clientY - rect.top - drag.offY;
    setDag((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        nodes: prev.nodes.map((n) =>
          n.id === drag.nodeId ? setNodePos(n, x, y) : n
        ),
      };
    });
  }, [dag]);

  const handleMouseUp = useCallback(() => {
    if (dragRef.current && dag) {
      const node = dag.nodes.find((n) => n.id === dragRef.current!.nodeId);
      if (node) {
        handleSaveDag(dag);
      }
    }
    dragRef.current = null;
  }, [dag, handleSaveDag]);

  const isEntry = (nodeId: string) => dag?.entry_node === nodeId;
  const isTerminal = (nodeId: string) =>
    dag ? !dag.edges.some((e) => e.from_node === nodeId) : false;

  function renderEdge(edge: DAGEdge) {
    if (!dag) return null;
    const fromNode = dag.nodes.find((n) => n.id === edge.from_node);
    const toNode = dag.nodes.find((n) => n.id === edge.to_node);
    if (!fromNode) return null;
    const from = nodePos(fromNode);
    if (!toNode || !edge.to_node) {
      const tx = from.x + NODE_W + 60;
      const ty = from.y + NODE_H / 2;
      return (
        <g key={edge.id}>
          <line
            x1={from.x + NODE_W} y1={from.y + NODE_H / 2}
            x2={tx} y2={ty}
            stroke="var(--pencil)" strokeWidth={1.5} strokeDasharray="4 3"
          />
          <polygon
            points={`${tx},${ty - 4} ${tx + 8},${ty} ${tx},${ty + 4}`}
            fill="var(--pencil)"
          />
        </g>
      );
    }
    const to = nodePos(toNode);
    const x1 = from.x + NODE_W;
    const y1 = from.y + NODE_H / 2;
    const x2 = to.x;
    const y2 = to.y + NODE_H / 2;
    const cx = (x1 + x2) / 2;
    return (
      <g key={edge.id}>
        <path
          d={`M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`}
          fill="none" stroke="var(--accent)" strokeWidth={1.5}
        />
        <polygon
          points={`${x2},${y2 - 5} ${x2 + 8},${y2} ${x2},${y2 + 5}`}
          fill="var(--accent)"
        />
      </g>
    );
  }

  function renderNode(node: DAGNode) {
    const pos = nodePos(node);
    const entry = isEntry(node.id);
    const terminal = isTerminal(node.id);
    const selected = selectedNode === node.id;
    const executing = execState.nodeId === node.id;
    return (
      <g
        key={node.id}
        onMouseDown={(e) => handleMouseDown(node.id, e)}
        onClick={(e) => { e.stopPropagation(); setSelectedNode(node.id); setPropsOpen(true); }}
        style={{ cursor: "grab" }}
      >
        <rect
          x={pos.x} y={pos.y} width={NODE_W} height={NODE_H} rx={8}
          fill={executing ? "var(--accent)" : "var(--paper)"}
          stroke={selected ? "var(--accent)" : entry ? "var(--accent)" : terminal ? "var(--pencil)" : "var(--rule)"}
          strokeWidth={selected ? 2.5 : entry ? 2 : 1.3}
          strokeDasharray={terminal ? "4 3" : undefined}
        />
        {entry && (
          <rect
            x={pos.x - 3} y={pos.y - 3} width={NODE_W + 6} height={NODE_H + 6} rx={10}
            fill="none" stroke="var(--accent)" strokeWidth={1} strokeDasharray="2 2" opacity={0.5}
          />
        )}
        <text x={pos.x + 10} y={pos.y + 22} style={{ fontSize: 16 }}>
          {ROLE_ICONS[node.role] || "\u25CF"}
        </text>
        <text
          x={pos.x + 30} y={pos.y + 22}
          style={{ fontFamily: "var(--hand)", fontSize: 12, fontWeight: 700, fill: executing ? "var(--paper)" : "var(--ink)" }}
        >
          {node.name.length > 12 ? node.name.slice(0, 11) + "…" : node.name}
        </text>
        <text
          x={pos.x + 30} y={pos.y + 38}
          style={{ fontFamily: "var(--mono)", fontSize: 8, fill: "var(--pencil)" }}
        >
          {node.model || "no model"}
        </text>
        <circle
          cx={pos.x + NODE_W - 12} cy={pos.y + 12} r={4}
          fill={selected ? "var(--accent)" : "var(--pencil)"}
        />
      </g>
    );
  }

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader title="DAG Builder" subtitle={`${dags.length} workflows — chain tasks into automated pipelines`} helpHref="/docs#dags" />
      {loading ? (
        <LoadingSpinner />
      ) : (
        <div style={{ display: "flex", height: "calc(100vh - 120px)" }}>
          <aside style={{
            width: 260, minWidth: 260, borderRight: "1.3px solid var(--rule)",
            background: "var(--paper)", overflowY: "auto", display: "flex", flexDirection: "column",
          }}>
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "10px 12px", borderBottom: "1.3px solid var(--rule)",
            }}>
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--pencil)" }}>
                DAG PIPELINES
              </span>
              <button
                onClick={() => setShowCreate(true)}
                style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)", fontSize: 9, padding: "3px 10px" }}
              >
                New +
              </button>
            </div>
            <div style={{ flex: 1, overflowY: "auto" }}>
              {dags.length === 0 ? (
                <EmptyState icon="△" title="No DAGs" action="Create One" onAction={() => setShowCreate(true)} />
              ) : (
                dags.map((d) => (
                  <div
                    key={d.id}
                    onClick={() => { setSelectedId(d.id); setSelectedNode(null); }}
                    style={{
                      padding: "10px 12px", cursor: "pointer",
                      borderBottom: "1px solid var(--rule)",
                      borderLeft: selectedId === d.id ? "3px solid var(--accent)" : "3px solid transparent",
                      background: selectedId === d.id ? "rgba(var(--accent-rgb, 212,160,23),0.06)" : "transparent",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontFamily: "var(--hand)", fontSize: 14, fontWeight: 700 }}>
                        {d.name}
                      </span>
                      <Hex variant={statusVariant(d.status)}>{d.status}</Hex>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>
                      <span>{d.nodes.length} nodes</span>
                      <span>{fmtRelative(d.updated_at)}</span>
                    </div>
                    <div style={{ marginTop: 6, display: "flex", justifyContent: "flex-end" }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeleteId(d.id); }}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--pencil)", fontSize: 12, padding: "2px 4px" }}
                      >
                        {"\uD83D\uDDD1\uFE0F"}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </aside>

          <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {dag ? (
              <>
                <div style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "8px 12px", borderBottom: "1.3px solid var(--rule)",
                  background: "var(--paper-2, #f5f5f0)",
                }}>
                  <input
                    value={dag.name}
                    onChange={(e) => setDag((prev) => prev ? { ...prev, name: e.target.value } : prev)}
                    onBlur={(e) => handleDagNameChange(e.target.value)}
                    style={{
                      fontFamily: "var(--hand)", fontSize: 16, fontWeight: 700,
                      background: "transparent", border: "none", outline: "none", color: "var(--ink)", width: 200,
                    }}
                  />
                  <Hex variant={statusVariant(dag.status)}>{dag.status}</Hex>
                  <div style={{ flex: 1 }} />
                  <button onClick={handleAddNode} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>
                    + Add Node
                  </button>
                  <button onClick={handleRun} disabled={execState.running} style={{ ...btn, background: execState.running ? "var(--pencil)" : "var(--accent)", color: "var(--paper)", borderColor: execState.running ? "var(--pencil)" : "var(--accent)", cursor: execState.running ? "not-allowed" : "pointer" }}>
                    {execState.running ? "\u23F3 Running..." : "\u25B6 Run DAG"}
                  </button>
                  {execState.log.length > 0 && (
                    <div style={{ position: "absolute", top: 38, right: 0, width: 320, maxHeight: 200, overflow: "auto", background: "var(--paper)", border: "1px solid var(--rule)", borderRadius: 4, padding: 6, zIndex: 10, fontFamily: "var(--mono)", fontSize: 9 }}>
                      {execState.log.map((line, i) => (
                        <div key={i} style={{ color: line.startsWith("Error") || line.startsWith("Failed") ? "var(--danger, #c4452a)" : "var(--ink)" }}>{line}</div>
                      ))}
                    </div>
                  )}
                  {dag.status !== "active" && (
                    <button onClick={handleActivate} style={{ ...btn, background: "#5a9a4a", color: "var(--paper)", borderColor: "#5a9a4a" }}>
                      Activate
                    </button>
                  )}
                  <button
                    onClick={() => {
                      if (!svgRef.current) return;
                      setDag((prev) => {
                        if (!prev) return prev;
                        const xs = prev.nodes.map((n) => nodePos(n).x);
                        const ys = prev.nodes.map((n) => nodePos(n).y);
                        if (xs.length === 0) return prev;
                        const minX = Math.min(...xs);
                        const minY = Math.min(...ys);
                        return {
                          ...prev,
                          nodes: prev.nodes.map((n) => {
                            const p = nodePos(n);
                            return setNodePos(n, p.x - minX + CANVAS_PAD, p.y - minY + CANVAS_PAD);
                          }),
                        };
                      });
                    }}
                    style={{ ...btn, background: "var(--paper)", color: "var(--pencil)", borderColor: "var(--rule)" }}
                  >
                    Fit
                  </button>
                </div>

                <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                  <svg
                    ref={svgRef}
                    style={{ width: "100%", height: "100%", background: "var(--paper-2, #f5f5f0)" }}
                    onMouseMove={handleMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseUp}
                    onClick={() => { setSelectedNode(null); setAddEdgeTarget(null); }}
                  >
                    <defs>
                      <pattern id="dag-grid" width={20} height={20} patternUnits="userSpaceOnUse">
                        <circle cx={10} cy={10} r={0.8} fill="var(--rule)" />
                      </pattern>
                    </defs>
                    <rect width="100%" height="100%" fill="url(#dag-grid)" />
                    {dag.edges.map(renderEdge)}
                    {dag.nodes.map(renderNode)}
                  </svg>
                </div>

                {selectedNode && propsOpen && (() => {
                  const node = dag.nodes.find((n) => n.id === selectedNode);
                  if (!node) return null;
                  const otherNodes = dag.nodes.filter((n) => n.id !== selectedNode);
                  const existingTargets = new Set(
                    dag.edges.filter((e) => e.from_node === selectedNode && e.to_node).map((e) => e.to_node!)
                  );
                  return (
                    <div style={{
                      height: 200, minHeight: 200, borderTop: "1.3px solid var(--rule)",
                      background: "var(--paper)", display: "flex", flexDirection: "column",
                      overflow: "hidden",
                    }}>
                      <div style={{
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                        padding: "6px 12px", borderBottom: "1px solid var(--rule)",
                      }}>
                        <span style={{ fontFamily: "var(--mono)", fontSize: 9, fontWeight: 700, color: "var(--pencil)", textTransform: "uppercase" }}>
                          Node Properties \u2014 {node.name}
                        </span>
                        <button
                          onClick={() => setPropsOpen(false)}
                          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--pencil)", fontSize: 12 }}
                        >
                          {"\u25BC"}
                        </button>
                      </div>
                      <div style={{ flex: 1, overflowY: "auto", padding: "8px 12px" }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                          <div>
                            <label style={lbl}>Name</label>
                            <input value={editName} onChange={(e) => setEditName(e.target.value)} style={inp} />
                          </div>
                          <div>
                            <label style={lbl}>Role</label>
                            <select value={editRole} onChange={(e) => setEditRole(e.target.value as Role)} style={{ ...inp, height: 28 }}>
                              {(["queen", "worker", "scout", "drone", "guard"] as Role[]).map((r) => (
                                <option key={r} value={r}>{ROLE_ICONS[r]} {r}</option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label style={lbl}>Agent</label>
                            <select value={editAgentId} onChange={(e) => setEditAgentId(e.target.value)} style={{ ...inp, height: 28 }}>
                              <option value="">None</option>
                              {agents.map((a) => (
                                <option key={a.id} value={a.id}>{a.name}</option>
                              ))}
                            </select>
                          </div>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 6 }}>
                          <div>
                            <label style={lbl}>Strategy</label>
                            <div style={{ display: "flex", gap: 4 }}>
                              {(["react", "plan_execute", "direct", "delegate"] as Strategy[]).map((s) => (
                                <label key={s} style={{
                                  display: "inline-flex", alignItems: "center", gap: 3,
                                  padding: "3px 8px", borderRadius: 3, cursor: "pointer",
                                  fontFamily: "var(--mono)", fontSize: 9,
                                  background: editStrategy === s ? "var(--accent)" : "var(--paper-2, #f5f5f0)",
                                  color: editStrategy === s ? "var(--paper)" : "var(--ink)",
                                  border: `1px solid ${editStrategy === s ? "var(--accent)" : "var(--rule)"}`,
                                }}>
                                  <input type="radio" name="strategy" checked={editStrategy === s} onChange={() => setEditStrategy(s)} style={{ display: "none" }} />
                                  {s}
                                </label>
                              ))}
                            </div>
                          </div>
                          <div>
                            <label style={lbl}>Model</label>
                            <select value={editModel} onChange={(e) => setEditModel(e.target.value)} style={inp}>
                              <option value="">Default ({availableModels[0] || "—"})</option>
                              {availableModels.map((m) => <option key={m} value={m}>{m}</option>)}
                            </select>
                          </div>
                        </div>
                        <div style={{ marginTop: 6 }}>
                          <label style={lbl}>Prompt</label>
                          <textarea
                            value={editPrompt}
                            onChange={(e) => setEditPrompt(e.target.value)}
                            rows={2}
                            style={{ ...inp, resize: "vertical" as const }}
                          />
                        </div>
                        <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
                          <button
                            disabled={saving}
                            onClick={handleNodePropsSave}
                            style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}
                          >
                            {saving ? "Saving..." : "Save"}
                          </button>
                          <button
                            onClick={handleDeleteNode}
                            style={{ ...btn, background: "var(--paper)", color: "#c4452a", borderColor: "#c4452a" }}
                          >
                            Delete Node
                          </button>
                          {otherNodes.length > 0 && (
                            <div style={{ position: "relative" }}>
                              <button
                                onClick={() => setAddEdgeTarget(addEdgeTarget === "open" ? null : "open")}
                                style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}
                              >
                                + Add Edge To...
                              </button>
                              {addEdgeTarget === "open" && (
                                <div style={{
                                  position: "absolute", bottom: "100%", left: 0, marginBottom: 4,
                                  background: "var(--paper)", border: "1.3px solid var(--rule)",
                                  borderRadius: 4, boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
                                  minWidth: 160, zIndex: 50,
                                }}>
                                  {otherNodes
                                    .filter((n) => !existingTargets.has(n.id))
                                    .map((n) => (
                                      <div
                                        key={n.id}
                                        onClick={() => handleAddEdge(n.id)}
                                        style={{
                                          padding: "6px 10px", cursor: "pointer",
                                          fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink)",
                                          borderBottom: "1px solid var(--rule)",
                                        }}
                                        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--paper-2, #f5f5f0)")}
                                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                      >
                                        {ROLE_ICONS[n.role]} {n.name}
                                      </div>
                                    ))}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {!propsOpen && selectedNode && (
                  <div
                    onClick={() => setPropsOpen(true)}
                    style={{
                      height: 28, borderTop: "1.3px solid var(--rule)", background: "var(--paper)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: "pointer", fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)",
                    }}
                  >
                    {"\u25B2 Show Properties"}
                  </div>
                )}
              </>
            ) : (
              <EmptyState icon="△" title="Select a DAG or create a new one" />
            )}
          </main>
        </div>
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create DAG Pipeline">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div>
            <label style={lbl}>Name</label>
            <input value={cName} onChange={(e) => setCName(e.target.value)} style={inp} placeholder="Pipeline name" />
          </div>
          <div>
            <label style={lbl}>Description</label>
            <textarea value={cDesc} onChange={(e) => setCDesc(e.target.value)} rows={3} style={{ ...inp, resize: "vertical" as const }} placeholder="What does this pipeline do?" />
          </div>
          <div style={{ textAlign: "right", marginTop: 8 }}>
            <button
              disabled={!cName.trim() || cBusy}
              onClick={handleCreate}
              style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)", opacity: cName.trim() ? 1 : 0.5 }}
            >
              {cBusy ? "Creating..." : "Create DAG"}
            </button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={deleteId !== null}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDeleteDag}
        title="Delete DAG"
        message="This will permanently delete this DAG pipeline and all its nodes and edges. This cannot be undone."
      />
    </div>
  );
}
