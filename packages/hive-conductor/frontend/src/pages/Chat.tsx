import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";

type Role = "user" | "assistant";
type StepStatus = "running" | "done" | "error";

interface ToolStep {
  id: string;
  tool: string;
  args?: Record<string, unknown>;
  status: StepStatus;
  summary?: string;
}

interface Message {
  id: string;
  role: Role;
  content: string;
  reasoning?: string; // assistant only — streamed thinking / reasoning tokens
  steps?: ToolStep[]; // assistant only — the live tool/status timeline
  status?: string; // assistant only — transient status line while streaming
  timestamp: Date;
}

interface Session {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
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
  return Math.random().toString(36).slice(2, 10);
}

function formatTime(date: Date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function createSession(title = "New Chat"): Session {
  return { id: generateId(), title, messages: [], createdAt: new Date() };
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

export default function ChatPage() {
  const suggestedPromptsHeading = SUGGESTED_PROMPTS_HEADING;
  const suggestedPrompts = SUGGESTED_PROMPTS;
  const [models, setModels] = useState<string[]>([]);
  const MODELS = models;
  const [sessions, setSessions] = useState<Session[]>([createSession()]);
  const [activeId, setActiveId] = useState(sessions[0].id);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [model, setModel] = useState("");

  useEffect(() => {
    fetch("/v1/settings/models")
      .then((res) => res.json())
      .then((data) => {
        const arr = Array.isArray(data) ? data : data.models || data.data || [];
        const list = arr.map((m: any) => (typeof m === "string" ? m : m.id || m.name || "")).filter(Boolean);
        if (list.length > 0) {
          setModels(list);
          setModel(list[0]);
        }
      })
      .catch(() => {});
  }, []);
  const [modelOpen, setModelOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const listEndRef = useRef<HTMLDivElement>(null);

  const activeSession = sessions.find((s) => s.id === activeId) ?? sessions[0] ?? createSession();

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

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming) return;
      const sessionId = activeId;
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

      // Build bounded history (prior turns + this one) — the backend is otherwise stateless per request.
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

      const patchAssistant = (fn: (m: Message) => Message) =>
        updateSession(sessionId, (s) => ({
          ...s,
          messages: s.messages.map((m) => (m.id === assistantId ? fn(m) : m)),
        }));

      try {
        const res = await fetch("/v1/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ model, messages: outbound }),
        });
        if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);

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
            if (evt.type === "status") {
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
      } catch (e: any) {
        patchAssistant((m) => ({
          ...m,
          status: undefined,
          steps: (m.steps ?? []).map((st) => (st.status === "running" ? { ...st, status: "error" } : st)),
          content: `Error: ${e.message}`,
        }));
      } finally {
        setStreaming(false);
        setTimeout(() => textareaRef.current?.focus(), 0);
      }
    },
    [activeId, streaming, model, sessions, updateSession],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const newSession = () => {
    const s = createSession();
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
    setDrawerOpen(false);
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const switchSession = (id: string) => {
    setActiveId(id);
    setDrawerOpen(false);
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const isEmpty = activeSession.messages.length === 0;

  return (
    <div className="chat-layout">
      {drawerOpen && <div className="drawer-backdrop" onClick={() => setDrawerOpen(false)} aria-hidden="true" />}
      <aside className={`drawer${drawerOpen ? " drawer--open" : ""}`} aria-label="Chat sessions">
        <div className="drawer-header">
          <span className="drawer-title">Sessions</span>
          <button className="btn-icon" onClick={newSession} aria-label="New chat">
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
          <div role="log" aria-live="polite" aria-label="Chat messages" className="message-list">
            {isEmpty && (
              <div className="empty-state">
                <p className="empty-title">What can I help you with?</p>
                <p className="empty-subtitle">{suggestedPromptsHeading}</p>
                <div className="suggested-prompts">
                  {suggestedPrompts.map((p) => (
                    <button
                      key={p}
                      className="card prompt-btn"
                      onClick={() => sendMessage(p)}
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
              disabled={streaming}
            />
            <button
              className="btn-primary send-btn"
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || streaming}
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
