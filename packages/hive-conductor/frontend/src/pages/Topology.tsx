import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../lib/api";
import { PageHeader, Card, Hex, StatusDot, LoadingSpinner, useToast } from "../components/shared";

type Agent = {
  id: string;
  name: string;
  description: string;
  model: string;
  status: string;
  capabilities: string[];
  skills: string[];
  tasks_completed: number;
  config: Record<string, unknown>;
};

type MCPServer = {
  id: string;
  name: string;
  url: string;
  status: string;
  tools_count: number;
};

type Skill = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
};

type Role = "queen" | "worker" | "scout" | "drone" | "guard";

type Edge = {
  sourceId: string;
  targetId: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  style: "solid" | "dashed" | "queen" | "guard";
  color: string;
  width: number;
};

type TooltipInfo = {
  name: string;
  model?: string;
  status?: string;
  tasks?: number;
  caps?: string[];
  sk?: string[];
  connections?: number;
} | null;

const ROLE_CONFIG: Record<Role, { radius: number; fill: string; glyph: string }> = {
  queen: { radius: 65, fill: "var(--accent)", glyph: "\u265B" },
  worker: { radius: 50, fill: "var(--ink)", glyph: "\u25CF" },
  scout: { radius: 50, fill: "#3a8f5a", glyph: "\u25C7" },
  drone: { radius: 45, fill: "var(--pencil)", glyph: "\u25CB" },
  guard: { radius: 50, fill: "#5b8fb3", glyph: "\u25B2" },
};

const EXTERNAL_SERVICES = [
  { name: "LiteLLM", y: 100 },
  { name: "Home Assistant", y: 190 },
  { name: "Langfuse", y: 280 },
  { name: "Cloudflare", y: 370 },
];

const LEGEND_ITEMS: { label: string; glyph: string; fill: string }[] = [
  { label: "Queen", glyph: "\u265B", fill: "var(--accent)" },
  { label: "Worker", glyph: "\u25CF", fill: "var(--ink)" },
  { label: "Scout", glyph: "\u25C7", fill: "#3a8f5a" },
  { label: "Drone", glyph: "\u25CB", fill: "var(--pencil)" },
  { label: "Guard", glyph: "\u25B2", fill: "#5b8fb3" },
];

function getRole(agent: Agent): Role {
  const n = agent.name.toLowerCase();
  const caps = agent.capabilities.map((c) => c.toLowerCase());
  if (n.includes("conductor") || n.includes("orchestrator") || n.includes("queen")) return "queen";
  if (caps.includes("security") || n.includes("guard") || n.includes("bouncer") || n.includes("redteam") || n.includes("sentinel")) return "guard";
  if (caps.includes("research") || n.includes("scout") || n.includes("phantom") || n.includes("researcher")) return "scout";
  if (caps.includes("monitoring") || n.includes("heartbeat") || n.includes("dreamloop") || n.includes("monitor")) return "drone";
  return "worker";
}

function getPosition(agent: Agent, allAgents: Agent[]): { x: number; y: number } {
  const role = getRole(agent);
  const sameRole = allAgents.filter((a) => getRole(a) === role);
  const idx = sameRole.findIndex((a) => a.id === agent.id);
  switch (role) {
    case "queen":
      return { x: 400, y: 80 };
    case "worker":
      return { x: 220 + idx * 160, y: 250 };
    case "guard":
      return { x: 80 + idx * 140, y: 250 };
    case "scout":
      return { x: 560 + idx * 140, y: 250 };
    case "drone":
      return { x: 300 + idx * 160, y: 420 };
  }
}

function hexPoints(cx: number, cy: number, r: number): string {
  const pts: string[] = [];
  for (let i = 0; i < 6; i++) {
    const angle = -Math.PI / 2 + (i * Math.PI) / 3;
    pts.push(`${(cx + r * Math.cos(angle)).toFixed(1)},${(cy + r * Math.sin(angle)).toFixed(1)}`);
  }
  return pts.join(" ");
}

function curvePath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = x2 - x1;
  return `M${x1},${y1} C${x1 + dx * 0.35},${y1} ${x1 + dx * 0.65},${y2} ${x2},${y2}`;
}

function dotColor(status: string): string {
  if (status === "busy" || status === "running") return "var(--accent)";
  if (status === "error") return "#c4452a";
  return "var(--pencil)";
}

