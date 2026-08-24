import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api";
import { useWorkspaces } from "../context/WorkspaceContext";
import {
  ConfirmDialog,
  EmptyState,
  LoadingSpinner,
  Modal,
  PageHeader,
  StatusDot,
  StatCard,
  Tabs,
  useToast,
} from "../components/shared";

type AgentStatus = "idle" | "busy" | "offline" | "error";
type Strategy = "react" | "plan_execute" | "direct" | "delegate";
type Role = "queen" | "worker" | "scout" | "drone" | "guard";

type Agent = {
  id: string;
  name: string;
  description: string;
  model: string;
  status: AgentStatus;
  capabilities: string[];
  skills: string[];
  current_mission: string | null;
  tasks_completed: number;
  avg_response_time_ms: number;
  last_active: string | null;
  created_at: string;
  config: Record<string, unknown>;
};

type IntentRow = {
  intent: string;
  agent: string;
  model: string;
  strategy: Strategy;
};

const MODELS = [
  "gpt-4o", "gpt-4o-mini", "claude-3.5-sonnet", "claude-3.5-haiku",
  "gemini-3.5-flash", "gemini-3.5-pro", "qwen-2.5-coder-32b",
  "deepseek-r1", "mistral-large", "llama-3.3-70b",
];

const CAPABILITIES = ["missions", "tools", "research", "code", "ha_control"];

const STRATEGIES: { key: Strategy; label: string; desc: string }[] = [
  { key: "react", label: "ReAct", desc: "Reason-Act-Observe loop. Best for complex reasoning." },
  { key: "plan_execute", label: "Plan & Execute", desc: "Plan first, then execute steps sequentially." },
  { key: "direct", label: "Direct", desc: "Single-shot execution. Fast and simple." },
  { key: "delegate", label: "Delegate", desc: "Route to sub-agents. Best for orchestration." },
];

const ROLE_ICONS: Record<Role, string> = {
  queen: "\uD83D\uDC51", worker: "\uD83D\uDC1D", scout: "\uD83D\uDD0D", drone: "\uD83E\uDD16", guard: "\uD83D\uDEE1\uFE0F",
};

const STRATEGY_COLORS: Record<Strategy, string> = {
  react: "#5a9a4a", plan_execute: "#3a6a9a", direct: "#d4a017", delegate: "#8b5cf6",
};

const STATUS_MAP: Record<AgentStatus, "running" | "idle" | "error" | "busy"> = {
  idle: "idle", busy: "busy", offline: "idle", error: "error",
};

const DEFAULT_INTENTS: IntentRow[] = [
  { intent: "tool_dispatch", agent: "Conductor", model: "gpt-4o", strategy: "delegate" },
  { intent: "research", agent: "Researcher", model: "gemini-3.5-pro", strategy: "react" },
  { intent: "code", agent: "Coder", model: "claude-3.5-sonnet", strategy: "plan_execute" },
  { intent: "ha_control", agent: "Abra", model: "gpt-4o-mini", strategy: "direct" },
  { intent: "security", agent: "RedTeam", model: "deepseek-r1", strategy: "react" },
  { intent: "maintenance", agent: "Heartbeat", model: "gpt-4o-mini", strategy: "direct" },
  { intent: "memory", agent: "DreamLoop", model: "mistral-large", strategy: "plan_execute" },
  { intent: "exploration", agent: "Phantom", model: "gemini-3.5-flash", strategy: "react" },
];

const STEP_LABELS = ["Describe", "Strategy", "Model", "Generate", "Review", "Scan", "Save"];

const inp = {
  width: "100%", padding: "6px 10px", fontFamily: "var(--mono)", fontSize: 10,
  background: "var(--paper-2, #f5f5f0)", border: "1.3px solid var(--rule)",
  borderRadius: 4, color: "var(--ink)", boxSizing: "border-box" as const,
};

const lbl = {
  fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)",
  textTransform: "uppercase" as const, marginBottom: 3, display: "block" as const,
};

