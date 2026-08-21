import { useState, useEffect } from "react";
import { api, IMAGE_MODELS } from "../lib/api";

export default function GenerationPanel({
  canvas,
  layers,
  selectedLayerId,
  onLayerUpdated,
}) {
  const layer = layers?.find((l) => l.id === selectedLayerId);
  const [prompt, setPrompt] = useState("");
  const [negPrompt, setNegPrompt] = useState("");
  const [tier, setTier] = useState("draft");
  const [action, setAction] = useState("generate");
  const [modelId, setModelId] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!modelId) {
      setModelId(IMAGE_MODELS.draft[0].id);
    }
  }, []);

  useEffect(() => {
    if (tier === "draft") {
      if (!IMAGE_MODELS.draft.find((m) => m.id === modelId)) {
        setModelId(IMAGE_MODELS.draft[0].id);
      }
    } else {
      if (!IMAGE_MODELS.proof.find((m) => m.id === modelId)) {
        setModelId(IMAGE_MODELS.proof[0].id);
      }
    }
  }, [tier]);

  if (!layer) {
    return (
      <div className="panel-section">
        <h3>Generate</h3>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          Select a layer to generate images
        </p>
      </div>
    );
  }

  if (layer.layer_type === "text") {
    return (
      <div className="panel-section">
        <h3>Generate</h3>
        <p style={{ color: "var(--amber)", fontSize: 13 }}>
          TEXT LAYER &mdash; use composite/text tools
        </p>
      </div>
    );
  }

  const canGenerate =
    !generating &&
    prompt.trim() &&
    (action !== "refine" || layer.image_path || layer.image_url);

  const handleGenerate = async () => {
    setError(null);
    setGenerating(true);

    try {
      await api.startGenerate(canvas.id, layer.id, {
        action,
        prompt: prompt.trim(),
        negative_prompt: negPrompt.trim() || undefined,
        tier,
        model_id: modelId,
        count: 1,
      });
      onLayerUpdated();
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  };

  const currentModels = tier === "draft" ? IMAGE_MODELS.draft : IMAGE_MODELS.proof;

  return (
    <div className="panel-section gen-panel">
      <h3>Generate</h3>

      <div className="row">
        <select value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="generate">GENERATE</option>
          <option
            value="refine"
            disabled={!layer.image_path && !layer.image_url}
          >
            REFINE
          </option>
          <option value="reference">REFERENCE</option>
        </select>
        <select value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="draft">DRAFT</option>
          <option value="proof">PROOF</option>
        </select>
      </div>

      <label>Model</label>
      <select
        value={modelId || ""}
        onChange={(e) => setModelId(e.target.value)}
        style={{ width: "100%", marginBottom: 10 }}
      >
        {currentModels.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name} ({m.provider})
          </option>
        ))}
      </select>

      <label>Prompt</label>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Describe what to generate..."
        rows={3}
      />

      <label>Negative prompt</label>
      <textarea
        value={negPrompt}
        onChange={(e) => setNegPrompt(e.target.value)}
        placeholder="What to avoid (optional)..."
        rows={2}
      />

      <button
        className="primary"
        style={{ width: "100%", marginTop: 10 }}
        disabled={!canGenerate}
        onClick={handleGenerate}
      >
        {generating ? "Generating..." : layer.image_url ? "Regenerate" : "Generate"}
      </button>

      {error && (
        <p style={{ color: "var(--burn)", marginTop: 8, fontSize: 13 }}>
          {error}
        </p>
      )}
    </div>
  );
}
