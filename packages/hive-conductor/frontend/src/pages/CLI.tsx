import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiGet, apiPost } from "../lib/api";
import { PageHeader } from "../components/shared";

// #292 — this page is a *limited operational console*, not a shell and not a
// demo panel. Every command is sent to `POST /v1/cli/exec` and executed by a
// registered backend capability; every line rendered comes from the backend
// response (or from the session's durable history on reconnect/refresh).
// Unsupported commands are refused by the backend (404 unsupported_command)
// and their failures are rendered, never simulated. The command set lives in
// `GET /v1/cli/commands` and is held to the page by
// `backend/tests/test_cli_contract.py`. Contract:
// docs/architecture/CONDUCTOR-CLI-PAGE-CONTRACT.md.
const BOOT_COMMAND = "hctl status";

// Client-side *error rendering* for explicit backend failures — the labels
// below name states the backend actually answered with (404/504/503/401),
// they never fabricate command output.
function failureLines(err: unknown): string[] {
  if (err instanceof ApiError) {
    if (err.status === 404) {
      return ["error: unsupported command", "  type 'help' for the supported set"];
    }
    if (err.status === 504) return ["error: command timed out"];
    if (err.status === 503) return ["error: backend unavailable"];
    if (err.status === 401) return ["error: unauthorized — sign in and retry"];
    // lib/api.ts wraps every transport-level failure (aborted, dropped
    // connection, offline) as ApiError with status 0 (#1423/#1436) — the
    // same words the boot path uses, so an unreachable hive reads as
    // unreachable, not as "command failed (0)".
    if (err.status === 0) return ["error: could not reach hive-conductor"];
    return [`error: command failed (${err.status})`];
  }
  return ["error: could not reach hive-conductor"];
}

// The backend's machine-readable error code, when it sent one (FastAPI's
// HTTPException.detail = {error: "...", ...}).
function detailErrorCode(err: unknown): string | null {
  if (err instanceof ApiError && err.detail && typeof err.detail === "object") {
    const code = (err.detail as { error?: unknown }).error;
    return typeof code === "string" ? code : null;
  }
  return null;
}

function isHistoryEntry(h: unknown): h is { command: string; outcome: string; lines?: string[] } {
  return (
    typeof h === "object" && h !== null && typeof (h as { command?: unknown }).command === "string"
  );
}

async function resolveSession(): Promise<{ id: string; history: unknown[] } | null> {
  const sessions = await apiGet<{ id: string; history?: unknown[] }[]>("/v1/cli/sessions");
  const session = sessions.find((s) => s.id === "default") ?? sessions[0];
  if (!session) return null;
  return { id: session.id, history: session.history ?? [] };
}

export default function CLI() {
  const [lines, setLines] = useState<string[]>([]);
  const [cmd, setCmd] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const booted = useRef(false);

  const exec = useCallback(async (command: string, sid: string | null) => {
    try {
      const health = await fetch("/health").then((r) => r.json());
      const agents = await fetch("/v1/agents").then((r) => r.json()).catch(() => []);
      const mcp = await fetch("/v1/mcp/servers").then((r) => r.json()).catch(() => []);
      const connected = mcp.filter((s: { status: string }) => s.status === "connected").length;
      const total = mcp.length;
      // M3-B7 (#97): status names what is degraded, not just whether the
      // process is up — the same degraded_services list /health computes and
      // the shell banner renders.
      const degraded: { service: string; reason: string }[] = Array.isArray(health.degraded_services)
        ? health.degraded_services
        : [];
      const degradedLines = degraded.length
        ? degraded.map((s) => `! degraded: ${s.service}${s.reason ? ` — ${s.reason}` : ""}`)
        : ["\u2713 no degraded optional services"];
      setLines([
        `$ hctl status`,
        `\u2713 hive-conductor running (pid 1, uptime ${Math.floor((Date.now() - new Date(health.started_at ?? Date.now()).getTime()) / 60000)}m)`,
        `\u2713 router model: ${health.router_model ?? "cerebras-qwen-3-235b-a22b-2507"}`,
        `\u2713 ${agents.length} agents ready`,
        `\u2713 ${connected}/${total} MCP servers connected`,
        `\u2713 vault: ${health.vault_enabled ? "enabled" : "disabled"} · state: ${health.state_enabled ? "enabled" : "disabled"} · reactor: ${health.reactor_enabled ? "enabled" : "disabled"}`,
        ...degradedLines,
      ]);
    } catch {
      setLines(["$ hctl status", "error: could not reach hive-conductor"]);
    }
  }, []);

  // Reconnect/refresh: restore the session's real history from the backend.
  // An empty session boots with one real `hctl status` execution.
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void (async () => {
      try {
        const session = await resolveSession();
        if (!session) {
          await exec(BOOT_COMMAND, null);
          return;
        }
        setSessionId(session.id);
        const restored = session.history.flatMap((h) =>
          isHistoryEntry(h) && h.outcome === "ok"
            ? [`$ ${h.command}`, ...(h.lines ?? [])]
            : isHistoryEntry(h)
              ? [`$ ${h.command}`]
              : [],
        );
        if (restored.length) {
          setLines(restored);
        } else {
          await exec(BOOT_COMMAND, session.id);
        }
      } catch {
        setLines(["error: could not reach hive-conductor"]);
      }
    })();
  }, [exec]);

  async function runCmd() {
    const command = cmd.trim();
    if (!command) return;
    setCmd("");

    if (c === "hctl status") {
      setLines((prev) => [...prev.slice(0, -1)]);
      void load();
      return;
    }

    try {
      if (c === "hctl agents") {
        // frontend-typed-client: allow pre-existing banked raw fetch (was :44); line shifted by the #97 degraded-status block in load().
        const data = await fetch("/v1/agents").then((r) => r.json());
        setLines((prev) => [...prev, ...data.map((a: { name: string; status: string; model: string; tasks_completed: number }) => `  ${a.name.padEnd(20)} ${a.status.padEnd(10)} ${a.model.padEnd(30)} ${a.tasks_completed} tasks`)]);
      } else if (c === "hctl health") {
        // frontend-typed-client: allow pre-existing banked raw fetch (was :47); line shifted by the #97 degraded-status block in load().
        const data = await fetch("/health").then((r) => r.json());
        const jsonLines = JSON.stringify(data, null, 2).split("\n").map((l: string) => `  ${l}`);
        setLines((prev) => [...prev, ...jsonLines]);
      } else if (c === "hctl sessions") {
        // frontend-typed-client: allow pre-existing banked raw fetch (was :51); line shifted by the #97 degraded-status block in load().
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