const btn = {
  padding: "5px 14px", borderRadius: 4, cursor: "pointer" as const,
  fontFamily: "var(--mono)", fontSize: 10, border: "1.3px solid",
};

function agentRole(a: Agent): Role {
  const n = a.name.toLowerCase();
  const caps = a.capabilities.map((c) => c.toLowerCase());
  if (n.includes("conductor") || n.includes("orchestrator") || n.includes("queen")) return "queen";
  if (caps.includes("security") || n.includes("guard") || n.includes("sentinel") || n.includes("redteam")) return "guard";
  if (caps.includes("research") || n.includes("research") || n.includes("phantom") || n.includes("scout")) return "scout";
  if (caps.includes("monitoring") || n.includes("monitor") || n.includes("watch") || n.includes("heartbeat")) return "drone";
  return "worker";
}

function inferStrategy(a: Agent): Strategy {
  const cfg = a.config as Record<string, unknown>;
  if (typeof cfg.strategy === "string" && ["react", "plan_execute", "direct", "delegate"].includes(cfg.strategy)) {
    return cfg.strategy as Strategy;
  }
  const caps = a.capabilities.map((c) => c.toLowerCase());
  if (caps.includes("planning") || caps.includes("orchestration")) return "plan_execute";
  if (caps.includes("delegation") || caps.includes("management")) return "delegate";
  if (caps.includes("direct_execution")) return "direct";
  return "react";
}

function soulExcerpt(a: Agent): string {
  const cfg = a.config as Record<string, unknown>;
  const soul = typeof cfg.soul === "string" ? cfg.soul : a.description || "";
  return soul.length > 80 ? soul.slice(0, 80) + "…" : soul;
}

function SBadge({ s }: { s: Strategy }) {
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 3, fontSize: 8,
      fontFamily: "var(--mono)", fontWeight: 600,
      background: `${STRATEGY_COLORS[s]}22`, color: STRATEGY_COLORS[s],
      border: `1px solid ${STRATEGY_COLORS[s]}44`,
    }}>
      {s}
    </span>
  );
}

