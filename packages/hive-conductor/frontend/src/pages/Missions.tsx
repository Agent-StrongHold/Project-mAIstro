import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost, apiPatch, apiDelete } from "../lib/api";
import { usePmPoc } from "../context/PocMode";
import { PM_NAV_MISSIONS, PM_NAV_PROGRAM } from "../lib/pmBranding";
import {
  Card, Hex, Modal, SearchInput, StatCard, LoadingSpinner, PageHeader, useToast,
  ConfirmDialog, EmptyState,
} from "../components/shared";

type MissionStatus = "pending" | "running" | "completed" | "failed" | "paused";
type MissionPriority = "low" | "medium" | "high" | "critical";

type Mission = {
  id: string;
  name: string;
  description: string;
  status: MissionStatus;
  priority: MissionPriority;
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  progress: number;
  steps_total: number;
  steps_completed: number;
  assigned_agents: string[];
  tags: string[];
  metadata: Record<string, unknown>;
};

type AgentOption = { id: string; name: string };

type ThreadMsg = { id: number; role: "user" | "agent"; text: string; ts: number };

const STATUS_COLORS: Record<MissionStatus, string> = {
  pending: "var(--pencil)",
  running: "var(--accent)",
  completed: "#5a9a4a",
  failed: "#c4452a",
  paused: "#e8a03a",
};

const PULSE_STATUSES: Set<MissionStatus> = new Set(["pending", "running", "paused"]);

const PRIORITY_PILLS: { label: string; value: MissionPriority; color: string }[] = [
  { label: "P0", value: "critical", color: "#c4452a" },
  { label: "P1", value: "high", color: "#d45a3a" },
  { label: "P2", value: "high", color: "#e8a03a" },
  { label: "P3", value: "medium", color: "#5b8fb3" },
  { label: "P4", value: "low", color: "var(--pencil)" },
  { label: "P5", value: "low", color: "#999" },
];

const TIMELINE_STEPS = ["classified", "dispatched", "running", "complete"];

const FILTER_TABS = ["All", "Running", "Completed", "Failed", "Pending"] as const;
type FilterTab = (typeof FILTER_TABS)[number];

const FILTER_MAP: Record<string, MissionStatus | null> = {
  All: null,
  Running: "running",
  Completed: "completed",
  Failed: "failed",
  Pending: "pending",
};

const PULSE_CSS_ID = "hc-mission-pulse";
function ensurePulseCss() {
  if (document.getElementById(PULSE_CSS_ID)) return;
  const s = document.createElement("style");
  s.id = PULSE_CSS_ID;
  s.textContent = "@keyframes hc-mpulse{0%,100%{opacity:1}50%{opacity:.35}}";
  document.head.appendChild(s);
}

function statusHexVariant(s: MissionStatus): "ok" | "danger" | "warn" | "accent" | "muted" {
  if (s === "completed") return "ok";
  if (s === "failed") return "danger";
  if (s === "running") return "accent";
  if (s === "paused") return "warn";
  return "muted";
}

function priorityHexVariant(p: MissionPriority): "danger" | "warn" | "accent" | "muted" {
  if (p === "critical") return "danger";
  if (p === "high") return "warn";
  if (p === "medium") return "accent";
  return "muted";
}

