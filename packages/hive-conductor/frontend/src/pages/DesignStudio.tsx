import { useState } from "react";
import { PageHeader } from "../components/shared";

type NodeResult = { id: string; status: "pending" | "running" | "done" | "error"; output?: string };

const PIPELINE_NODES = [
  { id: "style_interpreter", label: "Style Interpreter", icon: "🎨" },
  { id: "composition_planner", label: "Composition", icon: "📐" },
  { id: "generator", label: "Generator", icon: "🖼️" },
  { id: "compositor", label: "Compositor", icon: "🧩" },
  { id: "critic", label: "Critic", icon: "🔍" },
  { id: "refiner", label: "Refiner", icon: "✨" },
];

export default function DesignStudio() {
  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState(false);
  const [nodes, setNodes] = useState<NodeResult[]>(PIPELINE_NODES.map(n => ({ id: n.id, status: "pending" })));
  const [score, setScore] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function runPipeline() {
    if (!prompt.trim()) return;
    setRunning(true);
    setError("");
    setScore(null);
    setNodes(PIPELINE_NODES.map(n => ({ id: n.id, status: "pending" })));

    try {
      // Simulate pipeline progression (real version calls /v1/canvas/run)
      for (let i = 0; i < PIPELINE_NODES.length; i++) {
        setNodes(prev => prev.map((n, idx) => idx === i ? { ...n, status: "running" } : n));
        await new Promise(r => setTimeout(r, 800));
        setNodes(prev => prev.map((n, idx) => idx === i ? { ...n, status: "done", output: `Generated output for ${PIPELINE_NODES[i].label}` } : n));
      }

      // Run eval
      const evalRes = await fetch("/v1/canvas/eval", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ description: prompt }),
      });
      if (evalRes.ok) {
        const data = await evalRes.json();
        setScore(data.score ?? null);
      }
    } catch (e: any) {
      setError(e.message || "Pipeline failed");
      setNodes(prev => prev.map(n => n.status === "running" ? { ...n, status: "error" } : n));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div>
      <PageHeader title="Design Studio" subtitle="Canvas/Davinci visual pipeline — style → compose → generate → critique → refine" />

      {/* Input */}
      <div className="card" style={{ marginBottom: 16 }}>
        <label htmlFor="canvas-prompt" style={{ fontFamily: "var(--hand)", fontSize: 14, display: "block", marginBottom: 8 }}>
          Describe what you want to create:
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            id="canvas-prompt"
            type="text"
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => e.key === "Enter" && runPipeline()}
            placeholder="A whimsical forest scene with bioluminescent mushrooms..."
            style={{ flex: 1, padding: "10px 14px", borderRadius: 8, border: "1px solid var(--rule)", fontFamily: "var(--hand)", fontSize: 14 }}
            disabled={running}
            aria-label="Visual prompt"
          />
          <button
            onClick={runPipeline}
            disabled={running || !prompt.trim()}
            className="btn-primary"
            style={{ padding: "10px 20px", borderRadius: 8, fontFamily: "var(--hand)", fontSize: 14, cursor: running ? "wait" : "pointer" }}
          >
            {running ? "Running..." : "Generate"}
          </button>
        </div>
      </div>

      {/* Pipeline visualization */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--hand)", fontSize: 14, marginBottom: 12, fontWeight: 600 }}>Pipeline</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }} role="list" aria-label="Pipeline stages">
          {PIPELINE_NODES.map((pn, i) => {
            const node = nodes.find(n => n.id === pn.id);
            const statusColor = node?.status === "done" ? "#4caf50" : node?.status === "running" ? "#ff9800" : node?.status === "error" ? "#f44336" : "#ccc";
            return (
              <div key={pn.id} role="listitem" style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <div style={{ padding: "8px 12px", borderRadius: 8, border: `2px solid ${statusColor}`, background: node?.status === "done" ? "#e8f5e9" : node?.status === "running" ? "#fff3e0" : "var(--paper)", textAlign: "center", minWidth: 80 }}>
                  <div style={{ fontSize: 20 }}>{pn.icon}</div>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 9, marginTop: 4 }}>{pn.label}</div>
                  {node?.status === "running" && <div style={{ fontSize: 10, color: "#ff9800" }} aria-live="polite">⏳</div>}
                  {node?.status === "done" && <div style={{ fontSize: 10, color: "#4caf50" }}>✓</div>}
                </div>
                {i < PIPELINE_NODES.length - 1 && <span style={{ color: "var(--pencil)", fontSize: 18 }}>→</span>}
              </div>
            );
          })}
        </div>
      </div>

      {/* Score */}
      {score !== null && (
        <div className="card" style={{ marginBottom: 16, textAlign: "center" }}>
          <div style={{ fontFamily: "var(--hand)", fontSize: 14, marginBottom: 8 }}>Visual Quality Score</div>
          <div style={{ fontSize: 48, fontWeight: 700, color: score >= 75 ? "#4caf50" : score >= 50 ? "#ff9800" : "#f44336" }}>{score}</div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)" }}>/100</div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="card" role="alert" style={{ background: "#fdecea", border: "1px solid #f44336", color: "#b71c1c" }}>
          <strong>Error:</strong> {error}
          <button onClick={() => setError("")} style={{ marginLeft: 12, cursor: "pointer", background: "none", border: "none", color: "#b71c1c", textDecoration: "underline" }}>Dismiss</button>
        </div>
      )}
    </div>
  );
}