function mapStatus(s: string): "running" | "idle" | "error" | "busy" {
  if (s === "busy") return "busy";
  if (s === "running") return "running";
  if (s === "error") return "error";
  return "idle";
}

export default function Topology() {
  const navigate = useNavigate();
  const toast = useToast();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipInfo>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  const loadData = useCallback(async () => {
    try {
      const [a, s, sk] = await Promise.all([
        apiGet<Agent[]>("/v1/agents"),
        apiGet<MCPServer[]>("/v1/mcp/servers"),
        apiGet<Skill[]>("/v1/skills"),
      ]);
      setAgents(a);
      setServers(s);
      setSkills(sk);
    } catch (e) {
      // Promise.all means any one of the three endpoints failing produced a
      // completely blank topology — and `setLoading(false)` below then renders
      // that emptiness as the answer rather than as a failure.
      toast(`Could not load topology: ${e instanceof Error ? e.message : String(e)}`, "error");
    }
    setLoading(false);
  }, [toast]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const positions = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    agents.forEach((a) => m.set(a.id, getPosition(a, agents)));
    servers.forEach((s, i) => m.set(`srv:${s.id}`, { x: 700, y: 80 + i * 90 }));
    skills.forEach((sk, i) => m.set(`sk:${sk.id}`, { x: 250 + (i % 4) * 110, y: 530 + Math.floor(i / 4) * 50 }));
    EXTERNAL_SERVICES.forEach((svc) => m.set(`ext:${svc.name}`, { x: 60, y: svc.y }));
    return m;
  }, [agents, servers, skills]);

  const edgeList = useMemo(() => {
    const result: Edge[] = [];
    const queen = agents.find((a) => getRole(a) === "queen");
    const queenPos = queen ? positions.get(queen.id) : null;

    agents.forEach((agent) => {
      const pos = positions.get(agent.id);
      if (!pos) return;
      const role = getRole(agent);

      if (queen && queenPos && role !== "queen" && role !== "guard") {
        result.push({
          sourceId: queen.id,
          targetId: agent.id,
          x1: queenPos.x,
          y1: queenPos.y + ROLE_CONFIG.queen.radius,
          x2: pos.x,
          y2: pos.y - ROLE_CONFIG[role].radius,
          style: "queen",
          color: "var(--accent)",
          width: 2,
        });
      }

      if (role === "guard" && queen && queenPos) {
        result.push({
          sourceId: agent.id,
          targetId: queen.id,
          x1: pos.x,
          y1: pos.y - ROLE_CONFIG.guard.radius,
          x2: queenPos.x,
          y2: queenPos.y + ROLE_CONFIG.queen.radius,
          style: "guard",
          color: "#5b8fb3",
          width: 1.2,
        });
      }

      agent.capabilities.forEach((cap) => {
        const srv = servers.find((s) => s.name.toLowerCase().includes(cap.toLowerCase()));
        if (srv) {
          const sp = positions.get(`srv:${srv.id}`);
          if (sp) {
            result.push({
              sourceId: agent.id,
              targetId: `srv:${srv.id}`,
              x1: pos.x + ROLE_CONFIG[role].radius,
              y1: pos.y,
              x2: sp.x - 35,
              y2: sp.y,
              style: "solid",
              color: "var(--rule)",
              width: 1.2,
            });
          }
        }
      });

      agent.skills.forEach((sn) => {
        const sk = skills.find((s) => s.name.toLowerCase() === sn.toLowerCase() || s.id === sn);
        if (sk) {
          const sp = positions.get(`sk:${sk.id}`);
          if (sp) {
            result.push({
              sourceId: agent.id,
              targetId: `sk:${sk.id}`,
              x1: pos.x,
              y1: pos.y + ROLE_CONFIG[role].radius,
              x2: sp.x + 40,
              y2: sp.y,
              style: "dashed",
              color: "var(--pencil)",
              width: 1,
            });
          }
        }
      });
    });

    return result;
  }, [agents, servers, skills, positions]);

  const isEdgeActive = (edge: Edge) => {
    if (!hoveredId) return false;
    return edge.sourceId === hoveredId || edge.targetId === hoveredId;
  };

  if (loading) return <LoadingSpinner />;

  return (
    <div>
      <PageHeader title="Topology" subtitle="Visual map of how agents, skills, and services connect" helpHref="/docs#topology" />
      <div style={{ position: "relative", width: "100%", height: "calc(100vh - 100px)", overflow: "hidden" }}>
        <svg
          width="100%"
          height="calc(100vh - 100px)"
          viewBox="0 0 800 620"
          preserveAspectRatio="xMidYMid meet"
          style={{ display: "block" }}
        >
          <defs>
            <marker id="topo-arrow-rule" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <path d="M0,0 L8,3 L0,6" fill="var(--rule)" />
            </marker>
            <marker id="topo-arrow-accent" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
              <path d="M0,0 L10,3.5 L0,7" fill="var(--accent)" />
            </marker>
            <marker id="topo-arrow-pencil" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <path d="M0,0 L8,3 L0,6" fill="var(--pencil)" />
            </marker>
            <marker id="topo-arrow-blue" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <path d="M0,0 L8,3 L0,6" fill="#5b8fb3" />
            </marker>
          </defs>

          {edgeList.map((edge, i) => {
            const active = isEdgeActive(edge);
            const markerId = edge.style === "queen"
              ? "topo-arrow-accent"
              : edge.style === "guard"
                ? "topo-arrow-blue"
                : edge.style === "dashed"
                  ? "topo-arrow-pencil"
                  : "topo-arrow-rule";
            const dash = edge.style === "dashed"
              ? "6,4"
              : edge.style === "guard"
                ? "2,3"
                : "none";
            return (
              <path
                key={`edge-${i}`}
                d={curvePath(edge.x1, edge.y1, edge.x2, edge.y2)}
                fill="none"
                stroke={edge.color}
                strokeWidth={edge.width}
                strokeDasharray={dash}
                markerEnd={`url(#${markerId})`}
                opacity={hoveredId ? (active ? 1 : 0.08) : 0.4}
                style={{ transition: "opacity 0.2s ease" }}
              />
            );
          })}

          {EXTERNAL_SERVICES.map((svc) => {
            const pos = positions.get(`ext:${svc.name}`);
            if (!pos) return null;
            const isHov = hoveredId === `ext:${svc.name}`;
            const conns = edgeList.filter((e) => e.targetId === `ext:${svc.name}`).length;
            return (
              <g
                key={`ext:${svc.name}`}
                onMouseEnter={() => setHoveredId(`ext:${svc.name}`)}
                onMouseLeave={() => { setHoveredId(null); setTooltip(null); }}
                onMouseMove={(e) => {
                  setTooltipPos({ x: e.clientX, y: e.clientY });
                  setTooltip({ name: svc.name, connections: conns });
                }}
              >
                <rect
                  x={pos.x}
                  y={pos.y}
                  width={100}
                  height={35}
                  rx={6}
                  fill="var(--paper)"
                  stroke={isHov ? "var(--accent)" : "var(--rule)"}
                  strokeWidth={isHov ? 2 : 1}
                  style={{ transition: "stroke 0.15s" }}
                />
                <text
                  x={pos.x + 50}
                  y={pos.y + 21}
                  textAnchor="middle"
                  fontSize={8.5}
                  fontFamily="var(--mono)"
                  fill="var(--ink)"
                  style={{ pointerEvents: "none" }}
                >
                  {svc.name}
                </text>
              </g>
            );
          })}

          {servers.map((srv) => {
            const pos = positions.get(`srv:${srv.id}`);
            if (!pos) return null;
            const isHov = hoveredId === `srv:${srv.id}`;
            const conns = edgeList.filter((e) => e.targetId === `srv:${srv.id}`).length;
            return (
              <g
                key={`srv:${srv.id}`}
                onMouseEnter={() => setHoveredId(`srv:${srv.id}`)}
                onMouseLeave={() => { setHoveredId(null); setTooltip(null); }}
                onMouseMove={(e) => {
                  setTooltipPos({ x: e.clientX, y: e.clientY });
                  setTooltip({ name: srv.name, connections: conns });
                }}
              >
                <polygon
                  points={hexPoints(pos.x, pos.y, 35)}
                  fill="var(--paper)"
                  stroke={isHov ? "var(--accent)" : "var(--ink)"}
                  strokeWidth={isHov ? 2 : 1}
                  style={{ transition: "stroke 0.15s" }}
                />
                <text
                  x={pos.x}
                  y={pos.y - 2}
                  textAnchor="middle"
                  fontSize={9}
                  fontFamily="var(--mono)"
                  fontWeight={600}
                  fill="var(--ink)"
                  style={{ pointerEvents: "none" }}
                >
                  {srv.name.length > 8 ? srv.name.slice(0, 7) + "\u2026" : srv.name}
                </text>
                <text
                  x={pos.x}
                  y={pos.y + 12}
                  textAnchor="middle"
                  fontSize={7}
                  fontFamily="var(--mono)"
                  fill="var(--pencil)"
                  style={{ pointerEvents: "none" }}
                >
                  {srv.tools_count} tools
                </text>
              </g>
            );
          })}

          {skills.map((sk) => {
            const pos = positions.get(`sk:${sk.id}`);
            if (!pos) return null;
            const isHov = hoveredId === `sk:${sk.id}`;
            const conns = edgeList.filter((e) => e.targetId === `sk:${sk.id}`).length;
            return (
              <g
                key={`sk:${sk.id}`}
                onMouseEnter={() => setHoveredId(`sk:${sk.id}`)}
                onMouseLeave={() => { setHoveredId(null); setTooltip(null); }}
                onMouseMove={(e) => {
                  setTooltipPos({ x: e.clientX, y: e.clientY });
                  setTooltip({ name: sk.name, connections: conns });
                }}
              >
                <rect
                  x={pos.x}
                  y={pos.y}
                  width={80}
                  height={30}
                  rx={5}
                  fill="var(--paper-2)"
                  stroke={isHov ? "var(--accent)" : "var(--rule)"}
                  strokeWidth={isHov ? 1.5 : 0.8}
                  style={{ transition: "stroke 0.15s" }}
                />
                <text
                  x={pos.x + 40}
                  y={pos.y + 19}
                  textAnchor="middle"
                  fontSize={7.5}
                  fontFamily="var(--mono)"
                  fill="var(--ink)"
                  style={{ pointerEvents: "none" }}
                >
                  {sk.name.length > 12 ? sk.name.slice(0, 11) + "\u2026" : sk.name}
                </text>
              </g>
            );
          })}

          {agents.map((agent) => {
            const pos = positions.get(agent.id);
            if (!pos) return null;
            const role = getRole(agent);
            const cfg = ROLE_CONFIG[role];
            const isHov = hoveredId === agent.id;
            return (
              <g
                key={agent.id}
                style={{ cursor: "pointer" }}
                onClick={() => navigate("/agents")}
                onMouseEnter={() => setHoveredId(agent.id)}
                onMouseLeave={() => { setHoveredId(null); setTooltip(null); }}
                onMouseMove={(e) => {
                  setTooltipPos({ x: e.clientX, y: e.clientY });
                  setTooltip({
                    name: agent.name,
                    model: agent.model,
                    status: agent.status,
                    tasks: agent.tasks_completed,
                    caps: agent.capabilities,
                    sk: agent.skills,
                  });
                }}
              >
                <circle
                  cx={pos.x}
                  cy={pos.y}
                  r={cfg.radius + (isHov ? 6 : 0)}
                  fill={cfg.fill}
                  opacity={isHov ? 0.16 : 0.06}
                  style={{ transition: "all 0.15s ease" }}
                />
                <circle
                  cx={pos.x}
                  cy={pos.y}
                  r={cfg.radius}
                  fill="transparent"
                  stroke={cfg.fill}
                  strokeWidth={isHov ? 2.5 : 1.5}
                  style={{ transition: "stroke-width 0.15s ease" }}
                />
                <text
                  x={pos.x}
                  y={pos.y - 6}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={role === "queen" ? 30 : 24}
                  fill={cfg.fill}
                  style={{ pointerEvents: "none" }}
                >
                  {cfg.glyph}
                </text>
                <text
                  x={pos.x}
                  y={pos.y + cfg.radius * 0.48}
                  textAnchor="middle"
                  fontSize={9.5}
                  fontFamily="var(--mono)"
                  fontWeight={600}
                  fill="var(--ink)"
                  style={{ pointerEvents: "none" }}
                >
                  {agent.name.length > 14 ? agent.name.slice(0, 13) + "\u2026" : agent.name}
                </text>
                <text
                  x={pos.x}
                  y={pos.y + cfg.radius * 0.48 + 13}
                  textAnchor="middle"
                  fontSize={7}
                  fontFamily="var(--mono)"
                  fill="var(--pencil)"
                  style={{ pointerEvents: "none" }}
                >
                  {agent.model.length > 18 ? agent.model.slice(0, 17) + "\u2026" : agent.model}
                </text>
                <circle
                  cx={pos.x + cfg.radius * 0.72}
                  cy={pos.y - cfg.radius * 0.72}
                  r={5}
                  fill="var(--paper)"
                  stroke={cfg.fill}
                  strokeWidth={1}
                />
                <circle
                  cx={pos.x + cfg.radius * 0.72}
                  cy={pos.y - cfg.radius * 0.72}
                  r={3}
                  fill={dotColor(agent.status)}
                  style={{ pointerEvents: "none" }}
                />
              </g>
            );
          })}
        </svg>

        {tooltip && (
          <div
            style={{
              position: "fixed",
              left: tooltipPos.x + 16,
              top: tooltipPos.y - 8,
              background: "var(--paper)",
              border: "1px solid var(--rule)",
              borderRadius: 6,
              padding: "8px 12px",
              fontFamily: "var(--mono)",
              fontSize: 10,
              color: "var(--ink)",
              pointerEvents: "none",
              zIndex: 50,
              boxShadow: "0 4px 16px rgba(0,0,0,0.15)",
              maxWidth: 320,
              lineHeight: 1.6,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
              {tooltip.status && <StatusDot status={mapStatus(tooltip.status)} pulse={tooltip.status === "busy"} />}
              {tooltip.name}
            </div>
            {tooltip.model && (
              <div style={{ color: "var(--pencil)", fontSize: 9 }}>{tooltip.model}</div>
            )}
            {tooltip.status && (
              <div style={{ color: "var(--pencil)", fontSize: 9 }}>status: {tooltip.status}</div>
            )}
            {tooltip.tasks !== undefined && (
              <div style={{ color: "var(--pencil)", fontSize: 9 }}>tasks completed: {tooltip.tasks}</div>
            )}
            {tooltip.caps && tooltip.caps.length > 0 && (
              <div style={{ color: "var(--pencil)", fontSize: 9 }}>capabilities: {tooltip.caps.join(", ")}</div>
            )}
            {tooltip.sk && tooltip.sk.length > 0 && (
              <div style={{ color: "var(--pencil)", fontSize: 9 }}>skills: {tooltip.sk.join(", ")}</div>
            )}
            {tooltip.connections !== undefined && (
              <div style={{ color: "var(--pencil)", fontSize: 9 }}>
                {tooltip.connections} connection{tooltip.connections !== 1 ? "s" : ""}
              </div>
            )}
          </div>
        )}

        <Card>
          <div
            style={{
              position: "absolute",
              top: 12,
              right: 12,
              background: "var(--paper)",
              border: "1px solid var(--rule)",
              borderRadius: 6,
              padding: "10px 14px",
              fontFamily: "var(--mono)",
              fontSize: 9,
              color: "var(--ink)",
              zIndex: 5,
              boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
              lineHeight: 1.8,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 6, fontSize: 10 }}>Legend</div>
            {LEGEND_ITEMS.map((item) => (
              <div key={item.label} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: 16,
                    height: 16,
                    borderRadius: "50%",
                    border: `1.5px solid ${item.fill}`,
                    color: item.fill,
                    fontSize: 9,
                  }}
                >
                  {item.glyph}
                </span>
                <span>{item.label}</span>
              </div>
            ))}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
              <Hex variant="muted">MCP</Hex>
              <span>MCP Server</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
              <span
                style={{
                  display: "inline-block",
                  width: 24,
                  height: 13,
                  borderRadius: 3,
                  background: "var(--paper-2)",
                  border: "0.8px solid var(--rule)",
                  fontSize: 6,
                  textAlign: "center",
                  lineHeight: "13px",
                  fontFamily: "var(--mono)",
                }}
              >
                sk
              </span>
              <span>Skill</span>
            </div>
            <div style={{ marginTop: 6, borderTop: "1px solid var(--rule)", paddingTop: 6, display: "flex", flexDirection: "column", gap: 2 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 18, height: 0, borderTop: "2px solid var(--accent)", display: "inline-block" }} />
                <span style={{ color: "var(--pencil)" }}>Queen link</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 18, height: 0, borderTop: "1.2px dashed var(--pencil)", display: "inline-block" }} />
                <span style={{ color: "var(--pencil)" }}>Skill link</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 18, height: 0, borderTop: "1.2px dotted #5b8fb3", display: "inline-block" }} />
                <span style={{ color: "var(--pencil)" }}>Guard link</span>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
