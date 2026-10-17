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
      const data = await apiPost<{ session: { id: string }; lines: string[] }>("/v1/cli/exec", {
        command,
        session_id: sid,
      });
      setSessionId(data.session.id);
      setLines((prev) => [...prev, `$ ${command}`, ...data.lines]);
    } catch (err) {
      // A session record that vanished server-side (store reset) is recovered,
      // not echoed as a fake success: create a fresh session and run for real.
      if (detailErrorCode(err) === "unknown_session") {
        try {
          const fresh = await apiPost<{ id: string }>("/v1/cli/sessions");
          setSessionId(fresh.id);
          const retried = await apiPost<{ lines: string[] }>("/v1/cli/exec", {
            command,
            session_id: fresh.id,
          });
          setLines((prev) => [...prev, `$ ${command}`, ...retried.lines]);
          return;
        } catch {
          /* fall through to the plain failure rendering */
        }
      }
      setLines((prev) => [...prev, `$ ${command}`, ...failureLines(err)]);
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
    await exec(command, sessionId);
  }

  return (
    <div>
      <PageHeader title="CLI" subtitle="Operational console — status and inspection commands" helpHref="/docs#cli" />
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
