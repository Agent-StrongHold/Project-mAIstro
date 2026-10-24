import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, apiGet, apiPost, fallbackMessage } from "../lib/api";
import { randomId } from "../lib/ids";
import type { ChatApiMessage, ChatSessionDetail, ChatSessionSummary } from "../lib/chatSessions";
import {
  fetchModelsCatalog,
  openChatStream,
  sessionPath,
  sessionsListPath,
} from "../lib/chatSessions";
import type {
  BriefField,
  BriefView,
  Message,
  Session,
  ToolStep,
} from "../lib/chatUi";
import { useWorkspaces } from "../context/WorkspaceContext";

const SOURCE_LABEL: Record<BriefField["source"], string> = {
  user: "you",
  verbatim: "as said",
  record: "from record",
  assumed: "assumed",
  open: "open",
};

function BriefSoFar({ brief }: { brief: BriefView }) {
  if (brief.draft) {
    return (
      <aside className="brief-panel card" aria-label="Brief draft">
        <div className="brief-panel-head">
          <span>Draft ready</span>
          <span className="brief-panel-meta">nothing written yet</span>
        </div>
        {Object.entries(brief.draft.fields).map(([key, value]) => (
          <div key={key} className={`brief-row${brief.draft?.assumed.includes(key) ? " brief-row--assumed" : ""}`}>
            <span className="brief-row-label">{key}</span>
            <span className="brief-row-value">{value}</span>
            <span className="brief-tag">{brief.draft?.assumed.includes(key) ? "assumed" : "known"}</span>
          </div>
        ))}
      </aside>
    );
  }
  if (!brief.summary) return null;
  return (
    <aside className="brief-panel card" aria-label="Brief so far" aria-live="polite">
      <div className="brief-panel-head">
        <span>Brief so far</span>
        <span className="brief-panel-meta">
          {brief.summary.known} of {brief.summary.needed} needed · nothing written yet
        </span>
      </div>
      {brief.summary.fields.map((f) => (
        <div key={f.key} className={`brief-row brief-row--${f.source}`}>
          <span className="brief-row-label">{f.label}</span>
          <span className="brief-row-value">{f.value ?? "not yet"}</span>
          <span className="brief-tag">{SOURCE_LABEL[f.source]}</span>
        </div>
      ))}
    </aside>
  );
}

const SUGGESTED_PROMPTS_HEADING = "Chat, then turn it into an agent, a DAG, or a recurring workflow";
const SUGGESTED_PROMPTS = [
  "What agents and workflows do I already have?",
  "Build a DAG workflow for this and run it",
  "Turn this into an agent I can reuse",
];

// Keep the request payload bounded — mirrors the shipped client (messages.slice(-20)).
const HISTORY_LIMIT = 20;

function generateId() {
  // Ids name messages and sessions that later requests refer back to, so
  // they come from the CSPRNG rather than Math.random -- via `randomId`,
  // which works over plain HTTP too (see lib/ids.ts).
  return randomId();
}

