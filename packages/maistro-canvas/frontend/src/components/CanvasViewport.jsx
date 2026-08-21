import { useState, useEffect, useRef, useCallback } from "react";
import { Stage, Layer, Rect, Image as KImage, Text, Transformer } from "react-konva";

const MIN_SCALE = 0.05;
const MAX_SCALE = 4.0;

const DEFAULT_TEXT_STYLE = {
  font_family: "Quicksand",
  font_size: 14,
  font_weight: "normal",
  font_style: "normal",
  color: "#333333",
  line_height: 1.4,
  letter_spacing: 0,
  text_align: "center",
};

const DEFAULT_BOX_STYLE = {
  background_color: "rgba(255,255,255,0.85)",
  border_radius: 4,
  padding: { top: 8, right: 12, bottom: 8, left: 12 },
};

function useLoadImage(src) {
  const [img, setImg] = useState(null);
  useEffect(() => {
    if (!src) return setImg(null);
    const i = new window.Image();
    i.crossOrigin = "anonymous";
    i.onload = () => setImg(i);
    i.onerror = () => setImg(null);
    i.src = src;
    return () => { i.onload = null; };
  }, [src]);
  return img;
}

function ImageNode({ layer, selected, onSelect, onDragEnd }) {
  const img = useLoadImage(layer.image_path || layer.image_url);
  const shapeRef = useRef();
  const trRef = useRef();

  useEffect(() => {
    if (selected && trRef.current && shapeRef.current && !layer.locked) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer().batchDraw();
    }
  }, [selected, layer.locked]);

  if (!img) return null;

  const w = (layer.width || img.naturalWidth || 256) * (layer.scale || 1);
  const h = (layer.height || img.naturalHeight || 256) * (layer.scale || 1);

  return (
    <>
      <KImage
        ref={shapeRef}
        image={img}
        x={layer.x || 0}
        y={layer.y || 0}
        width={w}
        height={h}
        scaleX={1}
        scaleY={1}
        rotation={layer.rotation || 0}
        opacity={layer.opacity ?? 1}
        visible={layer.visible !== false}
        draggable={!layer.locked && selected}
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={(e) => {
          onDragEnd({
            x: Math.round(e.target.x()),
            y: Math.round(e.target.y()),
          });
        }}
      />
      {selected && !layer.locked && (
        <Transformer
          ref={trRef}
          rotateEnabled
          enabledAnchors={["top-left", "top-right", "bottom-left", "bottom-right"]}
          onTransformEnd={() => {
            const node = shapeRef.current;
            onDragEnd({
              x: Math.round(node.x()),
              y: Math.round(node.y()),
              scale: parseFloat(node.scaleX().toFixed(2)),
              rotation: parseFloat(((node.rotation() % 360 + 360) % 360).toFixed(1)),
            });
          }}
          borderStroke="#00ff88"
          anchorStroke="#00ff88"
          anchorFill="#0a0a0f"
          anchorSize={8}
        />
      )}
    </>
  );
}

function TextNode({ layer, selected, onSelect, onDragEnd, onDoubleClick }) {
  const shapeRef = useRef();
  const trRef = useRef();
  const style = { ...DEFAULT_TEXT_STYLE, ...(layer.style || {}) };
  const box = { ...DEFAULT_BOX_STYLE, ...(layer.box || {}) };
  const padding = { ...DEFAULT_BOX_STYLE.padding, ...(box.padding || {}) };

  const textContent = layer.text_content || "";
  const fontSize = style.font_size || 14;
  const lineHeight = (style.line_height || 1.4) * fontSize;
  const textWidth = layer.width || 400;
  const textHeight = layer.height || Math.max(lineHeight * 3, (textContent.split("\n").length + 1) * lineHeight + padding.top + padding.bottom);

  const hasBg = box.background_color && box.background_color !== "transparent";

  useEffect(() => {
    if (selected && trRef.current && shapeRef.current && !layer.locked) {
      trRef.current.nodes([shapeRef.current]);
      trRef.current.getLayer().batchDraw();
    }
  }, [selected, layer.locked]);

  const konvaFontStyle = [];
  if (style.font_weight === "bold") konvaFontStyle.push("bold");
  if (style.font_style === "italic") konvaFontStyle.push("italic");

  return (
    <>
      {hasBg && (
        <Rect
          x={(layer.x || 0) - padding.left}
          y={(layer.y || 0) - padding.top}
          width={textWidth + padding.left + padding.right}
          height={textHeight + padding.top + padding.bottom}
          fill={box.background_color}
          cornerRadius={box.border_radius || 0}
          opacity={layer.opacity ?? 1}
          visible={layer.visible !== false}
          listening={false}
        />
      )}
      <Text
        ref={shapeRef}
        text={textContent}
        x={layer.x || 0}
        y={layer.y || 0}
        width={textWidth}
        fontSize={fontSize}
        fontFamily={style.font_family}
        fontStyle={konvaFontStyle.join(" ") || "normal"}
        fill={style.color}
        lineHeight={style.line_height || 1.4}
        letterSpacing={style.letter_spacing || 0}
        align={style.text_align || "left"}
        verticalAlign="bottom"
        rotation={layer.rotation || 0}
        opacity={layer.opacity ?? 1}
        visible={layer.visible !== false}
        draggable={!layer.locked && selected}
        onClick={onSelect}
        onTap={onSelect}
        onDblClick={onDoubleClick}
        onDblTap={onDoubleClick}
        onDragEnd={(e) => {
          onDragEnd({
            x: Math.round(e.target.x()),
            y: Math.round(e.target.y()),
          });
        }}
      />
      {selected && !layer.locked && (
        <Transformer
          ref={trRef}
          rotateEnabled
          enabledAnchors={["top-left", "top-right", "bottom-left", "bottom-right"]}
          onTransformEnd={() => {
            const node = shapeRef.current;
            onDragEnd({
              x: Math.round(node.x()),
              y: Math.round(node.y()),
              width: Math.round(node.width() * node.scaleX()),
              height: Math.round(node.height() * node.scaleY()),
              rotation: parseFloat(((node.rotation() % 360 + 360) % 360).toFixed(1)),
            });
          }}
          borderStroke="#00ff88"
          anchorStroke="#00ff88"
          anchorFill="#0a0a0f"
          anchorSize={8}
        />
      )}
    </>
  );
}

