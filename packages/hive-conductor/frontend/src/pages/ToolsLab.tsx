import { useCallback, useEffect, useState } from "react";

const C = { bg: "#0a0914", card: "#11101e", border: "rgba(196,166,97,0.14)", gold: "#c4a661", ink: "#f3f0fb", muted: "#8b83a8", dim: "#5a5478", acc: "#a78bfa", ok: "#7cd4a0", danger: "#e87c7c" };

interface Tool { id: string; name: string; desc: string; icon: string; status: "stopped" | "starting" | "running"; url?: string; }

const TOOLS: Tool[] = [
  { id: "promptfoo", name: "Promptfoo", desc: "LLM eval & red-team testing", icon: "🧪", status: "stopped" },
  { id: "langflow", name: "Langflow", desc: "Visual LangChain/LangGraph builder", icon: "🔀", status: "stopped" },
  { id: "flowise", name: "Flowise", desc: "Low-code LLM app builder", icon: "🌊", status: "stopped" },
  { id: "opik", name: "Opik", desc: "LLM tracing & eval platform", icon: "📡", status: "stopped" },
];

export default function ToolsLab() {
  const [tools, setTools] = useState<Tool[]>(TOOLS);

  const pollStatus = useCallback(async () => {
    try {
      const r = await fetch("/v1/tools-lab/status", { credentials: "same-origin" });
      if (r.ok) {
        const data = await r.json();
        setTools(t => t.map(tool => ({ ...tool, status: data[tool.id]?.status || "stopped", url: data[tool.id]?.url })));
      }
    } catch { /* */ }
  }, []);

  useEffect(() => { pollStatus(); const i = setInterval(pollStatus, 10000); return () => clearInterval(i); }, [pollStatus]);

  const launch = async (id: string) => {
    setTools(t => t.map(tool => tool.id === id ? { ...tool, status: "starting" } : tool));
    try {
      await fetch(`/v1/tools-lab/${id}/start`, { method: "POST", credentials: "same-origin" });
      setTimeout(pollStatus, 3000);
    } catch { setTools(t => t.map(tool => tool.id === id ? { ...tool, status: "stopped" } : tool)); }
  };

  const stop = async (id: string) => {
    await fetch(`/v1/tools-lab/${id}/stop`, { method: "POST", credentials: "same-origin" }).catch(() => {});
    setTools(t => t.map(tool => tool.id === id ? { ...tool, status: "stopped", url: undefined } : tool));
  };

  return (
    <div style={{ minHeight: "100vh", background: C.bg, color: C.ink, fontFamily: "'Inter', -apple-system, system-ui, sans-serif", padding: "1.5rem 2rem" }}>
      <div style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ fontSize: "1.3rem", fontWeight: 700, margin: 0, fontFamily: "Georgia, serif" }}>Tools Lab</h1>
        <p style={{ fontSize: "0.7rem", color: C.muted, margin: "2px 0 0" }}>Eval, workflow, and observability tools — lazy-started on demand</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "0.75rem" }}>
        {tools.map(tool => (
          <div key={tool.id} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: "16px 18px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: "0.9rem", fontWeight: 600 }}>{tool.icon} {tool.name}</div>
                <div style={{ fontSize: "0.66rem", color: C.muted, marginTop: 2 }}>{tool.desc}</div>
              </div>
              <span style={{ fontSize: "0.58rem", padding: "2px 8px", borderRadius: 10, background: tool.status === "running" ? "rgba(124,212,160,0.15)" : tool.status === "starting" ? "rgba(196,166,97,0.15)" : "rgba(90,84,120,0.2)", color: tool.status === "running" ? C.ok : tool.status === "starting" ? C.gold : C.dim }}>
                {tool.status}
              </span>
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
              {tool.status === "stopped" && (
                <button onClick={() => launch(tool.id)} style={{ padding: "5px 14px", borderRadius: 6, border: "none", background: C.acc, color: "#fff", fontSize: "0.66rem", fontWeight: 600, cursor: "pointer" }}>Launch</button>
              )}
              {tool.status === "starting" && (
                <span style={{ fontSize: "0.66rem", color: C.gold }}>Starting...</span>
              )}
              {tool.status === "running" && (
                <>
                  {tool.url && <a href={tool.url} target="_blank" rel="noreferrer" style={{ padding: "5px 14px", borderRadius: 6, border: "none", background: C.acc, color: "#fff", fontSize: "0.66rem", fontWeight: 600, cursor: "pointer", textDecoration: "none" }}>Open</a>}
                  <button onClick={() => stop(tool.id)} style={{ padding: "5px 14px", borderRadius: 6, border: `1px solid ${C.border}`, background: "transparent", color: C.danger, fontSize: "0.66rem", cursor: "pointer" }}>Stop</button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