export default function Agents() {
  const toast = useToast();
  const { activeWorkspaceId } = useWorkspaces();
  const [tab, setTab] = useState(0);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanFindings, setScanFindings] = useState<string[] | null>(null);
  const [editConfig, setEditConfig] = useState("");
  const [editSoul, setEditSoul] = useState("");
  const [editRules, setEditRules] = useState("");
  const [saving, setSaving] = useState(false);

  const [bStep, setBStep] = useState(0);
  const [bDesc, setBDesc] = useState("");
  const [bStrat, setBStrat] = useState<Strategy>("react");
  const [bModel, setBModel] = useState("gpt-4o");
  const [bConfig, setBConfig] = useState("");
  const [bBusy, setBBusy] = useState(false);
  const [bScan, setBScan] = useState<string[] | null>(null);

  const [intents, setIntents] = useState<IntentRow[]>(DEFAULT_INTENTS);
  const [editIntent, setEditIntent] = useState<string | null>(null);

  const [cName, setCName] = useState("");
  const [cDesc, setCDesc] = useState("");
  const [cModel, setCModel] = useState("gpt-4o");
  const [cCaps, setCCaps] = useState<string[]>([]);
  const [cStrat, setCStrat] = useState<Strategy>("react");
  const [cBusy, setCBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      // Persona/Workspace system: scope to the active workspace's own
      // materialized agent roster (services/agent_materialization.py)
      // instead of the flat global registry.
      const path = activeWorkspaceId
        ? `/v1/agents?workspace_id=${encodeURIComponent(activeWorkspaceId)}`
        : "/v1/agents";
      setAgents(await apiGet<Agent[]>(path));
    } catch {
      toast("Failed to load agents", "error");
    } finally {
      setLoading(false);
    }
  }, [toast, activeWorkspaceId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selected) return;
    setEditConfig(JSON.stringify(selected.config, null, 2));
    const cfg = selected.config as Record<string, unknown>;
    setEditSoul(typeof cfg.soul === "string" ? cfg.soul : "");
    setEditRules(typeof cfg.rules === "string" ? cfg.rules : "");
    setScanFindings(null);
  }, [selected]);

  const handleSave = useCallback(async () => {
    if (!selected) return;
    setSaving(true);
    try {
      let config: Record<string, unknown>;
      try {
        const parsed = JSON.parse(editConfig);
        config = typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
          ? { ...parsed, soul: editSoul, rules: editRules }
          : { raw: editConfig, soul: editSoul, rules: editRules };
      } catch {
        config = { raw: editConfig, soul: editSoul, rules: editRules };
      }
      await apiPut(`/v1/agents/${selected.id}`, {
        ...selected, config, description: editSoul || selected.description,
      });
      toast("Agent saved");
      setSelected(null);
      await load();
    } catch {
      toast("Save failed", "error");
    } finally {
      setSaving(false);
    }
  }, [selected, editConfig, editSoul, editRules, load, toast]);

  const handleDelete = useCallback(async () => {
    if (!deleteId) return;
    try {
      await apiDelete(`/v1/agents/${deleteId}`);
      toast("Agent deleted");
      setSelected(null);
      await load();
    } catch {
      toast("Delete failed", "error");
    }
    setDeleteId(null);
  }, [deleteId, load, toast]);

  const handleScan = useCallback(async () => {
    if (!selected) return;
    setScanning(true);
    setScanFindings(null);
    try {
      const res = await apiPost<{ findings: string[] }>(`/v1/agents/${selected.id}/scan`);
      setScanFindings(res.findings);
      if (res.findings.length === 0) toast("No issues found", "ok");
    } catch {
      toast("Scan failed", "error");
    } finally {
      setScanning(false);
    }
  }, [selected, toast]);

  const handleCreate = useCallback(async () => {
    setCBusy(true);
    try {
      // `workspace_id` is what makes this work at all in a deployment that
      // still has HIVE_POC_MODE set: routes/agents.py 403s a create with no
      // workspace ("PM fleet is read-only in POC mode") and honours one with
      // it, subject to a workspace-owner check. The list call above has always
      // been workspace-scoped; the mutations were not (#129).
      await apiPost("/v1/agents", {
        name: cName, description: cDesc, model: cModel,
        capabilities: cCaps, strategy: cStrat,
        ...(activeWorkspaceId ? { workspace_id: activeWorkspaceId } : {}),
      });
      toast("Agent created");
      setShowCreate(false);
      setCName(""); setCDesc(""); setCModel("gpt-4o"); setCCaps([]); setCStrat("react");
      await load();
    } catch {
      toast("Create failed", "error");
    } finally {
      setCBusy(false);
    }
  }, [cName, cDesc, cModel, cCaps, cStrat, load, toast, activeWorkspaceId]);

  const handleForge = useCallback(async () => {
    setBBusy(true);
    try {
      const res = await apiPost<Record<string, unknown>>("/v1/agents/forge", {
        description: bDesc, strategy: bStrat, model: bModel,
        ...(activeWorkspaceId ? { workspace_id: activeWorkspaceId } : {}),
      });
      setBConfig(JSON.stringify(res, null, 2));
      setBStep(4);
    } catch {
      toast("Forge failed", "error");
    } finally {
      setBBusy(false);
    }
  }, [bDesc, bStrat, bModel, toast, activeWorkspaceId]);

  const handleBuilderScan = useCallback(async () => {
    setBBusy(true);
    try {
      const config = JSON.parse(bConfig);
      const res = await apiPost<{ findings: string[] }>("/v1/agents/scan", config);
      setBScan(res.findings);
    } catch {
      toast("Scan failed", "error");
    } finally {
      setBBusy(false);
    }
  }, [bConfig, toast]);

  const handleBuilderSave = useCallback(async () => {
    setBBusy(true);
    try {
      const config = JSON.parse(bConfig);
      await apiPost("/v1/agents", {
        ...config,
        ...(activeWorkspaceId ? { workspace_id: activeWorkspaceId } : {}),
      });
      toast("Agent created from forge");
      setBStep(0); setBDesc(""); setBConfig(""); setBScan(null);
      await load();
    } catch {
      toast("Forge save failed", "error");
    } finally {
      setBBusy(false);
    }
  }, [bConfig, load, toast, activeWorkspaceId]);

  const toggleCap = (cap: string) => {
    setCCaps((prev) => prev.includes(cap) ? prev.filter((c) => c !== cap) : [...prev, cap]);
  };

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader
        title="The Hive"
        subtitle={`${agents.length} agents — AI workers that handle your tasks`}
        helpHref="/docs#agents"
        actions={tab === 0 ? [
          <button key="c" onClick={() => setShowCreate(true)} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>+ Create</button>,
        ] : undefined}
      />
      <Tabs tabs={["Active", "Builder", "Intent Map"]} active={tab} onChange={setTab} />

      {tab === 0 && (
        loading ? <LoadingSpinner /> : agents.length === 0 ? (
          <EmptyState icon="🐝" title="No agents yet" action="Create Agent" onAction={() => setShowCreate(true)} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 10, padding: "0 0 80px" }}>
            {agents.map((a) => {
              const role = agentRole(a);
              const strategy = inferStrategy(a);
              return (
                <div
                  key={a.id}
                  className="card"
                  onClick={() => setSelected(a)}
                  style={{ cursor: "pointer", border: selected?.id === a.id ? "1.5px solid var(--accent)" : undefined }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 22 }}>{ROLE_ICONS[role]}</span>
                      <div>
                        <div style={{ fontFamily: "var(--hand)", fontSize: 16, fontWeight: 700 }}>{a.name}</div>
                        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 2 }}>{a.model}</div>
                      </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <StatusDot status={STATUS_MAP[a.status]} pulse={a.status === "busy"} />
                        <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>{a.status}</span>
                      </div>
                      <SBadge s={strategy} />
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 12, marginTop: 8, fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>
                    <span>{a.tasks_completed} tasks</span>
                    <span>{Math.round(a.avg_response_time_ms)}ms avg</span>
                  </div>
                  {a.current_mission && (
                    <div style={{ marginTop: 6, padding: "4px 8px", background: "rgba(212,160,23,0.1)", borderRadius: 3, fontFamily: "var(--mono)", fontSize: 9 }}>
                      mission: {a.current_mission}
                    </div>
                  )}
                  <div style={{ marginTop: 6, fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", fontStyle: "italic" }}>
                    {soulExcerpt(a)}
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}

      {tab === 1 && (
        <div>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginBottom: 20 }}>
            {STEP_LABELS.map((label, i) => (
              <div key={label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                <div style={{ width: 10, height: 10, borderRadius: "50%", background: i <= bStep ? "var(--accent)" : "var(--rule)" }} />
                <span style={{ fontFamily: "var(--mono)", fontSize: 7, color: i <= bStep ? "var(--ink)" : "var(--pencil)" }}>{label}</span>
              </div>
            ))}
          </div>

          {bStep === 0 && (
            <div style={{ maxWidth: 500, margin: "0 auto" }}>
              <label style={lbl}>What should this agent do?</label>
              <textarea value={bDesc} onChange={(e) => setBDesc(e.target.value)} rows={5} style={{ ...inp, resize: "vertical" as const }} placeholder="Describe the agent's purpose, skills, and behavior..." />
              <div style={{ marginTop: 12, textAlign: "right" }}>
                <button disabled={!bDesc.trim()} onClick={() => setBStep(1)} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)", opacity: bDesc.trim() ? 1 : 0.5 }}>Next \u2192</button>
              </div>
            </div>
          )}

          {bStep === 1 && (
            <div style={{ maxWidth: 600, margin: "0 auto" }}>
              <label style={lbl}>Choose a strategy</label>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 10 }}>
                {STRATEGIES.map((s) => (
                  <div key={s.key} onClick={() => setBStrat(s.key)} style={{
                    padding: 14, borderRadius: 6, cursor: "pointer",
                    border: bStrat === s.key ? `2px solid ${STRATEGY_COLORS[s.key]}` : "1.3px solid var(--rule)",
                    background: bStrat === s.key ? `${STRATEGY_COLORS[s.key]}11` : "var(--paper)",
                  }}>
                    <div style={{ fontFamily: "var(--hand)", fontSize: 15, fontWeight: 700, color: STRATEGY_COLORS[s.key] }}>{s.label}</div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", marginTop: 4 }}>{s.desc}</div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
                <button onClick={() => setBStep(0)} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>\u2190 Back</button>
                <button onClick={() => setBStep(2)} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>Next \u2192</button>
              </div>
            </div>
          )}

          {bStep === 2 && (
            <div style={{ maxWidth: 400, margin: "0 auto" }}>
              <label style={lbl}>Select model</label>
              <select value={bModel} onChange={(e) => setBModel(e.target.value)} style={{ ...inp, height: 32 }}>
                {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
                <button onClick={() => setBStep(1)} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>\u2190 Back</button>
                <button onClick={() => setBStep(3)} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>Next \u2192</button>
              </div>
            </div>
          )}

          {bStep === 3 && (
            <div style={{ maxWidth: 500, margin: "0 auto", textAlign: "center" }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, marginBottom: 16 }}>Ready to forge</div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)", marginBottom: 20 }}>
                Strategy: {bStrat} \u00B7 Model: {bModel}
              </div>
              <button disabled={bBusy} onClick={handleForge} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)", padding: "8px 24px", fontSize: 11 }}>
                {bBusy ? "Forging..." : "\u2692\uFE0F Forge Agent"}
              </button>
              <div style={{ marginTop: 12 }}>
                <button onClick={() => setBStep(2)} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>\u2190 Back</button>
              </div>
            </div>
          )}

          {bStep === 4 && (
            <div style={{ maxWidth: 600, margin: "0 auto" }}>
              <label style={lbl}>Generated config</label>
              <textarea value={bConfig} onChange={(e) => setBConfig(e.target.value)} rows={16} style={{ ...inp, resize: "vertical" as const, fontFamily: "var(--mono)", fontSize: 9 }} />
              <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
                <button onClick={() => setBStep(3)} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>\u2190 Back</button>
                <button onClick={() => { setBScan(null); setBStep(5); }} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>Scan \u2192</button>
              </div>
            </div>
          )}

          {bStep === 5 && (
            <div style={{ maxWidth: 500, margin: "0 auto" }}>
              <button disabled={bBusy} onClick={handleBuilderScan} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)", padding: "8px 24px", fontSize: 11 }}>
                {bBusy ? "Scanning..." : "\uD83D\uDEE1\uFE0F Run Security Scan"}
              </button>
              {bScan !== null && (
                <div style={{
                  marginTop: 12, borderRadius: 4, padding: 10,
                  background: bScan.length > 0 ? "rgba(196,69,42,0.08)" : "rgba(90,154,74,0.08)",
                  border: `1px solid ${bScan.length > 0 ? "rgba(196,69,42,0.3)" : "rgba(90,154,74,0.3)"}`,
                }}>
                  {bScan.length === 0
                    ? <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "#5a9a4a" }}>\u2713 No issues found</div>
                    : bScan.map((f, i) => <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 9, color: "#c4452a" }}>\u26A0 {f}</div>)
                  }
                </div>
              )}
              <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
                <button onClick={() => setBStep(4)} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>\u2190 Back</button>
                <button onClick={() => setBStep(6)} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>Next \u2192 Save</button>
              </div>
            </div>
          )}

          {bStep === 6 && (
            <div style={{ maxWidth: 500, margin: "0 auto", textAlign: "center" }}>
              <div style={{ fontFamily: "var(--hand)", fontSize: 18, marginBottom: 16 }}>Save forged agent</div>
              {bScan && bScan.length > 0 && (
                <div style={{ background: "rgba(196,69,42,0.08)", border: "1px solid rgba(196,69,42,0.3)", borderRadius: 4, padding: 10, marginBottom: 12, textAlign: "left" }}>
                  {bScan.map((f, i) => <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 9, color: "#c4452a" }}>\u26A0 {f}</div>)}
                </div>
              )}
              <button disabled={bBusy} onClick={handleBuilderSave} style={{ ...btn, background: "#5a9a4a", color: "var(--paper)", borderColor: "#5a9a4a", padding: "8px 24px", fontSize: 11 }}>
                {bBusy ? "Saving..." : "\uD83D\uDCBE Save Agent"}
              </button>
              <div style={{ marginTop: 12 }}>
                <button onClick={() => setBStep(5)} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>\u2190 Back</button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 2 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: 10 }}>
          <thead>
            <tr style={{ borderBottom: "1.3px solid var(--rule)" }}>
              <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase" }}>Intent</th>
              <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase" }}>Agent</th>
              <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase" }}>Model</th>
              <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--pencil)", fontWeight: 600, fontSize: 9, textTransform: "uppercase" }}>Strategy</th>
            </tr>
          </thead>
          <tbody>
            {intents.map((row) => (
              <tr key={row.intent} style={{ borderBottom: "1px solid var(--rule)" }}>
                <td style={{ padding: "8px 12px", fontFamily: "var(--hand)", fontSize: 13, fontWeight: 600 }}>{row.intent}</td>
                <td style={{ padding: "8px 12px", cursor: "pointer" }} onClick={() => setEditIntent(editIntent === row.intent ? null : row.intent)}>
                  {editIntent === row.intent ? (
                    <select
                      value={row.agent}
                      onChange={(e) => {
                        const ag = agents.find((a) => a.name === e.target.value);
                        setIntents((prev) => prev.map((r) => r.intent === row.intent
                          ? { ...r, agent: e.target.value, model: ag?.model ?? r.model, strategy: ag ? inferStrategy(ag) : r.strategy } : r));
                        setEditIntent(null);
                      }}
                      onBlur={() => setEditIntent(null)}
                      autoFocus
                      style={{ ...inp, height: 24, padding: "2px 6px" }}
                    >
                      {agents.length > 0
                        ? agents.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)
                        : <option value={row.agent}>{row.agent}</option>
                      }
                    </select>
                  ) : (
                    <span style={{ color: "var(--accent)" }}>{row.agent}</span>
                  )}
                </td>
                <td style={{ padding: "8px 12px", color: "var(--pencil)" }}>{row.model}</td>
                <td style={{ padding: "8px 12px" }}><SBadge s={row.strategy} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <div style={{
          position: "fixed", top: 0, right: 0, bottom: 0, width: 380,
          background: "var(--paper)", borderLeft: "1.5px solid var(--rule)",
          zIndex: 100, overflow: "auto", padding: 16,
          boxShadow: "-4px 0 16px rgba(0,0,0,0.1)",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 22 }}>{ROLE_ICONS[agentRole(selected)]}</span>
              <h2 style={{ fontFamily: "var(--hand)", fontSize: 20, fontWeight: 700, margin: 0 }}>{selected.name}</h2>
            </div>
            <button onClick={() => setSelected(null)} style={{ background: "none", border: "none", fontSize: 16, cursor: "pointer", color: "var(--pencil)" }}>\u2715</button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 12 }}>
            <StatCard label="Model" value={selected.model} />
            <StatCard label="Status" value={selected.status} />
            <StatCard label="Tasks" value={selected.tasks_completed} />
            <StatCard label="Avg Latency" value={`${Math.round(selected.avg_response_time_ms)}ms`} />
          </div>
          <label style={lbl}>Config (JSON)</label>
          <textarea value={editConfig} onChange={(e) => setEditConfig(e.target.value)} rows={8} style={{ ...inp, resize: "vertical" as const, fontFamily: "var(--mono)", fontSize: 9 }} />
          <label style={{ ...lbl, marginTop: 10 }}>SOUL.md</label>
          <textarea value={editSoul} onChange={(e) => setEditSoul(e.target.value)} rows={5} style={{ ...inp, resize: "vertical" as const, fontFamily: "var(--mono)", fontSize: 9 }} />
          <label style={{ ...lbl, marginTop: 10 }}>RULES.md</label>
          <textarea value={editRules} onChange={(e) => setEditRules(e.target.value)} rows={5} style={{ ...inp, resize: "vertical" as const, fontFamily: "var(--mono)", fontSize: 9 }} />
          {scanFindings !== null && (
            <div style={{
              marginTop: 10, borderRadius: 4, padding: 8,
              background: scanFindings.length > 0 ? "rgba(196,69,42,0.08)" : "rgba(90,154,74,0.08)",
              border: `1px solid ${scanFindings.length > 0 ? "rgba(196,69,42,0.3)" : "rgba(90,154,74,0.3)"}`,
            }}>
              {scanFindings.length === 0
                ? <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "#5a9a4a" }}>\u2713 No issues found</div>
                : scanFindings.map((f, i) => <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 9, color: "#c4452a" }}>\u26A0 {f}</div>)
              }
            </div>
          )}
          <div style={{ marginTop: 14, display: "flex", gap: 6, flexWrap: "wrap" }}>
            <button disabled={saving} onClick={handleSave} style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>
              {saving ? "Saving..." : "\uD83D\uDCBE Save"}
            </button>
            <button disabled={scanning} onClick={handleScan} style={{ ...btn, background: "var(--paper)", color: "var(--ink)", borderColor: "var(--rule)" }}>
              {scanning ? "Scanning..." : "\uD83D\uDEE1\uFE0F Scan"}
            </button>
            <button onClick={() => setDeleteId(selected.id)} style={{ ...btn, background: "var(--paper)", color: "#c4452a", borderColor: "#c4452a" }}>
              {"\uD83D\uDDD1\uFE0F Delete"}
            </button>
          </div>
        </div>
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Agent" wide>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div>
            <label style={lbl}>Name</label>
            <input value={cName} onChange={(e) => setCName(e.target.value)} style={inp} placeholder="Agent name" />
          </div>
          <div>
            <label style={lbl}>Description</label>
            <textarea value={cDesc} onChange={(e) => setCDesc(e.target.value)} rows={3} style={{ ...inp, resize: "vertical" as const }} placeholder="What does this agent do?" />
          </div>
          <div>
            <label style={lbl}>Model</label>
            <select value={cModel} onChange={(e) => setCModel(e.target.value)} style={{ ...inp, height: 32 }}>
              {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label style={lbl}>Capabilities</label>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {CAPABILITIES.map((cap) => (
                <label key={cap} style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 10 }}>
                  <input type="checkbox" checked={cCaps.includes(cap)} onChange={() => toggleCap(cap)} />
                  {cap}
                </label>
              ))}
            </div>
          </div>
          <div>
            <label style={lbl}>Strategy</label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {STRATEGIES.map((s) => (
                <label key={s.key} style={{
                  display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer",
                  fontFamily: "var(--mono)", fontSize: 10,
                  color: cStrat === s.key ? STRATEGY_COLORS[s.key] : "var(--pencil)",
                  fontWeight: cStrat === s.key ? 600 : 400,
                }}>
                  <input type="radio" name="strategy" checked={cStrat === s.key} onChange={() => setCStrat(s.key)} />
                  {s.label}
                </label>
              ))}
            </div>
          </div>
          <div style={{ textAlign: "right", marginTop: 8 }}>
            <button
              disabled={!cName.trim() || cBusy}
              onClick={handleCreate}
              style={{ ...btn, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)", opacity: cName.trim() ? 1 : 0.5 }}
            >
              {cBusy ? "Creating..." : "Create Agent"}
            </button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={deleteId !== null}
        onClose={() => setDeleteId(null)}
        onConfirm={handleDelete}
        title="Delete Agent"
        message="This will permanently delete this agent. This cannot be undone."
      />
    </div>
  );
}