function TextEditor({ layer, onSave, onCancel }) {
  const [text, setText] = useState(layer.text_content || "");
  const inputRef = useRef(null);

  useEffect(() => {
    if (inputRef.current) inputRef.current.focus();
  }, []);

  return (
    <textarea
      ref={inputRef}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => onSave(text)}
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel();
        if (e.key === "Enter" && e.ctrlKey) onSave(text);
      }}
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: "100%",
        height: "100%",
        background: "rgba(0,0,0,0.8)",
        color: "var(--text)",
        fontSize: 14,
        fontFamily: layer.style?.font_family || "Quicksand",
        padding: 16,
        border: "2px solid var(--phosphor)",
        borderRadius: 6,
        zIndex: 50,
        resize: "none",
        outline: "none",
      }}
    />
  );
}

export default function CanvasViewport({
  canvas,
  layers,
  selectedLayerId,
  onSelectLayer,
  onUpdateLayer,
}) {
  const containerRef = useRef();
  const [stageSize, setStageSize] = useState({ width: 800, height: 600 });
  const [scale, setScale] = useState(1);
  const [editingLayerId, setEditingLayerId] = useState(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setStageSize({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!canvas) return;
    const sx = (stageSize.width - 40) / canvas.width;
    const sy = (stageSize.height - 40) / canvas.height;
    setScale(Math.min(sx, sy, 1));
  }, [canvas, stageSize]);

  const handleWheel = useCallback((e) => {
    e.evt.preventDefault();
    const factor = e.evt.deltaY < 0 ? 1.1 : 0.9;
    setScale((s) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s * factor)));
  }, []);

  const editingLayer = editingLayerId ? (layers || []).find((l) => l.id === editingLayerId) : null;

  if (!canvas) {
    return (
      <div ref={containerRef} className="viewport-area checkerboard">
        <div className="empty-state">
          <div className="icon">&#9670;</div>
          <h2>No canvas loaded</h2>
          <p>Create or select a canvas to begin</p>
        </div>
      </div>
    );
  }

  const sorted = [...(layers || [])].sort((a, b) => (a.z_index ?? 0) - (b.z_index ?? 0));
  const offsetX = (stageSize.width - canvas.width * scale) / 2;
  const offsetY = (stageSize.height - canvas.height * scale) / 2;

  return (
    <div ref={containerRef} className="viewport-area checkerboard" style={{ position: "relative" }}>
      <Stage
        width={stageSize.width}
        height={stageSize.height}
        onWheel={handleWheel}
        onClick={(e) => {
          if (e.target === e.target.getStage()) onSelectLayer(null);
        }}
        scaleX={scale}
        scaleY={scale}
        x={offsetX}
        y={offsetY}
      >
        <Layer>
          <Rect
            x={0}
            y={0}
            width={canvas.width}
            height={canvas.height}
            fill={canvas.background_color || "#FFFFFF"}
          />
          {sorted.map((ly) =>
            ly.type === "text" ? (
              <TextNode
                key={ly.id}
                layer={ly}
                selected={ly.id === selectedLayerId}
                onSelect={() => onSelectLayer(ly.id)}
                onDragEnd={(changes) => onUpdateLayer(canvas.id, ly.id, changes)}
                onDoubleClick={() => setEditingLayerId(ly.id)}
              />
            ) : (
              <ImageNode
                key={ly.id}
                layer={ly}
                selected={ly.id === selectedLayerId}
                onSelect={() => onSelectLayer(ly.id)}
                onDragEnd={(changes) => onUpdateLayer(canvas.id, ly.id, changes)}
              />
            )
          )}
        </Layer>
      </Stage>
      {editingLayer && (
        <TextEditor
          layer={editingLayer}
          canvasEl={containerRef.current}
          onSave={(text) => {
            onUpdateLayer(canvas.id, editingLayer.id, { text_content: text });
            setEditingLayerId(null);
          }}
          onCancel={() => setEditingLayerId(null)}
        />
      )}
      <div
        style={{
          position: "absolute",
          bottom: 8,
          right: 8,
          background: "var(--ink-2)",
          padding: "4px 8px",
          borderRadius: 4,
          fontSize: 11,
          fontFamily: "var(--font)",
          color: "var(--text-dim)",
        }}
      >
        {Math.round(scale * 100)}%
      </div>
    </div>
  );
}
