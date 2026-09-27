import { useEffect, useRef, useState } from "react";
import { randomId } from "../lib/ids";

type FixedPageEditorProps = {
  artifactName: string;
  initialPrompt: string;
  onExit: () => void;
  onSave?: () => Promise<void>;
};

type Layer = {
  id: string;
  name: string;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  background: string;
};

const PAGE_WIDTH = 960;
const PAGE_HEIGHT = 540;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function makeId(): string {
  // `randomId`, not `crypto.randomUUID`: the e2e harness (and documented
  // homelab deploys) serve the app over plain HTTP from a LAN hostname, where
  // randomUUID is undefined and the editor would die in the error boundary on
  // first render (#1344 records the identical DeckBuilder failure).
  return `layer-${randomId().slice(0, 8)}`;
}

export default function FixedPageEditor({ artifactName, initialPrompt, onExit, onSave }: FixedPageEditorProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [layers, setLayers] = useState<Layer[]>([
    {
      id: makeId(),
      name: "Title",
      text: initialPrompt.split(/[.!?]/)[0] || `${artifactName} draft`,
      x: 80,
      y: 70,
      width: 800,
      height: 90,
      color: "#172033",
      background: "#ffffff",
    },
    {
      id: makeId(),
      name: "Description",
      text: initialPrompt || "Add a concise description for this visual.",
      x: 80,
      y: 190,
      width: 620,
      height: 120,
      color: "#334155",
      background: "#ffffff",
    },
  ]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState("Draft editor ready. No remote generation has been requested.");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const selected = layers.find((layer) => layer.id === selectedId) ?? layers[0];
  const selectedIndex = selected ? layers.findIndex((layer) => layer.id === selected.id) : -1;

  function updateSelected(patch: Partial<Layer>): void {
    if (!selected) return;
    setLayers((current) => current.map((layer) => (layer.id === selected.id ? { ...layer, ...patch } : layer)));
  }

  function nudge(dx: number, dy: number): void {
    if (!selected) return;
    updateSelected({ x: Math.max(0, Math.min(PAGE_WIDTH - selected.width, selected.x + dx)), y: Math.max(0, Math.min(PAGE_HEIGHT - selected.height, selected.y + dy)) });
    const direction = dx > 0 ? "right" : dx < 0 ? "left" : dy > 0 ? "down" : "up";
    setStatus(`${selected.name} moved ${direction}.`);
  }

  function moveLayer(direction: -1 | 1): void {
    if (selectedIndex < 0) return;
    const target = selectedIndex + direction;
    if (target < 0 || target >= layers.length) return;
    setLayers((current) => {
      const next = [...current];
      [next[selectedIndex], next[target]] = [next[target], next[selectedIndex]];
      return next;
    });
    setStatus(`${selected?.name} moved ${direction < 0 ? "earlier" : "later"} in the layer order.`);
  }

  function addLayer(): void {
    const layer: Layer = {
      id: makeId(),
      name: `Layer ${layers.length + 1}`,
      text: "New text layer",
      x: 120,
      y: 350,
      width: 500,
      height: 70,
      color: "#334155",
      background: "#ffffff",
    };
    setLayers((current) => [...current, layer]);
    setSelectedId(layer.id);
    setStatus(`${layer.name} added and selected.`);
  }

  function deleteSelected(): void {
    if (!selected || layers.length === 1) return;
    const next = layers.filter((layer) => layer.id !== selected.id);
    setLayers(next);
    setSelectedId(next[Math.max(0, selectedIndex - 1)]?.id ?? null);
    setStatus(`${selected.name} deleted.`);
  }

  async function saveDraft(): Promise<void> {
    if (!onSave || saving) return;
    setSaving(true);
    setStatus("Saving project through the Design service...");
    try {
      await onSave();
      setStatus("Project saved. This editor remains available for local changes.");
    } catch (error) {
      setStatus(error instanceof Error ? `Project save failed: ${error.message}` : "Project save failed.");
    } finally {
      setSaving(false);
    }
  }

  function exportHtml(): void {
    const markup = layers
      .map(
        (layer) =>
          `<div style="position:absolute;left:${layer.x}px;top:${layer.y}px;width:${layer.width}px;height:${layer.height}px;color:${layer.color};background:${layer.background};padding:16px;box-sizing:border-box">${escapeHtml(layer.text)}</div>`,
      )
      .join("\n");
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(artifactName)}</title></head><body style="margin:0"><main style="position:relative;width:${PAGE_WIDTH}px;height:${PAGE_HEIGHT}px">${markup}</main></body></html>`;
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${artifactName.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "design"}.html`;
    link.click();
    URL.revokeObjectURL(url);
    setStatus("Draft exported as HTML.");
  }

  return (
    <div aria-labelledby="fixed-editor-title" style={{ color: "var(--ink)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
        <div>
          <h1 id="fixed-editor-title" ref={headingRef} tabIndex={-1} style={{ margin: 0, fontFamily: "var(--hand)", fontSize: 24 }}>
            {artifactName} editor
          </h1>
          <p style={{ margin: "4px 0 0", color: "var(--pencil)", fontSize: 12 }}>
            Fixed-page draft. Select a layer, then use the property controls or nudge commands; dragging is never required.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={onExit}>Back to Design Studio</button>
          {onSave && <button type="button" onClick={() => void saveDraft()} disabled={saving}>{saving ? "Saving..." : "Save project"}</button>}
          <button type="button" className="btn-primary" onClick={exportHtml}>Export HTML</button>
        </div>
      </div>

      <p role="status" aria-live="polite" style={{ minHeight: 18, color: "var(--pencil)", fontSize: 12 }}>{status}</p>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(150px, 220px) minmax(0, 1fr) minmax(190px, 260px)", gap: 16, alignItems: "start" }}>
        <section className="card" aria-labelledby="fixed-layers-title">
          <h2 id="fixed-layers-title" style={{ margin: "0 0 10px", fontSize: 14 }}>Layers</h2>
          <div role="listbox" aria-label="Canvas layers" aria-describedby="layer-help" style={{ display: "grid", gap: 6 }}>
            {layers.map((layer, index) => (
              <button
                key={layer.id}
                type="button"
                role="option"
                aria-selected={layer.id === selected?.id}
                onClick={() => { setSelectedId(layer.id); setStatus(`${layer.name} selected.`); }}
                style={{ textAlign: "left", padding: "8px 10px", borderColor: layer.id === selected?.id ? "var(--accent)" : "var(--rule)" }}
              >
                {index + 1}. {layer.name}
              </button>
            ))}
          </div>
          <p id="layer-help" style={{ color: "var(--pencil)", fontSize: 11, lineHeight: 1.4 }}>
            Tab to a layer and press Enter. Use Move earlier/later to reorder without dragging.
          </p>
          <button type="button" onClick={addLayer}>Add layer</button>
        </section>

        <section aria-labelledby="fixed-canvas-title">
          <h2 id="fixed-canvas-title" style={{ fontSize: 14 }}>Canvas preview</h2>
          <div
            role="region"
            aria-label={`${artifactName} canvas`}
            style={{ position: "relative", width: "100%", aspectRatio: `${PAGE_WIDTH} / ${PAGE_HEIGHT}`, background: "#f8fafc", border: "1px solid var(--rule)", overflow: "hidden" }}
          >
            {layers.map((layer) => (
              <button
                key={layer.id}
                type="button"
                aria-label={`Select ${layer.name} layer`}
                aria-pressed={layer.id === selected?.id}
                onClick={() => setSelectedId(layer.id)}
                style={{ position: "absolute", left: `${(layer.x / PAGE_WIDTH) * 100}%`, top: `${(layer.y / PAGE_HEIGHT) * 100}%`, width: `${(layer.width / PAGE_WIDTH) * 100}%`, height: `${(layer.height / PAGE_HEIGHT) * 100}%`, color: layer.color, background: layer.background, border: layer.id === selected?.id ? "2px solid var(--accent)" : "1px solid #cbd5e1", textAlign: "left", overflow: "hidden", padding: 16 }}
              >
                {layer.text}
              </button>
            ))}
          </div>
          <p style={{ color: "var(--pencil)", fontSize: 11 }}>Keyboard equivalent: select a layer, then adjust X/Y, width, or height. Arrow commands move it by 8 px.</p>
        </section>

        <section className="card" aria-labelledby="fixed-properties-title">
          <h2 id="fixed-properties-title" style={{ margin: "0 0 10px", fontSize: 14 }}>Layer properties</h2>
          {selected ? (
            <div style={{ display: "grid", gap: 9 }}>
              <label>Layer name<input value={selected.name} onChange={(event) => updateSelected({ name: event.target.value })} /></label>
              <label>Text<textarea rows={3} value={selected.text} onChange={(event) => updateSelected({ text: event.target.value })} /></label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <label>X<input type="number" min={0} max={PAGE_WIDTH} value={selected.x} onChange={(event) => updateSelected({ x: Number(event.target.value) })} /></label>
                <label>Y<input type="number" min={0} max={PAGE_HEIGHT} value={selected.y} onChange={(event) => updateSelected({ y: Number(event.target.value) })} /></label>
                <label>Width<input type="number" min={40} max={PAGE_WIDTH} value={selected.width} onChange={(event) => updateSelected({ width: Number(event.target.value) })} /></label>
                <label>Height<input type="number" min={30} max={PAGE_HEIGHT} value={selected.height} onChange={(event) => updateSelected({ height: Number(event.target.value) })} /></label>
              </div>
              <label>Text color<input type="color" value={selected.color} onChange={(event) => updateSelected({ color: event.target.value })} /></label>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button type="button" onClick={() => nudge(0, -8)}>Move up</button>
                <button type="button" onClick={() => nudge(0, 8)}>Move down</button>
                <button type="button" onClick={() => nudge(-8, 0)}>Move left</button>
                <button type="button" onClick={() => nudge(8, 0)}>Move right</button>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button type="button" onClick={() => moveLayer(-1)} disabled={selectedIndex <= 0}>Move earlier</button>
                <button type="button" onClick={() => moveLayer(1)} disabled={selectedIndex < 0 || selectedIndex === layers.length - 1}>Move later</button>
                <button type="button" onClick={deleteSelected} disabled={layers.length === 1}>Delete</button>
              </div>
            </div>
          ) : <p>Select a layer to edit its properties.</p>}
        </section>
      </div>
    </div>
  );
}
