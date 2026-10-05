import { useCallback, useEffect, useState } from "react";
import type { Agent, ChatSessionSummary, HealthResponse, MCPServer } from "../api/entities";
import { apiGet } from "../lib/api";
import { PageHeader } from "../components/shared";

export default function CLI() {
  const [lines, setLines] = useState<string[]>([]);
  const [cmd, setCmd] = useState("");

  const load = useCallback(async () => {
    try {
      const health = await apiGet<HealthResponse>("/health");
      const agents = await apiGet<Agent[]>("/v1/agents").catch(() => [] as Agent[]);
      const mcp = await apiGet<MCPServer[]>("/v1/mcp/servers").catch(() => [] as MCPServer[]);
      const connected = mcp.filter((s) => s.status === "connected").length;
      const total = mcp.length;
      const degraded: { service: string; reason: string }[] = Array.isArray(health.degraded_services)
        ? (health.degraded_services as { service: string; reason: string }[])
        : [];
      const degradedLines = degraded.length
        ? degraded.map((s) => `! degraded: ${s.service}${s.reason ? ` — ${s.reason}` : ""}`)
        : ["\u2713 no degraded optional services"];
      setLines([
        `$ hctl status`,
        `\u2713 hive-conductor running (pid 1, uptime ${Math.floor((Date.now() - new Date(String(health.started_at ?? Date.now())).getTime()) / 60000)}m)`,
        `\u2713 router model: ${String(health.router_model ?? "cerebras-qwen-3-235b-a22b-2507")}`,
        `\u2713 ${agents.length} agents ready`,
        `\u2713 ${connected}/${total} MCP servers connected`,
        `\u2713 vault: ${health.vault_enabled ? "enabled" : "disabled"} · state: ${health.state_enabled ? "enabled" : "disabled"} · reactor: ${health.reactor_enabled ? "enabled" : "disabled"}`,
        ...degradedLines,
      ]);
    } catch {
      setLines(["$ hctl status", "error: could not reach hive-conductor"]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function runCmd() {
    if (!cmd.trim()) return;
    const c = cmd.trim();
    setLines((prev) => [...prev, `$ ${c}`]);
    setCmd("");

    if (c === "hctl status") {
      setLines((prev) => [...prev.slice(0, -1)]);
      void load();
      return;
    }

    try {
      if (c === "hctl agents") {
        const data = await apiGet<Agent[]>("/v1/agents");
        setLines((prev) => [...prev, ...data.map((a) => `  ${a.name.padEnd(20)} ${a.status.padEnd(10)} ${a.model.padEnd(30)} ${a.tasks_completed} tasks`)]);
      } else if (c === "hctl health") {
        const data = await apiGet<HealthResponse>("/health");
        const jsonLines = JSON.stringify(data, null, 2).split("\n").map((l: string) => `  ${l}`);
        setLines((prev) => [...prev, ...jsonLines]);
      } else if (c === "hctl sessions") {
        const data = await apiGet<ChatSessionSummary[]>("/v1/chat/sessions");
        setLines((prev) => [...prev, ...data.map((s) => `  ${s.id.slice(0, 8)}  ${s.title.padEnd(30)} ${s.message_count} msgs`)]);
      } else if (c === "help" || c === "hctl") {
        setLines((prev) => [...prev, "  hctl status    — show system status", "  hctl agents    — list agents", "  hctl health    — health check JSON", "  hctl sessions  — list chat sessions", "  help           — this message"]);
      } else {
        setLines((prev) => [...prev, `  unknown command: ${c}`, "  type 'help' for available commands"]);
      }
    } catch {
      setLines((prev) => [...prev, `  error: command failed`]);
    }
  }

  return (
    <div>
      <PageHeader title="CLI" subtitle="Command-line interface for quick status checks" helpHref="/docs#dashboard" />
      <div className="card" style={{ fontFamily: "var(--mono)", fontSize: 12, minHeight: 320, background: "var(--ink)", color: "var(--paper)", padding: "12px 14px", borderRadius: 6, lineHeight: 1.7 }}>
        {lines.map((line, i) => (
          <div key={i} style={{ color: line.startsWith("$") ? "var(--pencil)" : line.startsWith("!") ? "var(--danger)" : line.includes("\u2713") ? "var(--ok)" : line.includes("error") ? "var(--danger)" : "var(--paper)", whiteSpace: "pre" }}>{line}</div>
        ))}
        <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
          <span style={{ color: "var(--pencil)" }}>$</span>
          <input style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "var(--paper)", fontFamily: "var(--mono)", fontSize: 12, padding: 0 }} value={cmd} onChange={(e) => setCmd(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void runCmd(); }} autoFocus />
        </div>
      </div>
    </div>
  );
}
