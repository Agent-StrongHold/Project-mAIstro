import { useState } from "react";
import {
  refineStyleContract,
  updateStyleContract,
  generateScene,
  updateScene,
} from "../lib/storyApi";

export default function RefinePanel({ story, scene, onUpdated }) {
  const [feedback, setFeedback] = useState("");
  const [scope, setScope] = useState("scene");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState(null);

  if (!story || !scene) {
    return (
      <div className="panel-section">
        <h3>Refine</h3>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          Select a scene to refine
        </p>
      </div>
    );
  }

  const handleRefine = async () => {
    if (!feedback.trim() || working) return;
    setError(null);
    setWorking(true);

    try {
      if (scope === "style") {
        const newContract = await refineStyleContract(
          story.style_contract,
          feedback.trim(),
          scene.title
        );
        updateStyleContract(story.id, newContract);
      }

      await generateScene(story.id, scene.id, () => {});
      updateScene(story.id, scene.id, { status: "done" });
      setFeedback("");
      onUpdated();
    } catch (err) {
      setError(err.message);
    } finally {
      setWorking(false);
    }
  };

  const contract = story.style_contract;

  return (
    <div
      className="panel-section gen-panel"
      style={{ flexShrink: 0, borderTop: "2px solid var(--phosphor)" }}
    >
      <h3>Refine</h3>

      <div className="row">
        <button
          style={{
            flex: 1,
            borderColor: scope === "scene" ? "var(--phosphor)" : undefined,
            background: scope === "scene" ? "var(--phosphor-bg)" : undefined,
          }}
          onClick={() => setScope("scene")}
        >
          This Scene
        </button>
        <button
          style={{
            flex: 1,
            borderColor: scope === "style" ? "var(--phosphor)" : undefined,
            background: scope === "style" ? "var(--phosphor-bg)" : undefined,
          }}
          onClick={() => setScope("style")}
        >
          Style Contract
        </button>
      </div>

      {scope === "style" && (
        <div
          style={{
            background: "var(--ink-2)",
            borderRadius: 4,
            padding: 8,
            marginBottom: 8,
            fontSize: 11,
            color: "var(--text-dim)",
          }}
        >
          <div><b>Current:</b> {contract.art_style}</div>
          <div><b>Lighting:</b> {contract.lighting}</div>
          <div><b>Mood:</b> {contract.mood}</div>
          <div>
            <b>Palette:</b>{" "}
            {(contract.color_palette || []).map((c, i) => (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 10,
                  background: c,
                  borderRadius: 2,
                  marginRight: 3,
                  verticalAlign: "middle",
                }}
              />
            ))}
          </div>
        </div>
      )}

      <textarea
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        placeholder={
          scope === "style"
            ? 'e.g. "make it more saturated, warmer tones, switch to watercolor style"'
            : 'e.g. "move the character to the left, make the sky more dramatic, add fog"'
        }
        rows={2}
        style={{ width: "100%", marginBottom: 8 }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            handleRefine();
          }
        }}
      />

      <button
        className="primary"
        style={{ width: "100%" }}
        disabled={!feedback.trim() || working}
        onClick={handleRefine}
      >
        {working
          ? "Refining..."
          : scope === "style"
            ? "Update Style + Regenerate"
            : "Refine Scene"}
      </button>

      {error && (
        <p style={{ color: "var(--burn)", marginTop: 8, fontSize: 13 }}>
          {error}
        </p>
      )}
    </div>
  );
}
