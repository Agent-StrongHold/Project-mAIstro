import { useState } from "react";
import {
  decomposeStory,
  createStory,
  generateScene,
} from "../lib/storyApi";

export default function StoryInput({ onStoryReady }) {
  const [text, setText] = useState("");
  const [phase, setPhase] = useState(null);
  const [log, setLog] = useState([]);

  const addLog = (msg) => setLog((prev) => [...prev, msg]);

  const handleGo = async () => {
    if (!text.trim() || phase) return;
    setPhase("decomposing");
    setLog(["Analyzing story..."]);

    try {
      addLog("Decomposing into storyboard + style contract...");
      const decomp = await decomposeStory(text.trim());
      addLog(
        `Plan: "${decomp.title}" — ${decomp.scenes.length} scenes, style: ${decomp.style_contract?.art_style || "custom"}`
      );

      const story = createStory(decomp);
      addLog("Generating first scene...");

      const firstScene = story.scenes[0];
      await generateScene(story.id, firstScene.id, (msg) => {
        setLog((prev) => [...prev.slice(0, -1), msg]);
      });
      addLog("First scene complete!");

      setPhase(null);
      onStoryReady(story);
    } catch (err) {
      addLog(`Error: ${err.message}`);
      setPhase(null);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        padding: 40,
        gap: 20,
        maxWidth: 700,
        margin: "0 auto",
      }}
    >
      <div style={{ fontSize: 48, opacity: 0.3 }}>&#9670;</div>
      <h1 style={{ fontFamily: "var(--font)", fontSize: 24, color: "var(--phosphor)" }}>
        CANVAS STUDIO
      </h1>
      <p style={{ color: "var(--text-dim)", textAlign: "center", fontSize: 14 }}>
        Describe your story. The AI will create a storyboard, define a visual style
        contract, and generate the first scene. You refine from there.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder='A lone astronaut crashes on an alien ocean world. She discovers bioluminescent creatures beneath the waves that communicate through light patterns. As she learns their language, she realizes they are warning her about a coming storm that happens once every thousand years.'
        rows={5}
        style={{ width: "100%", fontSize: 14, lineHeight: 1.5 }}
        disabled={!!phase}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            handleGo();
          }
        }}
      />
      <button
        className="primary"
        style={{ width: "100%", padding: "12px 0", fontSize: 15 }}
        disabled={!text.trim() || !!phase}
        onClick={handleGo}
      >
        {phase === "decomposing"
          ? "Building storyboard..."
          : "Create Storyboard"}
      </button>
      <span style={{ fontSize: 11, color: "var(--text-dim)" }}>
        Cmd+Enter to start
      </span>

      {log.length > 0 && (
        <div
          style={{
            width: "100%",
            fontFamily: "var(--font)",
            fontSize: 11,
            background: "var(--ink-2)",
            borderRadius: 6,
            padding: 10,
            color: "var(--text-dim)",
          }}
        >
          {log.map((msg, i) => (
            <div
              key={i}
              style={{
                color: msg.startsWith("Error")
                  ? "var(--burn)"
                  : i === log.length - 1
                    ? "var(--phosphor)"
                    : undefined,
              }}
            >
              {msg}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
