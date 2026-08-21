import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "../components/shared";

export default function CLI() {
  const [lines, setLines] = useState<string[]>([]);
  const [cmd, setCmd] = useState("");

  const load = useCallback(async () => {
    try {
      const health = await fetch("/health").then((r) => r.json());
      const agents = await fetch("/v1/agents").then((r) => r.json()).catch(() => []);
      const mcp = await fetch("/v1/mcp/servers").then((r) => r.json()).catch(() => []);
      const connected = mcp.filter((s: { status: string }) => s.status === "connected").length;
      const total = mcp.length;
      setLines([
        `$ hctl status`,
        `\u2713 hive-conductor running (pid 1, uptime ${Math.floor((Date.now() - new Date(health.started_at ?? Date.now()).getTime()) / 60000)}m)`,
        `\u2713 router model: ${health.router_model ?? "cerebras-qwen-3-235b-a22b-2507"}`,
        `\u2713 ${agents.length} agents ready`,
        `\u2713 ${connected}/${total} MCP servers connected`,
        `\u2713 vault: ${health.vault_enabled ? "enabled" : "disabled"} · state: ${health.state_enabled ? "enabled" : "disabled"} · reactor: ${health.reactor_enabled ? "enabled" : "disabled"}`,
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
        const data = await fetch("/v1/agents").then((r) => r.json());
        setLines((prev) => [...prev, ...data.map((a: { name: string; status: string; model: string; tasks_completed: number }) => `  ${a.name.padEnd(20)} ${a.status.padEnd(10)} ${a.model.padEnd(30)} ${a.tasks_completed} tasks`)]);
      } else if (c === "hctl health") {
        const data = await fetch("/health").then((r) => r.json());
        const jsonLines = JSON.stringify(data, null, 2).split("\n").map((l: string) => `  ${l}`);
        setLines((prev) => [...prev, ...jsonLines]);
      } else if (c === "hctl sessions") {
        const data = await fetch("/v1/chat/sessions").then((r) => r.json());
        setLines((prev) => [...prev, ...data.map((s: { id: string; title: string; message_count: number }) => `  ${s.id.slice(0, 8)}  ${s.title.padEnd(30)} ${s.message_count} msgs`)]);
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
      <div className="card" style={{ fontFamily: "var(--mono)", fontSize: 11, minHeight: 320, background: "var(--ink)", color: "var(--paper)", padding: "12px 14px", borderRadius: 6, lineHeight: 1.7 }}>
        {lines.map((line, i) => (
          <div key={i} style={{ color: line.startsWith("$") ? "var(--pencil)" : line.includes("\u2713") ? "var(--ok)" : line.includes("error") ? "var(--danger)" : "var(--paper)", whiteSpace: "pre" }}>{line}</div>
        ))}
        <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
          <span style={{ color: "var(--pencil)" }}>$</span>
          <input style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "var(--paper)", fontFamily: "var(--mono)", fontSize: 11, padding: 0 }} value={cmd} onChange={(e) => setCmd(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void runCmd(); }} autoFocus />
        </div>
      </div>
    </div>
  );
}
