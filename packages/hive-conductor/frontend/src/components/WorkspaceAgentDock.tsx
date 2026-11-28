import { useCallback, useEffect, useRef, useState } from "react";
import { MessageCircle, X } from "lucide-react";
import { ApiError, apiGet, apiPost, fallbackMessage } from "../lib/api";
import { randomId } from "../lib/ids";
import type { Message } from "../lib/chatUi";
import type { ChatSessionDetail, ChatSessionSummary, ChatStreamFrame } from "../lib/chatSessions";
import {
  fetchModelsCatalog,
  openChatStream,
  sessionsListPath,
} from "../lib/chatSessions";
import { useWorkspaces } from "../context/WorkspaceContext";

/**
 * Persistent Workspace Agent shell surface (#2549, Slice B).
 *
 * One conversation-first agent dock mounted ONCE in AppShell, so it renders on
 * every page (Home, Chat, Goals, Attention, Approvals, Design Studio, DAG
 * Builder, DAG Runs, Missions, Backlog, Capabilities, Quotas, Inner Temple,
 * CLI, Credentials, Audit, Settings). It is the same durable chat seam as the
 * Chat page — `/v1/chat/sessions` rows plus the `/v1/chat/stream` SSE frames —
 * never a second store or a competing execution path. A turn executes on the
 * canonical Chat completion service for the active Workspace, so workspace
 * ops, workflows, runs, and approvals are accomplishable through this
 * conversation (AC-4), not only through dedicated page forms.
 *
 * With no active Workspace (a fresh daily-user account's first run — the
 * daily role holds no `workspaces.write`, so it cannot provision one), the
 * launcher still opens the panel and the panel says so honestly, exactly
 * like the Chat page's "No Workspace selected" refusal — never a silent
 * dead toggle whose `aria-expanded` claims a surface that never renders.
 */

// Dedicated durable session title so the dock's transcript is identifiable in
// the same session store the Chat page lists.
const DOCK_SESSION_TITLE = "Workspace Agent";

// Keep the request payload bounded — mirrors Chat.tsx's HISTORY_LIMIT.
const HISTORY_LIMIT = 20;

function generateId() {
  // Via `randomId` (CSPRNG, works over plain HTTP) — these ids name turns the
  // backend may key idempotence on (#1822 AC-4), same as Chat.tsx.
  return randomId();
}

/** The conversation half. Remounted per active Workspace (`key=` below), so a
 * Workspace switch is an unmount — no effect-body reset, and any in-flight
 * stream aborts in cleanup. */
