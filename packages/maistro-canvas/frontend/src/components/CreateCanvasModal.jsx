import { useState } from "react";
import { api } from "../lib/api";

const RATIOS = {
  "1:1": [1024, 1024],
  "16:9": [1824, 1024],
  "9:16": [1024, 1824],
  "3:2": [1536, 1024],
  "2:3": [1024, 1536],
  "4:3": [1360, 1024],
  "3:4": [1024, 1360],
};

export default function CreateCanvasModal({ onClose, onCreated }) {
  const [name, setName] = useState("Untitled Canvas");
  const [useRatio, setUseRatio] = useState(true);
  const [ratio, setRatio] = useState("1:1");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [bgColor, setBgColor] = useState("#FFFFFF");
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    setError(null);
    setCreating(true);

    const body = {
      name: name.trim() || "Untitled Canvas",
      background_color: bgColor,
    };

    if (useRatio) {
      body.aspect_ratio = ratio;
    } else {
      body.width = parseInt(width);
      body.height = parseInt(height);
    }

    try {
      const canvas = await api.createCanvas(body);
      onCreated(canvas);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>New Canvas</h2>

        <div className="field">
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="field">
          <label>Dimensions</label>
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <button
              onClick={() => setUseRatio(true)}
              style={{
                flex: 1,
                borderColor: useRatio ? "var(--phosphor)" : undefined,
              }}
            >
              Aspect Ratio
            </button>
            <button
              onClick={() => setUseRatio(false)}
              style={{
                flex: 1,
                borderColor: !useRatio ? "var(--phosphor)" : undefined,
              }}
            >
              Custom
            </button>
          </div>

          {useRatio ? (
            <select value={ratio} onChange={(e) => setRatio(e.target.value)}>
              {Object.keys(RATIOS).map((r) => (
                <option key={r} value={r}>
                  {r} ({RATIOS[r][0]}x{RATIOS[r][1]})
                </option>
              ))}
            </select>
          ) : (
            <div style={{ display: "flex", gap: 8 }}>
              <input
                type="number"
                step={8}
                min={64}
                max={8192}
                value={width}
                onChange={(e) => setWidth(e.target.value)}
                placeholder="Width"
                style={{ flex: 1 }}
              />
              <input
                type="number"
                step={8}
                min={64}
                max={8192}
                value={height}
                onChange={(e) => setHeight(e.target.value)}
                placeholder="Height"
                style={{ flex: 1 }}
              />
            </div>
          )}
        </div>

        <div className="field">
          <label>Background</label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="color"
              value={bgColor}
              onChange={(e) => setBgColor(e.target.value)}
              style={{ width: 40, height: 32, padding: 2 }}
            />
            <input value={bgColor} onChange={(e) => setBgColor(e.target.value)} />
          </div>
        </div>

        {error && (
          <p style={{ color: "var(--burn)", fontSize: 13 }}>{error}</p>
        )}

        <div className="actions">
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={creating} onClick={handleCreate}>
            {creating ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
