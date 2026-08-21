import { useState } from "react";
import { api, planScene } from "../lib/api";

export default function SceneBuilder({ onSceneCreated }) {
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState(null);
  const [progress, setProgress] = useState([]);

  const canBuild = description.trim() && !status;

  const handleBuild = async () => {
    if (!canBuild) return;
    setStatus("planning");
    setProgress(["Decomposing scene..."]);

    try {
      const plan = await planScene(description.trim());
      setProgress([`Plan: "${plan.name}" with ${plan.layers.length} layers`]);

      setStatus("creating");
      const canvas = await api.createCanvas({
        name: plan.name,
        aspect_ratio: plan.aspect_ratio || "16:9",
        background_color: plan.background_color || "#000000",
      });

      const layers = [];
      for (const lp of plan.layers) {
        setProgress((p) => [
          ...p.slice(0, 1),
          `Creating layer: ${lp.name}`,
        ]);
        const layer = await api.addLayer(canvas.id, {
          name: lp.name,
          layer_type: lp.layer_type || "object",
          z_index: lp.z_index,
        });
        layers.push({ ...layer, _prompt: lp.prompt });
      }

      setStatus("generating");
      for (let i = 0; i < layers.length; i++) {
        const ly = layers[i];
        setProgress((p) => [
          ...p.slice(0, 1),
          `Generating ${i + 1}/${layers.length}: ${ly.name}`,
        ]);
        try {
          await api.startGenerate(canvas.id, ly.id, {
            action: "generate",
            prompt: ly._prompt,
            model_id: "azure-gpt-image-2",
          });
        } catch (genErr) {
          setProgress((p) => [
            ...p,
            `Warning: ${ly.name} failed (${genErr.message}), continuing...`,
          ]);
        }
      }

      setProgress((p) => [...p.slice(0, 1), "Done!"]);
      setStatus(null);
      onSceneCreated(canvas);
    } catch (err) {
      setProgress((p) => [...p, `Error: ${err.message}`]);
      setStatus(null);
    }
  };

  return (
    <div className="panel-section" style={{ borderBottom: "2px solid var(--phosphor)" }}>
      <h3>Describe Your Scene</h3>
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder='e.g. "A cyberpunk cityscape at night with neon signs, rain-slicked streets, and a lone figure in a trench coat walking towards the camera"'
        rows={3}
        style={{ width: "100%", marginBottom: 8 }}
        disabled={!!status}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canBuild) {
            e.preventDefault();
            handleBuild();
          }
        }}
      />
      <button
        className="primary"
        style={{ width: "100%" }}
        disabled={!canBuild}
        onClick={handleBuild}
      >
        {status === "planning"
          ? "Planning..."
          : status === "creating"
            ? "Creating layers..."
            : status === "generating"
              ? "Generating images..."
              : "Build Scene"}
      </button>
      {progress.length > 0 && (
        <div
          style={{
            marginTop: 8,
            fontFamily: "var(--font)",
            fontSize: 11,
            color: "var(--text-dim)",
            maxHeight: 120,
            overflowY: "auto",
          }}
        >
          {progress.map((msg, i) => (
            <div
              key={i}
              style={{
                color: msg.startsWith("Error")
                  ? "var(--burn)"
                  : msg.startsWith("Warning")
                    ? "var(--amber)"
                    : i === 0
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
