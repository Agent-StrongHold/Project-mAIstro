import { useState } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

function SortableLayerItem({ layer, selected, onSelect, onToggle, onDelete }) {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id: layer.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`layer-item ${selected ? "selected" : ""}`}
      onClick={() => onSelect(layer.id)}
      {...attributes}
      {...listeners}
    >
      <div className="thumb">
        {layer.image_path || layer.image_url ? (
          <img
            src={layer.image_url || layer.image_path}
            alt=""
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <span>&#9634;</span>
        )}
      </div>
      <div className="info">
        <div className="name">{layer.name}</div>
        <span className="type-badge">{layer.layer_type}</span>
      </div>
      <div className="status-dot" />
      <div className="actions" onClick={(e) => e.stopPropagation()}>
        <button
          title={layer.visible !== false ? "Hide" : "Show"}
          onClick={() => onToggle(layer.id, "visible", layer.visible === false)}
        >
          {layer.visible !== false ? "\u{1F441}" : "\u2014"}
        </button>
        <button
          title={layer.locked ? "Unlock" : "Lock"}
          onClick={() => onToggle(layer.id, "locked", !layer.locked)}
        >
          {layer.locked ? "\u{1F512}" : "\u{1F513}"}
        </button>
        <button
          title="Delete"
          className="danger"
          onClick={() => {
            if (confirm(`Delete layer "${layer.name}"?`)) onDelete(layer.id);
          }}
        >
          \u00D7
        </button>
      </div>
    </div>
  );
}

export default function LayerPanel({
  canvas,
  layers,
  selectedLayerId,
  onSelectLayer,
  onDeleteLayer,
  onReorderLayers,
  onAddLayer,
  onUpdateLayerProp,
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("background");
  const sensors = useSensors(useSensor(PointerSensor));

  const sorted = [...(layers || [])].sort(
    (a, b) => (b.z_index ?? 0) - (a.z_index ?? 0)
  );

  const handleDragEnd = (event) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIdx = sorted.findIndex((l) => l.id === active.id);
    const newIdx = sorted.findIndex((l) => l.id === over.id);
    const reordered = arrayMove(sorted, oldIdx, newIdx);

    const assignments = reordered.map((l, i) => ({
      layer_id: l.id,
      z_index: reordered.length - 1 - i,
    }));
    onReorderLayers(canvas.id, assignments);
  };

  const selected = layers?.find((l) => l.id === selectedLayerId);

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div className="panel-section">
        <h3>Layers</h3>

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={sorted.map((l) => l.id)}
            strategy={verticalListSortingStrategy}
          >
            {sorted.map((ly) => (
              <SortableLayerItem
                key={ly.id}
                layer={ly}
                selected={ly.id === selectedLayerId}
                onSelect={onSelectLayer}
                onToggle={(id, prop, val) => onUpdateLayerProp(canvas.id, id, { [prop]: val })}
                onDelete={(id) => onDeleteLayer(canvas.id, id)}
              />
            ))}
          </SortableContext>
        </DndContext>

        {showAdd ? (
          <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
            <input
              placeholder="Layer name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              style={{ flex: 1 }}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && newName.trim()) {
                  onAddLayer(canvas.id, {
                    name: newName.trim(),
                    layer_type: newType,
                  });
                  setNewName("");
                  setShowAdd(false);
                }
              }}
            />
            <select value={newType} onChange={(e) => setNewType(e.target.value)}>
              <option value="background">BG</option>
              <option value="character">Char</option>
              <option value="object">Obj</option>
              <option value="text">Text</option>
            </select>
            <button onClick={() => setShowAdd(false)}>\u00D7</button>
          </div>
        ) : (
          <button
            style={{ width: "100%", marginTop: 8 }}
            onClick={() => setShowAdd(true)}
          >
            + Add Layer
          </button>
        )}
      </div>

      {selected && (
        <div className="panel-section">
          <h3>Properties</h3>
          <div className="properties">
            <div className="prop-row">
              <label>Opacity</label>
              <input
                type="range"
                min="0"
                max="100"
                value={Math.round((selected.opacity ?? 1) * 100)}
                onChange={(e) => {
                  const val = parseInt(e.target.value) / 100;
                  onUpdateLayerProp(canvas.id, selected.id, { opacity: val });
                }}
              />
              <span className="value">
                {Math.round((selected.opacity ?? 1) * 100)}%
              </span>
            </div>
            <div className="prop-row">
              <label>X</label>
              <input
                type="number"
                style={{ flex: 1 }}
                value={selected.x || 0}
                onChange={(e) =>
                  onUpdateLayerProp(canvas.id, selected.id, {
                    x: parseInt(e.target.value) || 0,
                  })
                }
              />
            </div>
            <div className="prop-row">
              <label>Y</label>
              <input
                type="number"
                style={{ flex: 1 }}
                value={selected.y || 0}
                onChange={(e) =>
                  onUpdateLayerProp(canvas.id, selected.id, {
                    y: parseInt(e.target.value) || 0,
                  })
                }
              />
            </div>
            <div className="prop-row">
              <label>Scale</label>
              <input
                type="number"
                step="0.01"
                style={{ flex: 1 }}
                value={selected.scale ?? 1}
                onChange={(e) =>
                  onUpdateLayerProp(canvas.id, selected.id, {
                    scale: parseFloat(e.target.value) || 1,
                  })
                }
              />
            </div>
            <div className="prop-row">
              <label>Rotation</label>
              <input
                type="number"
                step="1"
                style={{ flex: 1 }}
                value={selected.rotation || 0}
                onChange={(e) =>
                  onUpdateLayerProp(canvas.id, selected.id, {
                    rotation: parseFloat(e.target.value) || 0,
                  })
                }
              />
              <span className="value">&deg;</span>
            </div>
            <div className="prop-row">
              <label>Blend</label>
              <select
                style={{ flex: 1 }}
                value={selected.blend_mode || "normal"}
                onChange={(e) =>
                  onUpdateLayerProp(canvas.id, selected.id, {
                    blend_mode: e.target.value,
                  })
                }
              >
                <option value="normal">Normal</option>
                <option value="multiply">Multiply</option>
                <option value="screen">Screen</option>
                <option value="overlay">Overlay</option>
              </select>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