function formatTime(date: Date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function compactArgs(args?: Record<string, unknown>): string {
  if (!args) return "";
  try {
    const s = Object.entries(args)
      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
      .join(", ");
    return s.length > 80 ? `${s.slice(0, 77)}…` : s;
  } catch {
    return "";
  }
}

// --- Dependency-free markdown for the subset the backend emits ---
// (**bold**, `inline code`, ``` fenced code ```, • / - bullets, --- rules).
// Intentionally renders to React nodes (no dangerouslySetInnerHTML / no XSS surface).
function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) nodes.push(<code key={`${keyBase}-c${i}`}>{tok.slice(1, -1)}</code>);
    else nodes.push(<strong key={`${keyBase}-b${i}`}>{tok.slice(2, -2)}</strong>);
    last = m.index + tok.length;
    i++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // consume closing fence
      blocks.push(
        <pre key={key++} className="md-code">
          <code>{buf.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    if (trimmed === "---") {
      blocks.push(<hr key={key++} className="md-hr" />);
      i++;
      continue;
    }
    if (/^\s*[•\-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[•\-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[•\-*]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="md-ul">
          {items.map((it, j) => (
            <li key={j}>{renderInline(it, `li${key}-${j}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    if (trimmed === "") {
      i++;
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("```") &&
      lines[i].trim() !== "---" &&
      !/^\s*[•\-*]\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="md-p">
        {para.map((p, j) => (
          <span key={j}>
            {renderInline(p, `p${key}-${j}`)}
            {j < para.length - 1 ? <br /> : null}
          </span>
        ))}
      </p>,
    );
  }
  return <>{blocks}</>;
}

function ToolSteps({ steps }: { steps: ToolStep[] }) {
  return (
    <div className="tool-steps">
      {steps.map((step) => (
        <div key={step.id} className={`tool-step tool-step--${step.status}`}>
          <span className="tool-step-icon" aria-hidden="true">
            {step.status === "done" ? "✓" : step.status === "error" ? "✕" : "⟳"}
          </span>
          <span className="tool-step-name">{step.tool}</span>
          {step.args && Object.keys(step.args).length > 0 && (
            <span className="tool-step-args">{compactArgs(step.args)}</span>
          )}
          {step.summary && <span className="tool-step-summary">{step.summary}</span>}
        </div>
      ))}
    </div>
  );
}

function apiMessagesToUi(messages: ChatApiMessage[]): Message[] {
  return messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      id: m.id,
      role: m.role as Role,
      content: m.content,
      timestamp: m.timestamp ? new Date(m.timestamp) : new Date(),
    }));
}

function detailToSession(detail: ChatSessionDetail): Session {
  return {
    id: detail.id,
    title: detail.title,
    messages: apiMessagesToUi(detail.messages),
    createdAt: new Date(detail.created_at),
  };
}

export default function ChatPage() {
  // #1822: sessions and transcripts are Workspace-scoped durable rows. The
  // drawer hydrates from `/v1/chat/sessions`; stream carries `session_id` so
  // execute_turn can append into maistro.sessions. Stale stream callbacks are
  // aborted on Workspace/session switch.
  const { activeWorkspaceId, ready: workspacesReady } = useWorkspaces();
  const [searchParams, setSearchParams] = useSearchParams();
  const pendingDeepLinkRef = useRef<string | null>(searchParams.get("session"));
  const suggestedPromptsHeading = SUGGESTED_PROMPTS_HEADING;
  const suggestedPrompts = SUGGESTED_PROMPTS;
  const [models, setModels] = useState<string[]>([]);
  const MODELS = models;
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [model, setModel] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const listEndRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamEpochRef = useRef(0);
  // Monotonic generation for session open/create requests, bumped on every
  // Workspace switch and before each drawer-triggered open/create, so a late
  // response can never commit another Workspace's transcript or selection.
  const sessionReqRef = useRef(0);

  useEffect(() => {
    const linked = searchParams.get("session");
    if (linked) pendingDeepLinkRef.current = linked;
  }, [searchParams]);

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
        if (list.length > 0) {
          setModels(list);
          setModel(list[0]);
        }
      })
      .catch(() => {});
  }, []);

  const activeSession =
    sessions.find((s) => s.id === activeId) ??
    ({ id: "", title: "Chat", messages: [], createdAt: new Date() } satisfies Session);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession.messages, streaming]);

  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.rows = 1;
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, [input]);

  const updateSession = useCallback((id: string, updater: (s: Session) => Session) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? updater(s) : s)));
  }, []);

  const openSession = useCallback(async (sessionId: string) => {
    const req = sessionReqRef.current;
    const detail = await apiGet<ChatSessionDetail>(sessionPath(sessionId));
    // Superseded by a Workspace switch or a newer open/create: drop the
    // response before it can touch React state.
    if (sessionReqRef.current !== req) return null;
    const session = detailToSession(detail);
    setSessions((prev) => {
      const rest = prev.filter((s) => s.id !== session.id);
      return [session, ...rest];
    });
    setActiveId(session.id);
    return session;
  }, []);

  const createServerSession = useCallback(
    async (title = "New Chat") => {
      if (!activeWorkspaceId) throw new Error("No Workspace selected");
      const req = sessionReqRef.current;
      const detail = await apiPost<ChatSessionDetail>("/v1/chat/sessions", {
        title,
        workspace_id: activeWorkspaceId,
      });
      if (sessionReqRef.current !== req) return null;
      const session = detailToSession(detail);
      setSessions((prev) => [session, ...prev.filter((s) => s.id !== session.id)]);
      setActiveId(session.id);
      return session;
    },
    [activeWorkspaceId],
  );

  useEffect(() => {
    if (!workspacesReady) return;
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    streamEpochRef.current += 1;
    // Invalidate any in-flight session open/create from the previous Workspace.
    sessionReqRef.current += 1;
    const sessionGeneration = sessionReqRef.current;
    setStreaming(false);
    setInput("");
    setLoadError(null);

    if (!activeWorkspaceId) {
      setSessions([]);
      setActiveId("");
      setLoadingSessions(false);
      return;
    }

    let cancelled = false;
    setLoadingSessions(true);
    const tick = setTimeout(() => {
      void (async () => {
        try {
          const list = await apiGet<ChatSessionSummary[]>(sessionsListPath(activeWorkspaceId));
          if (cancelled || sessionReqRef.current !== sessionGeneration) return;
          if (list.length === 0) {
            const created = await createServerSession();
            if (cancelled || sessionReqRef.current !== sessionGeneration || !created) return;
            setSessions([created]);
            setActiveId(created.id);
            pendingDeepLinkRef.current = null;
          } else {
            const linked = pendingDeepLinkRef.current;
            pendingDeepLinkRef.current = null;
            const preferred =
              linked && list.some((s) => s.id === linked) ? linked : list[0].id;
            const opened = await openSession(preferred);
            if (cancelled || sessionReqRef.current !== sessionGeneration || !opened) return;
            // Keep other summaries in the drawer without full histories yet.
            const others: Session[] = list
              .filter((s) => s.id !== opened.id)
              .map((s) => ({
                id: s.id,
                title: s.title,
                messages: [],
                createdAt: new Date(s.updated_at),
              }));
            setSessions([opened, ...others]);
            if (linked && searchParams.get("session")) {
              const next = new URLSearchParams(searchParams);
              next.delete("session");
              setSearchParams(next, { replace: true });
            }
          }
          setLoadError(null);
        } catch (e) {
          if (cancelled || sessionReqRef.current !== sessionGeneration) return;
          setSessions([]);
          setActiveId("");
          setLoadError(e instanceof ApiError ? e.message : "Couldn't load chat sessions.");
        } finally {
          if (!cancelled) setLoadingSessions(false);
        }
      })();
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(tick);
    };
    // searchParams / setSearchParams are read only to consume ?session= once;
    // listing them would re-hydrate when the param is cleared.
  }, [activeWorkspaceId, workspacesReady, createServerSession, openSession]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming || !activeWorkspaceId || !activeId) return;
      const sessionId = activeId;
      const epoch = streamEpochRef.current;
      streamAbortRef.current?.abort();
      const abort = new AbortController();
      streamAbortRef.current = abort;

      const userMsg: Message = { id: generateId(), role: "user", content: text.trim(), timestamp: new Date() };
      const assistantId = generateId();
      const assistantMsg: Message = {
        id: assistantId,
        role: "assistant",
        content: "",
        steps: [],
        status: "Sending…",
        timestamp: new Date(),
      };

      const prior = (sessions.find((s) => s.id === sessionId)?.messages ?? [])
        .filter((m) => m.content)
        .map((m) => ({ role: m.role, content: m.content }));
      const outbound = [...prior, { role: "user", content: text.trim() }].slice(-HISTORY_LIMIT);

      updateSession(sessionId, (s) => ({
        ...s,
        title: s.messages.length === 0 ? text.trim().slice(0, 30) : s.title,
        messages: [...s.messages, userMsg, assistantMsg],
      }));

      setInput("");
      setStreaming(true);
      setTimeout(() => textareaRef.current?.focus(), 0);

      const patchAssistant = (fn: (m: Message) => Message) => {
        if (streamEpochRef.current !== epoch) return;
        updateSession(sessionId, (s) => ({
          ...s,
          messages: s.messages.map((m) => (m.id === assistantId ? fn(m) : m)),
        }));
      };

      try {
        const res = await openChatStream(
          {
            model,
            messages: outbound,
            workspace_id: activeWorkspaceId,
            session_id: sessionId,
          },
          abort.signal,
        );
        if (!res.ok || !res.body) throw new Error(fallbackMessage(res.status));

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let gotContent = false;
        let streamed = false; // any content tokens arrived via `delta`

        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? ""; // keep any partial frame for the next chunk
          for (const frame of frames) {
            const trimmed = frame.trim();
            if (!trimmed.startsWith("data:")) continue;
            const payload = trimmed.slice(5).trim();
            if (!payload) continue;
            let evt: any;
            try {
              evt = JSON.parse(payload);
            } catch {
              continue;
            }
            if (evt.type === "brief") {
              // The interview's state after this turn: open (summary + question),
              // drafted (the draft, nothing written), or gone (dropped).
              const view: BriefView | null = evt.interview || evt.draft ? evt : null;
              updateSession(sessionId, (s) => ({ ...s, brief: view }));
            } else if (evt.type === "status") {
              patchAssistant((m) => ({ ...m, status: evt.message }));
            } else if (evt.type === "delta") {
              if (evt.content) {
                streamed = true;
                patchAssistant((m) => ({ ...m, status: undefined, content: m.content + evt.content }));
              }
            } else if (evt.type === "thinking") {
              if (evt.content) {
                patchAssistant((m) => ({ ...m, status: undefined, reasoning: (m.reasoning ?? "") + evt.content }));
              }
            } else if (evt.type === "tool_call") {
              patchAssistant((m) => ({
                ...m,
                status: undefined,
                steps: [...(m.steps ?? []), { id: generateId(), tool: evt.tool, args: evt.args, status: "running" }],
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
              // Tokens already appended via `delta`; done.content is a fallback only
              // (non-streaming backend, or no deltas received).
              patchAssistant((m) => ({
                ...m,
                status: undefined,
                content: streamed ? m.content : evt.content || m.content || "",
              }));
            }
          }
        }

        if (!gotContent) {
          patchAssistant((m) => ({ ...m, content: m.content || "(no response)", status: undefined }));
        }
      } catch (e: unknown) {
        if (abort.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) {
          return;
        }
        const message = e instanceof Error ? e.message : "stream failed";
        patchAssistant((m) => ({
          ...m,
          status: undefined,
          steps: (m.steps ?? []).map((st) => (st.status === "running" ? { ...st, status: "error" } : st)),
          content: `Error: ${message}`,
        }));
      } finally {
        if (streamEpochRef.current === epoch) {
          setStreaming(false);
          setTimeout(() => textareaRef.current?.focus(), 0);
        }
      }
    },
    [activeId, streaming, model, sessions, updateSession, activeWorkspaceId],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage(input);
    }
  };

  const abortActiveStream = () => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    streamEpochRef.current += 1;
    setStreaming(false);
  };

  const newSession = () => {
    if (!activeWorkspaceId || loadingSessions) return;
    abortActiveStream();
    // Invalidate any in-flight open/create before creating a new session.
    sessionReqRef.current += 1;
    void (async () => {
      try {
        await createServerSession();
        setLoadError(null);
        setDrawerOpen(false);
        setTimeout(() => textareaRef.current?.focus(), 0);
      } catch (e) {
        setLoadError(e instanceof ApiError ? e.message : "Couldn't create a chat session.");
      }
    })();
  };

  const switchSession = (id: string) => {
    if (id === activeId) {
      setDrawerOpen(false);
      return;
    }
    abortActiveStream();
    // Invalidate any in-flight open/create before requesting this session.
    sessionReqRef.current += 1;
    void (async () => {
      try {
        await openSession(id);
        setLoadError(null);
        setDrawerOpen(false);
        setTimeout(() => textareaRef.current?.focus(), 0);
      } catch (e) {
        setLoadError(e instanceof ApiError ? e.message : "Couldn't open that chat session.");
      }
    })();
  };

  const canCompose = Boolean(activeWorkspaceId && activeId && !loadingSessions && !loadError);
  const isEmpty = canCompose && activeSession.messages.length === 0;

  if (workspacesReady && !activeWorkspaceId) {
    return (
      <div className="chat-layout">
        <main className="chat-main">
          {/* Keep aria-label so navigation-coverage e2e can probe Chat. */}
          <div role="log" aria-live="polite" aria-label="Chat messages" className="message-list">
            <div className="empty-state" role="status">
              <p className="empty-title">Select a Workspace</p>
              <p className="empty-subtitle">
                Chat sessions are Workspace-scoped. Pick or create a Workspace in the tab bar first.
              </p>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="chat-layout">
      {drawerOpen && <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)} aria-hidden="true" />}
      <aside className={`drawer${drawerOpen ? " drawer--open" : ""}`} aria-label="Chat sessions">
        <div className="drawer-header">
          <span className="drawer-title">Sessions</span>
          <button
            className="btn-icon"
            onClick={newSession}
            aria-label="New chat"
            disabled={!activeWorkspaceId || loadingSessions}
          >
            ＋
          </button>
        </div>
        <nav>
          {sessions.map((s) => (
            <button
              key={s.id}
              className={`drawer-link${s.id === activeId ? " drawer-link--active" : ""}`}
              onClick={() => switchSession(s.id)}
              aria-current={s.id === activeId ? "page" : undefined}
            >
              <span className="drawer-link-title">{s.title}</span>
              <span className="drawer-link-time">{formatTime(s.createdAt)}</span>
            </button>
          ))}
        </nav>
      </aside>
      <div className="chat-layout">
        <header className="chat-header">
          <button
            className="btn-icon hamburger"
            onClick={() => setDrawerOpen((o) => !o)}
            aria-label="Toggle session drawer"
            aria-expanded={drawerOpen}
          >
            ☰
          </button>
          <span className="chat-header-title">AI Assistant</span>
          <div className="model-selector">
            <button
              className="btn-model"
              onClick={() => setModelOpen((o) => !o)}
              aria-haspopup="listbox"
              aria-expanded={modelOpen}
              aria-label={`Current model: ${model}`}
            >
              {model} <span aria-hidden="true">▾</span>
            </button>
            {modelOpen && (
              <ul className="model-dropdown" role="listbox" aria-label="Select model">
                {MODELS.map((m) => (
                  <li
                    key={m}
                    role="option"
                    aria-selected={m === model}
                    className={`model-option${m === model ? " model-option--active" : ""}`}
                    onClick={() => {
                      setModel(m);
                      setModelOpen(false);
                    }}
                  >
                    {m}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </header>
        <main className="chat-main">
          {activeSession.brief && <BriefSoFar brief={activeSession.brief} />}
          <div role="log" aria-live="polite" aria-label="Chat messages" className="message-list">
            {loadingSessions && (
              <div className="empty-state" role="status">
                <p className="empty-title">Loading sessions…</p>
              </div>
            )}
            {!loadingSessions && loadError && (
              <div className="empty-state" role="alert">
                <p className="empty-title">Chat unavailable</p>
                <p className="empty-subtitle">{loadError}</p>
              </div>
            )}
            {isEmpty && (
              <div className="empty-state">
                <p className="empty-title">What can I help you with?</p>
                <p className="empty-subtitle">{suggestedPromptsHeading}</p>
                <div className="suggested-prompts">
                  {suggestedPrompts.map((p) => (
                    <button
                      key={p}
                      className="card prompt-btn"
                      onClick={() => void sendMessage(p)}
                      aria-label={`Suggested prompt: ${p}`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {activeSession.messages.map((msg) => (
              <div key={msg.id} className={`message message--${msg.role}`}>
                {msg.role === "assistant" && msg.reasoning && (
                  <details className="chat-reasoning">
                    <summary>💭 Reasoning</summary>
                    <div className="chat-reasoning-body">{msg.reasoning}</div>
                  </details>
                )}
                {msg.role === "assistant" && msg.steps && msg.steps.length > 0 && <ToolSteps steps={msg.steps} />}
                {msg.status && (
                  <div className="chat-status" aria-label="Status">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                    {msg.status}
                  </div>
                )}
                {msg.content && (
                  <div className="message-bubble card">
                    {msg.role === "assistant" ? <Markdown text={msg.content} /> : msg.content}
                  </div>
                )}
                <span className="message-time">{formatTime(msg.timestamp)}</span>
              </div>
            ))}
            <div ref={listEndRef} />
          </div>
          <div className="chat-input-bar">
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message… (Enter to send, Shift+Enter for newline)"
              aria-label="Message input"
              rows={2}
              disabled={streaming || !canCompose}
            />
            <button
              className="btn-primary send-btn"
              onClick={() => void sendMessage(input)}
              disabled={!input.trim() || streaming || !canCompose}
              aria-label="Send message"
            >
              Send
            </button>
          </div>
        </main>
      </div>
    </div>
  );
}