function timelineIndex(m: Mission): number {
  if (m.status === "completed") return 3;
  if (m.status === "running") return 2;
  if (m.status === "paused") return 2;
  if (m.status === "pending") return 1;
  return 0;
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function fmtTime(v?: string | null): string {
  return v ? new Date(v).toLocaleString() : "\u2014";
}

const btnBase: React.CSSProperties = {
  border: "1.3px solid var(--rule)",
  borderRadius: 4,
  padding: "4px 12px",
  fontFamily: "var(--mono)",
  fontSize: 10,
  cursor: "pointer",
};

const inputBase: React.CSSProperties = {
  width: "100%",
  fontFamily: "var(--mono)",
  fontSize: 11,
  padding: "6px 8px",
  border: "1.3px solid var(--rule)",
  borderRadius: 4,
  background: "var(--paper)",
  color: "var(--ink)",
};

export default function Missions() {
  const pmPoc = usePmPoc();
  const toast = useToast();
  const [rows, setRows] = useState<Mission[]>([]);
  const [sel, setSel] = useState<Mission | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterTab>("All");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newPriority, setNewPriority] = useState<MissionPriority>("medium");
  const [newAgent, setNewAgent] = useState("");
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [thread, setThread] = useState<ThreadMsg[]>([]);
  const [threadInput, setThreadInput] = useState("");
  const threadNextId = useRef(0);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [clarifyAnswer, setClarifyAnswer] = useState("");
  const threadEndRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const [taskData, agentData] = await Promise.all([
        apiGet<Mission[]>("/v1/tasks"),
        apiGet<AgentOption[]>("/v1/agents"),
      ]);
      setRows(taskData);
      setAgents(agentData);
    } catch {
      toast("Failed to load missions", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    ensurePulseCss();
    void load();
  }, [load]);

  useEffect(() => {
    const hasRunning = rows.some((m) => m.status === "running" || m.status === "pending");
    if (!hasRunning) return;
    const id = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(id);
  }, [rows, load]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread]);

  const filtered = useMemo(() => {
    let list = rows;
    const statusFilter = FILTER_MAP[filter];
    if (statusFilter) list = list.filter((m) => m.status === statusFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((m) => m.name.toLowerCase().includes(q));
    }
    return list;
  }, [rows, filter, search]);

  const active = useMemo(() => {
    if (sel) {
      const refreshed = rows.find((r) => r.id === sel.id);
      if (refreshed) return refreshed;
    }
    return filtered[0] ?? null;
  }, [sel, rows, filtered]);

  async function createMission() {
    if (!newTitle.trim() || !newDesc.trim()) return;
    try {
      const body: Record<string, unknown> = {
        name: newTitle.trim(),
        description: newDesc.trim(),
        priority: newPriority,
      };
      if (newAgent) body.assigned_agents = [newAgent];
      const created = await apiPost<Mission>("/v1/tasks", body);
      setShowCreate(false);
      setNewTitle("");
      setNewDesc("");
      setNewPriority("medium");
      setNewAgent("");
      await load();
      setSel(created);
      toast("Mission created", "ok");
    } catch {
      toast("Failed to create mission", "error");
    }
  }

  async function patchStatus(id: string, status: MissionStatus) {
    try {
      await apiPatch(`/v1/tasks/${id}/status`, { status });
      await load();
      toast(`Status \u2192 ${status}`, "ok");
    } catch {
      toast("Status update failed", "error");
    }
  }

  async function deleteMission(id: string) {
    try {
      await apiDelete(`/v1/tasks/${id}`);
      setSel(null);
      await load();
      toast("Mission deleted", "ok");
    } catch {
      toast("Delete failed", "error");
    }
  }

  async function clearFailedMissions() {
    try {
      const res = await apiPost<{ removed: number }>("/v1/tasks/clear", { status: "failed" });
      setSel(null);
      await load();
      toast(`Cleared ${res.removed} failed mission(s)`, "ok");
    } catch {
      toast("Clear failed", "error");
    }
  }

  async function clearCompletedMissions() {
    try {
      const res = await apiPost<{ removed: number }>("/v1/tasks/clear", { status: "completed" });
      setSel(null);
      await load();
      toast(`Cleared ${res.removed} completed mission(s)`, "ok");
    } catch {
      toast("Clear completed failed", "error");
    }
  }

  async function sendThreadMsg() {
    if (!threadInput.trim() || !active) return;
    const text = threadInput.trim();
    const userMsg: ThreadMsg = { id: threadNextId.current++, role: "user", text, ts: Date.now() };
    setThread((prev) => [...prev, userMsg]);
    setThreadInput("");
    try {
      const res = await apiPost<{
        message?: string;
        queued_tasks?: { task_id: string }[];
        interview?: { complete?: boolean };
      }>("/v1/program/guidance", { text, task_id: active.id });
      const n = res.queued_tasks?.length ?? 0;
      const agentText =
        res.message ??
        (n > 0
          ? `Recorded. Hyperagent queued ${n} follow-up task(s).`
          : res.interview?.complete
            ? "Recorded. The fleet updated your program context."
            : "Recorded. Finish the Program interview to enable autonomous follow-ups.");
      setThread((prev) => [
        ...prev,
        { id: threadNextId.current++, role: "agent", text: agentText, ts: Date.now() },
      ]);
      toast(n > 0 ? `Guidance queued ${n} task(s)` : "Guidance saved", "ok");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Guidance failed";
      setThread((prev) => [
        ...prev,
        {
          id: threadNextId.current++,
          role: "agent",
          text: detail.includes("PM POC")
            ? `${detail} Restart Hive with HIVE_POC_MODE=pm.`
            : detail,
          ts: Date.now(),
        },
      ]);
      toast(detail, "error");
    }
  }

  function selectMission(m: Mission) {
    setSel(m);
    setThread([]);
    setClarifyAnswer("");
  }

  if (loading) return <LoadingSpinner />;

  return (
    <div style={{ minHeight: "calc(100vh - 60px)" }}>
      <PageHeader
        title={pmPoc ? PM_NAV_MISSIONS : "Missions"}
        subtitle={
          pmPoc
            ? "Autonomous fleet tasks (poll Jira, scan risks, research). Jira writes use Jira drafts on Program."
            : "Multi-step tasks assigned to AI agents"
        }
        helpHref={pmPoc ? undefined : "/docs#missions"}
        actions={
          <div style={{ display: "flex", gap: 6 }}>
            {pmPoc && (
              <Link to="/agents" className="btn" style={{ fontSize: 9, padding: "2px 8px" }}>
                {PM_NAV_PROGRAM}
              </Link>
            )}
            {pmPoc && rows.some((m) => m.status === "completed") && (
              <button
                type="button"
                className="btn"
                style={{ fontSize: 9, padding: "2px 8px" }}
                onClick={() => void clearCompletedMissions()}
              >
                Clear completed
              </button>
            )}
            {pmPoc && rows.some((m) => m.status === "failed") && (
              <button
                type="button"
                className="btn"
                style={{ fontSize: 9, padding: "2px 8px", color: "var(--danger)", borderColor: "var(--danger)" }}
                onClick={() => void clearFailedMissions()}
              >
                Clear failed
              </button>
            )}
            {!pmPoc && (
              <button className="btn btn-accent" style={{ fontSize: 9, padding: "2px 8px" }} onClick={() => setShowCreate(true)}>
                + new
              </button>
            )}
          </div>
        }
      />
      <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 0, minHeight: "calc(100vh - 120px)" }}>
      <div style={{ borderRight: "1.5px dashed var(--rule)", padding: 10, display: "flex", flexDirection: "column", gap: 6, overflowY: "auto" }}>
        <div style={{ display: "flex", gap: 3, flexWrap: "wrap", marginBottom: 4 }}>
          {FILTER_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setFilter(tab)}
              style={{
                background: filter === tab ? "var(--accent)" : "transparent",
                color: filter === tab ? "var(--paper)" : "var(--ink)",
                border: `1.3px solid ${filter === tab ? "var(--accent)" : "var(--rule)"}`,
                borderRadius: 3,
                padding: "2px 8px",
                fontFamily: "var(--mono)",
                fontSize: 9,
                cursor: "pointer",
              }}
            >
              {tab}
            </button>
          ))}
        </div>

        <SearchInput value={search} onChange={setSearch} placeholder="Filter missions…" />

        {filtered.length === 0 && (
          <EmptyState icon="🎯" title="No missions" action="Create one" onAction={() => setShowCreate(true)} />
        )}

        {filtered.map((m) => {
          const sc = STATUS_COLORS[m.status];
          const pulse = PULSE_STATUSES.has(m.status);
          return (
            <div
              key={m.id}
              onClick={() => selectMission(m)}
              style={{
                padding: "6px 8px",
                borderRadius: 4,
                border: `1.3px solid ${active?.id === m.id ? "var(--accent)" : "var(--rule)"}`,
                background: active?.id === m.id ? "var(--accent-bg, rgba(212,160,23,0.08))" : "transparent",
                cursor: "pointer",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: sc,
                    animation: pulse ? "hc-mpulse 1.5s ease-in-out infinite" : "none",
                    flexShrink: 0,
                  }}
                />
                <Hex variant={statusHexVariant(m.status)}>{m.status}</Hex>
                <Hex variant="muted">{m.priority}</Hex>
              </div>
              <div style={{ fontFamily: "var(--hand)", fontSize: 13 }}>{truncate(m.name, 28)}</div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 8, color: "var(--pencil)", marginTop: 2 }}>
                {m.assigned_agents.length > 0 ? `${m.assigned_agents[0]} \u00B7 ` : ""}
                {m.created_at ? new Date(m.created_at).toLocaleDateString() : ""}
              </div>
            </div>
          );
        })}

        <div style={{ marginTop: "auto", paddingTop: 8 }}>
          <button
            onClick={() => setShowCreate(true)}
            style={{
              width: "100%",
              background: "var(--accent)",
              color: "var(--paper)",
              border: "1.3px solid var(--accent)",
              borderRadius: 4,
              padding: "6px 0",
              fontFamily: "var(--hand)",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            New Mission +
          </button>
        </div>
      </div>

      <div style={{ padding: "14px 18px", overflowY: "auto" }}>
        {active ? (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>{active.id}</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 24, fontWeight: 700, margin: "2px 0 4px" }}>{active.name}</div>
                <div style={{ fontFamily: "var(--hand)", fontSize: 13, color: "var(--pencil)" }}>{active.description}</div>
                {active.status === "failed" && typeof active.metadata?.error === "string" && (
                  <div
                    style={{
                      marginTop: 8,
                      padding: "8px 10px",
                      background: "rgba(196,69,42,0.1)",
                      border: "1px solid var(--danger)",
                      borderRadius: 4,
                      fontFamily: "var(--mono)",
                      fontSize: 9,
                      color: "var(--danger)",
                      lineHeight: 1.4,
                      wordBreak: "break-word",
                    }}
                  >
                    {active.metadata.error}
                  </div>
                )}
                {active.status === "failed" && pmPoc && !active.metadata?.error && (
                  <div style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)" }}>
                    Likely from before the PM stub fix (no LLM). Use <strong>Clear failed</strong>, then invoke an agent again from Agent Fleet.
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", justifyContent: "flex-end", marginLeft: 12 }}>
                {active.status === "pending" && (
                  <button onClick={() => void patchStatus(active.id, "running")} style={{ ...btnBase, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>Start</button>
                )}
                {active.status === "running" && (
                  <>
                    <button onClick={() => void patchStatus(active.id, "completed")} style={{ ...btnBase, background: "#5a9a4a", color: "#fff", borderColor: "#5a9a4a" }}>Complete</button>
                    <button onClick={() => void patchStatus(active.id, "failed")} style={{ ...btnBase, background: "#c4452a", color: "#fff", borderColor: "#c4452a" }}>Fail</button>
                    <button onClick={() => void patchStatus(active.id, "pending")} style={btnBase}>Cancel</button>
                  </>
                )}
                {(active.status === "completed" || active.status === "failed") && (
                  <>
                    {!pmPoc && (
                      <button onClick={() => void patchStatus(active.id, "pending")} style={{ ...btnBase, background: "var(--accent)", color: "var(--paper)", borderColor: "var(--accent)" }}>Restart</button>
                    )}
                    <button onClick={() => setConfirmDelete(true)} style={{ ...btnBase, color: "#c4452a", borderColor: "#c4452a" }}>Delete</button>
                  </>
                )}
              </div>
            </div>

            <div style={{ display: "flex", gap: 5, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span
                  style={{
                    display: "inline-block", width: 7, height: 7, borderRadius: "50%",
                    background: STATUS_COLORS[active.status],
                    animation: PULSE_STATUSES.has(active.status) ? "hc-mpulse 1.5s ease-in-out infinite" : "none",
                  }}
                />
                <Hex variant={statusHexVariant(active.status)}>{active.status}</Hex>
              </span>
              <Hex variant={priorityHexVariant(active.priority)}>{active.priority}</Hex>
              {active.assigned_agents.map((a) => <Hex key={a} variant="ok">{a}</Hex>)}
            </div>

            <div style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", textTransform: "uppercase" }}>Progress</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink)" }}>
                  {Math.round(active.progress * 100)}% &middot; {active.steps_completed}/{active.steps_total} steps
                </span>
              </div>
              <div style={{ height: 8, background: "var(--rule)", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${active.progress * 100}%`, background: STATUS_COLORS[active.status], borderRadius: 4, transition: "width 0.3s" }} />
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 14 }}>
              <StatCard label="Created" value={fmtTime(active.created_at)} />
              <StatCard label="Updated" value={fmtTime(active.updated_at)} />
              <StatCard label="Started" value={fmtTime(active.started_at)} />
              <StatCard label="Completed" value={fmtTime(active.completed_at)} />
            </div>

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", textTransform: "uppercase", marginBottom: 8 }}>Timeline</div>
              {TIMELINE_STEPS.map((step, i) => {
                const done = i <= timelineIndex(active);
                return (
                  <div key={step} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 16 }}>
                      <div
                        style={{
                          width: 10, height: 10, borderRadius: "50%",
                          border: done ? "none" : "1.3px solid var(--pencil)",
                          background: done ? "var(--accent)" : "transparent",
                          flexShrink: 0,
                        }}
                      />
                      {i < TIMELINE_STEPS.length - 1 && (
                        <div style={{ width: 1.5, height: 20, background: done ? "var(--accent)" : "var(--rule)" }} />
                      )}
                    </div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: done ? "var(--ink)" : "var(--pencil)", paddingBottom: 12 }}>{step}</div>
                  </div>
                );
              })}
            </div>

            <div style={{ display: "flex", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
              {active.assigned_agents.length > 0 && (
                <div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", textTransform: "uppercase", marginBottom: 4 }}>Agents</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {active.assigned_agents.map((a) => <Hex key={a} variant="ok">{a}</Hex>)}
                  </div>
                </div>
              )}
              {active.tags.length > 0 && (
                <div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", textTransform: "uppercase", marginBottom: 4 }}>Tags</div>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {active.tags.map((t) => <Hex key={t}>{t}</Hex>)}
                  </div>
                </div>
              )}
            </div>

            {active.status === "paused" && (
              <Card>
                <div style={{ padding: "10px 14px", background: "rgba(232,160,58,0.12)", border: "1.3px solid #e8a03a", borderRadius: 5, marginBottom: 12 }}>
                  <div style={{ fontFamily: "var(--hand)", fontSize: 15, color: "#e8a03a", marginBottom: 6, fontWeight: 600 }}>
                    Mission paused \u2014 agent needs your input
                  </div>
                  <textarea
                    value={clarifyAnswer}
                    onChange={(e) => setClarifyAnswer(e.target.value)}
                    placeholder="Enter your guidance…"
                    rows={3}
                    style={{ ...inputBase, resize: "vertical" }}
                  />
                  <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                    {["Proceed as planned", "Modify approach", "Abort mission"].map((opt) => (
                      <label key={opt} style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer", fontFamily: "var(--mono)", fontSize: 9, color: clarifyAnswer === opt ? "var(--accent)" : "var(--ink)" }}>
                        <input type="radio" name="clarify" checked={clarifyAnswer === opt} onChange={() => setClarifyAnswer(opt)} style={{ accentColor: "var(--accent)" }} />
                        {opt}
                      </label>
                    ))}
                  </div>
                  <button
                    onClick={() => { if (clarifyAnswer) void patchStatus(active.id, "running"); }}
                    disabled={!clarifyAnswer}
                    style={{
                      ...btnBase,
                      marginTop: 10,
                      background: clarifyAnswer ? "var(--accent)" : "var(--rule)",
                      color: clarifyAnswer ? "var(--paper)" : "var(--pencil)",
                      borderColor: "var(--accent)",
                      cursor: clarifyAnswer ? "pointer" : "not-allowed",
                    }}
                  >
                    Continue Mission
                  </button>
                </div>
              </Card>
            )}

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", textTransform: "uppercase", marginBottom: 8 }}>Guidance Thread</div>
              <div style={{ border: "1.3px solid var(--rule)", borderRadius: 5, padding: 8, maxHeight: 200, overflowY: "auto", marginBottom: 6 }}>
                {thread.length === 0 && (
                  <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", textAlign: "center", padding: 12 }}>
                    No messages yet. Send guidance to the agent.
                  </div>
                )}
                {thread.map((msg) => (
                  <div key={msg.id} style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start", marginBottom: 6 }}>
                    <div
                      style={{
                        maxWidth: "75%", padding: "5px 10px",
                        borderRadius: msg.role === "user" ? "10px 10px 2px 10px" : "10px 10px 10px 2px",
                        background: msg.role === "user" ? "var(--accent)" : "rgba(0,0,0,0.05)",
                        color: msg.role === "user" ? "var(--paper)" : "var(--ink)",
                        fontFamily: "var(--mono)", fontSize: 10,
                      }}
                    >
                      {msg.text}
                    </div>
                  </div>
                ))}
                <div ref={threadEndRef} />
              </div>
              <div style={{ display: "flex", gap: 4 }}>
                <input
                  value={threadInput}
                  onChange={(e) => setThreadInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") sendThreadMsg(); }}
                  placeholder="Send guidance…"
                  style={{ flex: 1, ...inputBase, fontSize: 10, padding: "5px 8px" }}
                />
                <button
                  onClick={sendThreadMsg}
                  disabled={!threadInput.trim()}
                  style={{
                    ...btnBase,
                    background: threadInput.trim() ? "var(--accent)" : "var(--rule)",
                    color: threadInput.trim() ? "var(--paper)" : "var(--pencil)",
                    borderColor: "var(--accent)",
                    cursor: threadInput.trim() ? "pointer" : "not-allowed",
                  }}
                >
                  Send
                </button>
              </div>
            </div>
          </>
        ) : (
          <EmptyState icon="🎯" title="Select a mission" action="Create one" onAction={() => setShowCreate(true)} />
        )}
      </div>

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="New Mission" wide>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", display: "block", marginBottom: 3 }}>Title *</label>
            <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="Mission title" style={inputBase} autoFocus />
          </div>
          <div>
            <label style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", display: "block", marginBottom: 3 }}>Description *</label>
            <textarea
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="What should the mission accomplish?"
              rows={4}
              style={{ ...inputBase, resize: "vertical" }}
            />
          </div>
          <div>
            <label style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", display: "block", marginBottom: 5 }}>Priority</label>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {PRIORITY_PILLS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => setNewPriority(p.value)}
                  style={{
                    padding: "4px 14px",
                    borderRadius: 12,
                    border: `1.3px solid ${newPriority === p.value ? p.color : "var(--rule)"}`,
                    background: newPriority === p.value ? p.color : "transparent",
                    color: newPriority === p.value ? "#fff" : "var(--ink)",
                    fontFamily: "var(--mono)",
                    fontSize: 9,
                    cursor: "pointer",
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--pencil)", display: "block", marginBottom: 3 }}>Assign Agent</label>
            <select value={newAgent} onChange={(e) => setNewAgent(e.target.value)} style={inputBase}>
              <option value="">\u2014 none \u2014</option>
              {agents.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}
            </select>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 6 }}>
            <button
              onClick={() => setShowCreate(false)}
              style={{ ...btnBase, background: "var(--paper)", color: "var(--ink)" }}
            >
              Cancel
            </button>
            <button
              onClick={() => void createMission()}
              disabled={!newTitle.trim() || !newDesc.trim()}
              style={{
                ...btnBase,
                background: newTitle.trim() && newDesc.trim() ? "var(--accent)" : "var(--rule)",
                color: newTitle.trim() && newDesc.trim() ? "var(--paper)" : "var(--pencil)",
                borderColor: "var(--accent)",
                cursor: newTitle.trim() && newDesc.trim() ? "pointer" : "not-allowed",
              }}
            >
              Create Mission
            </button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => { if (active) void deleteMission(active.id); }}
        title="Delete Mission"
        message={`Permanently delete "${active?.name ?? ""}"? This cannot be undone.`}
      />
      </div>
    </div>
  );
}