function WorkspaceAgentConversation({ workspaceId }: { workspaceId: string }) {
  const [model, setModel] = useState("");
  const [session, setSession] = useState<ChatSessionSummary | null>(null);
  const [turns, setTurns] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const epochRef = useRef(0);
  const sendInFlightRef = useRef(false);

  // Model catalog: first entry, same resolution as the Chat page.
  useEffect(() => {
    fetchModelsCatalog()
      .then((res) => res.json())
      .then((data) => {
        const arr = Array.isArray(data) ? data : data.models || data.data || [];
        const list = arr
          .map((m: { id?: string; name?: string } | string) =>
            typeof m === "string" ? m : m.id || m.name || "",
          )
          .filter(Boolean);
        if (list.length > 0) setModel(list[0]);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    // Unmount (or Workspace switch via remount) kills any in-flight stream.
    return () => {
      abortRef.current?.abort();
      epochRef.current += 1;
    };
  }, []);

  // Hydrate the dock's dedicated session for THIS Workspace on mount.
  useEffect(() => {
    let cancelled = false;
    const generation = epochRef.current;
    void (async () => {
      try {
        const list = await apiGet<ChatSessionSummary[]>(
          sessionsListPath(workspaceId),
        );
        if (cancelled || epochRef.current !== generation) return;
        const existing = list.find((s) => s.title === DOCK_SESSION_TITLE);
        if (existing) {
          // Hydrate the transcript from durable truth.
          const detail = await apiGet<ChatSessionDetail>(
            `/v1/chat/sessions/${encodeURIComponent(existing.id)}`,
          );
          if (cancelled || epochRef.current !== generation) return;
          setTurns(
            detail.messages
              .filter((m) => m.role === "user" || m.role === "assistant")
              .map((m) => ({
                id: m.id,
                role: m.role as Message["role"],
                content: m.content,
                timestamp: m.timestamp ? new Date(m.timestamp) : new Date(),
              })),
          );
          // Publish session and hydrated turns together (#review: the composer
          // must not enable against the initial empty `turns` array — a send
          // here would omit all conversation history, and the later
          // `setTurns` would clobber its optimistic user/assistant bubbles).
          setSession(existing);
        } else {
          const created = await apiPost<ChatSessionDetail>("/v1/chat/sessions", {
            title: DOCK_SESSION_TITLE,
            workspace_id: workspaceId,
          });
          if (cancelled || epochRef.current !== generation) return;
          setSession({
            id: created.id,
            user_id: created.user_id,
            workspace_id: created.workspace_id,
            title: created.title,
            message_count: created.messages.length,
            updated_at: created.updated_at,
          });
        }
        setLoadError(null);
      } catch (e) {
        if (cancelled || epochRef.current !== generation) return;
        setSession(null);
        setTurns([]);
        setLoadError(e instanceof ApiError ? e.message : "Couldn't open the Workspace Agent.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (
        !trimmed ||
        busy ||
        sendInFlightRef.current ||
        !session ||
        !model
      ) {
        return;
      }
      sendInFlightRef.current = true;
      const sessionId = session.id;
      const epoch = epochRef.current;
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      const userTurn: Message = {
        id: generateId(),
        role: "user",
        content: trimmed,
        timestamp: new Date(),
      };
      const assistantId = generateId();
      const assistantTurn: Message = {
        id: assistantId,
        role: "assistant",
        content: "",
        status: "Thinking…",
        steps: [],
        timestamp: new Date(),
      };

      const prior = turns
        .filter((m) => m.content)
        .map((m) => ({ role: m.role, content: m.content }));
      const outbound = [...prior, { role: "user" as const, content: trimmed }].slice(
        -HISTORY_LIMIT,
      );

      setTurns((prev) => [...prev, userTurn, assistantTurn]);
      setInput("");
      setBusy(true);

      const patchAssistant = (fn: (m: Message) => Message) => {
        if (epochRef.current !== epoch) return;
        setTurns((prev) =>
          prev.map((m) => (m.id === assistantId ? fn(m) : m)),
        );
      };

      try {
        const res = await openChatStream(
          {
            model,
            messages: outbound,
            workspace_id: workspaceId,
            session_id: sessionId,
            turn_id: generateId(),
          },
          abort.signal,
        );
        if (!res.ok || !res.body) throw new Error(fallbackMessage(res.status));

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let gotContent = false;
        let streamed = false;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const trimmedFrame = frame.trim();
            if (!trimmedFrame.startsWith("data:")) continue;
            const payload = trimmedFrame.slice(5).trim();
            if (!payload) continue;
            let evt: ChatStreamFrame;
            try {
              evt = JSON.parse(payload) as ChatStreamFrame;
            } catch {
              continue;
            }
            if (evt.type === "status") {
              patchAssistant((m) => ({ ...m, status: evt.message }));
            } else if (evt.type === "delta") {
              if (evt.content) {
                streamed = true;
                patchAssistant((m) => ({
                  ...m,
                  status: undefined,
                  content: m.content + evt.content,
                }));
              }
            } else if (evt.type === "tool_call") {
              patchAssistant((m) => ({
                ...m,
                status: undefined,
                steps: [
                  ...(m.steps ?? []),
                  { id: generateId(), tool: evt.tool ?? "tool", status: "running" as const },
                ],
              }));
            } else if (evt.type === "tool_result") {
              patchAssistant((m) => {
                const steps = (m.steps ?? []).slice();
                for (let k = steps.length - 1; k >= 0; k--) {
                  if (steps[k].tool === evt.tool && steps[k].status === "running") {
                    steps[k] = { ...steps[k], status: "done", summary: evt.summary };
                    break;
                  }
                }
                return { ...m, steps };
              });
            } else if (evt.type === "done") {
              gotContent = true;
              patchAssistant((m) => ({
                ...m,
                status: undefined,
                content: streamed ? m.content : evt.content || m.content || "",
              }));
            }
          }
        }
        if (!gotContent) {
          patchAssistant((m) => ({
            ...m,
            content: m.content || "(no response)",
            status: undefined,
          }));
        }
      } catch (e: unknown) {
        if (abort.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) {
          return;
        }
        const message = e instanceof Error ? e.message : "stream failed";
        patchAssistant((m) => ({
          ...m,
          status: undefined,
          steps: (m.steps ?? []).map((st) =>
            st.status === "running" ? { ...st, status: "error" as const } : st,
          ),
          content: `Error: ${message}`,
        }));
      } finally {
        sendInFlightRef.current = false;
        if (epochRef.current === epoch) setBusy(false);
      }
    },
    [busy, model, session, turns, workspaceId],
  );

  const canCompose = Boolean(session && model && !loadError);

  return (
    <div
      className="agent-dock-conversation"
      role="complementary"
      aria-label="Workspace Agent"
      data-testid="workspace-agent-dock"
    >
      {!loadError && !session && (
        <div className="agent-dock-status" role="status" style={{ padding: "10px 12px" }}>
          Opening the Workspace Agent…
        </div>
      )}
      {loadError && (
        <div className="agent-dock-empty" role="alert" style={{ padding: "10px 12px" }}>
          {loadError}
        </div>
      )}
      {session && (
        <>
          <div className="agent-dock-messages" role="log" aria-live="polite" aria-label="Workspace Agent messages">
            {turns.length === 0 && (
              <div className="agent-dock-empty" role="status">
                Ask your Workspace Agent anything — workspace ops, workflows, runs, approvals.
              </div>
            )}
            {turns.map((turn) => (
              <div key={turn.id} className={`agent-dock-turn agent-dock-turn--${turn.role}`}>
                {(turn.steps ?? []).length > 0 && (
                  <div className="agent-dock-steps">
                    {(turn.steps ?? []).map((step) => (
                      <div key={step.id} className={`agent-dock-step agent-dock-step--${step.status}`}>
                        <span aria-hidden="true">{step.status === "done" ? "✓" : step.status === "error" ? "✕" : "⟳"}</span>
                        <span>{step.tool}</span>
                        {step.summary && <span className="agent-dock-step-summary">{step.summary}</span>}
                      </div>
                    ))}
                  </div>
                )}
                {turn.status && (
                  <div className="agent-dock-status" role="status">{turn.status}</div>
                )}
                {turn.content && (
                  <div className="agent-dock-bubble" style={{ whiteSpace: "pre-wrap" }}>
                    {turn.content}
                  </div>
                )}
              </div>
            ))}
            <div ref={listEndRef} />
          </div>
          <form
            className="agent-dock-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send(input);
            }}
          >
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              disabled={!canCompose || busy}
              placeholder={canCompose ? "Message your Workspace Agent…" : "Workspace Agent unavailable"}
              aria-label="Message the Workspace Agent"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(input);
                }
              }}
            />
            <button
              type="submit"
              className="agent-dock-send"
              disabled={!canCompose || busy || !input.trim()}
              aria-label="Send to Workspace Agent"
            >
              →
            </button>
          </form>
        </>
      )}
    </div>
  );
}

