import { useState } from "react";
import { api } from "../lib/api";

export default function CompositePreview({ canvas, onClose }) {
  const [image, setImage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [format, setFormat] = useState("png");
  const [quality, setQuality] = useState(90);
  const [showExport, setShowExport] = useState(false);

  useState(() => {
    (async () => {
      try {
        const result = await api.composite(canvas.id);
        setImage(result.image_url || result.image_b64);
      } catch {
        try {
          const latest = await api.getLatestComposite(canvas.id);
          setImage(latest.image_url || latest.image_b64);
        } catch { /* no composite yet; the placeholder stays until one exists */ }
      } finally {
        setLoading(false);
      }
    })();
  });

  const handleExport = () => {
    const url = api.exportUrl(canvas.id, format, quality);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${canvas.name || "canvas"}.${format}`;
    a.click();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal composite-preview"
        onClick={(e) => e.stopPropagation()}
        style={{ minWidth: 500, textAlign: "center" }}
      >
        <h2>Composite Preview</h2>

        {loading ? (
          <p style={{ color: "var(--phosphor)" }}>Compositing...</p>
        ) : image ? (
          <img
            src={image.startsWith("data:") ? image : `data:image/png;base64,${image}`}
            alt="Composite"
            style={{ maxWidth: "100%", borderRadius: 4 }}
          />
        ) : (
          <p style={{ color: "var(--text-dim)" }}>No composite available</p>
        )}

        {showExport ? (
          <div style={{ marginTop: 16 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "center" }}>
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="png">PNG</option>
                <option value="webp">WebP</option>
                <option value="jpg">JPG</option>
              </select>
              {format !== "png" && (
                <>
                  <label style={{ fontSize: 12, color: "var(--text-dim)" }}>
                    Quality: {quality}
                  </label>
                  <input
                    type="range"
                    min={1}
                    max={100}
                    value={quality}
                    onChange={(e) => setQuality(parseInt(e.target.value))}
                    style={{ width: 120 }}
                  />
                </>
              )}
              <button className="primary" onClick={handleExport}>
                Download
              </button>
            </div>
          </div>
        ) : null}

        <div className="actions" style={{ marginTop: 16 }}>
          <button onClick={() => setShowExport(!showExport)}>
            {showExport ? "Hide Export" : "Export"}
          </button>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
