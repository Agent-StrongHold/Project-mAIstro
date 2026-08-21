import { useState, useRef, useCallback, useEffect } from "react";

const HANDLE_SIZE = 8;
const MIN_SIZE = 30;

export default function LayerCanvas({ page, pageDims, selectedLayer, onSelectLayer, onLayerTransform }) {
  const containerRef = useRef(null);
  const [scale, setScale] = useState(1);
  const [drag, setDrag] = useState(null);
  const [resize, setResize] = useState(null);

  const { w = 1536, h = 1024 } = pageDims || {};

  useEffect(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setScale(Math.min(rect.width / w, rect.height / h, 1));
  }, [w, h, page]);

  const layers = page?.layers || [];

  const getTransform = (layer) => {
    const x = (layer.x ?? layer.slot?.x ?? 0) * w;
    const y = (layer.y ?? layer.slot?.y ?? 0) * h;
    let lw, lh;
    if (layer.slot === "full_page") {
      lw = w; lh = h;
    } else if (typeof layer.slot === "object" && layer.slot) {
      lw = layer.slot.w * w;
      lh = layer.slot.h * h;
    } else {
      lw = (layer.lw ?? 0.4) * w;
      lh = (layer.lh ?? 0.6) * h;
    }
    const s = layer.scale ?? 1;
    return { x, y, w: lw * s, h: lh * s };
  };

  const handleMouseDown = (e, li, type, handlePos) => {
    e.preventDefault();
    e.stopPropagation();
    onSelectLayer(li);
    const layer = layers[li];
    const t = getTransform(layer);
    const startX = e.clientX;
    const startY = e.clientY;

    if (type === "move") {
      setDrag({ li, startX, startY, origX: t.x, origY: t.y });
    } else if (type === "resize") {
      setResize({ li, startX, startY, origX: t.x, origY: t.y, origW: t.w, origH: t.h, handle: handlePos });
    }
  };

  const handleMouseMove = useCallback((e) => {
    if (drag) {
      const dx = (e.clientX - drag.startX) / scale;
      const dy = (e.clientY - drag.startY) / scale;
      onLayerTransform(drag.li, { x: drag.origX + dx, y: drag.origY + dy }, true);
    }
    if (resize) {
      const dx = (e.clientX - resize.startX) / scale;
      const dy = (e.clientY - resize.startY) / scale;
      const aspect = resize.origW / resize.origH || 1;
      let newW = resize.origW;
      let newH = resize.origH;
      let newX = resize.origX;
      let newY = resize.origY;
      const h = resize.handle;

      if (h.includes("e")) newW = Math.max(MIN_SIZE, resize.origW + dx);
      if (h.includes("w")) { newW = Math.max(MIN_SIZE, resize.origW - dx); newX = resize.origX + (resize.origW - newW); }
      if (h.includes("s")) newH = Math.max(MIN_SIZE, resize.origH + dy);
      if (h.includes("n")) { newH = Math.max(MIN_SIZE, resize.origH - dy); newY = resize.origY + (resize.origH - newH); }

      if (h === "e" || h === "w") newH = newW / aspect;
      if (h === "n" || h === "s") newW = newH * aspect;

      onLayerTransform(resize.li, { x: newX, y: newY, w: newW, h: newH }, true);
    }
  }, [drag, resize, scale, onLayerTransform]);

  const handleMouseUp = useCallback(() => {
    if (drag) {
      const layer = layers[drag.li];
      const t = getTransform(layer);
      onLayerTransform(drag.li, { x: t.x, y: t.y, w: t.w, h: t.h }, false);
      setDrag(null);
    }
    if (resize) {
      const layer = layers[resize.li];
      const t = getTransform(layer);
      onLayerTransform(resize.li, { x: t.x, y: t.y, w: t.w, h: t.h }, false);
      setResize(null);
    }
  }, [drag, resize, layers, onLayerTransform]);

  useEffect(() => {
    if (!drag && !resize) return;
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [drag, resize, handleMouseMove, handleMouseUp]);

  const handles = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", position: "relative", overflow: "hidden" }}>
      <div style={{ width: w * scale, height: h * scale, position: "relative", background: "#1a1a1a", borderRadius: 4, overflow: "hidden", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}>
        {layers.map((layer, li) => {
          if (layer.type === "text") return null;
          if (!layer.image_url) return null;

          const t = getTransform(layer);
          const isSelected = li === selectedLayer;
          const isDragging = (drag?.li === li) || (resize?.li === li);

          return (
            <div key={layer.id} style={{ position: "absolute", left: t.x * scale, top: t.y * scale, width: t.w * scale, height: t.h * scale, cursor: isDragging ? "grabbing" : "grab", zIndex: 1000 + (layer.z_index || 0) }}
              onMouseDown={(e) => handleMouseDown(e, li, "move")}
            >
              <img src={layer.image_url} alt={layer.name} draggable={false} style={{ width: "100%", height: "100%", objectFit: "cover", pointerEvents: "none", userSelect: "none" }} />
              {isSelected && (
                <>
                  <div style={{ position: "absolute", inset: 0, border: "2px solid var(--phosphor)", pointerEvents: "none", zIndex: 10 }} />
                  <div style={{ position: "absolute", top: -16, left: 0, fontSize: 9, padding: "1px 4px", background: "var(--phosphor)", color: "var(--ink-0)", borderRadius: 2, whiteSpace: "nowrap", zIndex: 20 }}>{layer.name}</div>
                  {handles.map((h) => (
                    <div key={h} onMouseDown={(e) => handleMouseDown(e, li, "resize", h)}
                      style={{
                        position: "absolute", width: HANDLE_SIZE, height: HANDLE_SIZE, background: "var(--phosphor)", border: "1px solid var(--ink-0)", zIndex: 20,
                        cursor: `${h}-resize`,
                        ...{
                          nw: { top: -HANDLE_SIZE / 2, left: -HANDLE_SIZE / 2 },
                          n:  { top: -HANDLE_SIZE / 2, left: "50%", marginLeft: -HANDLE_SIZE / 2 },
                          ne: { top: -HANDLE_SIZE / 2, right: -HANDLE_SIZE / 2 },
                          e:  { top: "50%", right: -HANDLE_SIZE / 2, marginTop: -HANDLE_SIZE / 2 },
                          se: { bottom: -HANDLE_SIZE / 2, right: -HANDLE_SIZE / 2 },
                          s:  { bottom: -HANDLE_SIZE / 2, left: "50%", marginLeft: -HANDLE_SIZE / 2 },
                          sw: { bottom: -HANDLE_SIZE / 2, left: -HANDLE_SIZE / 2 },
                          w:  { top: "50%", left: -HANDLE_SIZE / 2, marginTop: -HANDLE_SIZE / 2 },
                        }[h],
                      }}
                    />
                  ))}
                </>
              )}
            </div>
          );
        })}
        {page?.composite && (
          <img src={page.composite} alt="" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "fill", pointerEvents: "none", opacity: 0.15, zIndex: 0 }} />
        )}
      </div>
    </div>
  );
}