export function WorkspaceAgentDock() {
  const { activeWorkspaceId } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const launcherRef = useRef<HTMLButtonElement>(null);

  // Keyboard journeys: Escape closes the panel and restores focus to the
  // launcher; the launcher toggles with Enter/Space natively (real <button>).
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && open) {
      e.stopPropagation();
      setOpen(false);
      launcherRef.current?.focus();
    }
  };

  const close = useCallback(() => {
    setOpen(false);
    launcherRef.current?.focus();
  }, []);

  return (
    <div className="agent-dock" data-testid="workspace-agent-dock-root" onKeyDown={onKeyDown}>
      {open && (
        // Opens with or without an active Workspace — a launcher that flips
        // `aria-expanded` while rendering nothing is the dead-button lie
        // (#2549 AC-6 honesty). Keyed remount per Workspace: switching
        // Workspaces is an unmount, so session state never leaks across the
        // switch and the in-flight stream aborts in cleanup.
        <WorkspaceAgentDockPanel onClose={close}>
          {activeWorkspaceId ? (
            <WorkspaceAgentConversation key={activeWorkspaceId} workspaceId={activeWorkspaceId} />
          ) : (
            <div
              className="agent-dock-conversation"
              role="complementary"
              aria-label="Workspace Agent"
              data-testid="workspace-agent-dock"
            >
              <div className="agent-dock-empty" role="status">
                No workspace selected — the Workspace Agent works inside your active Workspace.
                Create or select a Workspace, then ask here.
              </div>
            </div>
          )}
        </WorkspaceAgentDockPanel>
      )}
      <button
        ref={launcherRef}
        type="button"
        className="agent-dock-launcher"
        data-testid="workspace-agent-launcher"
        aria-expanded={open}
        aria-controls="workspace-agent-panel"
        onClick={() => {
          const next = !open;
          setOpen(next);
          if (next) {
            setTimeout(() => {
              document
                .querySelector<HTMLTextAreaElement>(".agent-dock-composer textarea")
                ?.focus();
            }, 0);
          }
        }}
        title="Workspace Agent"
      >
        <MessageCircle size={16} strokeWidth={1.5} aria-hidden />
        <span>Agent</span>
      </button>
    </div>
  );
}

function WorkspaceAgentDockPanel({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div id="workspace-agent-panel" className="agent-dock-panel-wrap">
      <div className="agent-dock-header">
        <span className="agent-dock-title">
          <MessageCircle size={14} strokeWidth={1.5} aria-hidden />
          Workspace Agent
        </span>
        <button
          type="button"
          className="agent-dock-close"
          onClick={onClose}
          aria-label="Close Workspace Agent"
        >
          <X size={14} aria-hidden />
        </button>
      </div>
      {children}
    </div>
  );
}
