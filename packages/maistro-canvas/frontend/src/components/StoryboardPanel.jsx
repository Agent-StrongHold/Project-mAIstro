import { generateScene } from "../lib/storyApi";

export default function StoryboardPanel({
  story,
  currentSceneIdx,
  onSelectScene,
  onSceneGenerated,
}) {
  if (!story) return null;
  const contract = story.style_contract;

  const handleGenerate = async (scene) => {
    await generateScene(story.id, scene.id, () => {});
    onSceneGenerated();
  };

  return (
    <div className="panel-section" style={{ flex: 1, overflow: "auto" }}>
      <h3>Storyboard</h3>
      <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 8 }}>
        {story.title}
      </div>

      <div
        style={{
          background: "var(--ink-2)",
          borderRadius: 6,
          padding: 8,
          marginBottom: 12,
          fontSize: 11,
        }}
      >
        <div style={{ color: "var(--phosphor)", fontFamily: "var(--font)", marginBottom: 4 }}>
          STYLE CONTRACT
        </div>
        <div style={{ color: "var(--text-dim)" }}>
          <div><b>Style:</b> {contract.art_style}</div>
          <div><b>Lighting:</b> {contract.lighting}</div>
          <div><b>Mood:</b> {contract.mood}</div>
          <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
            {(contract.color_palette || []).map((c, i) => (
              <div
                key={i}
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: 3,
                  background: c,
                  border: "1px solid var(--border)",
                }}
              />
            ))}
          </div>
        </div>
      </div>

      {story.scenes.map((scene, idx) => (
        <div
          key={scene.id}
          className={`layer-item ${idx === currentSceneIdx ? "selected" : ""}`}
          onClick={() => onSelectScene(idx)}
          style={{ marginBottom: 4 }}
        >
          <div
            className="thumb"
            style={{
              background: scene.status === "done"
                ? undefined
                : scene.status === "generating"
                  ? "var(--amber)"
                  : "var(--ink-3)",
            }}
          >
            {scene.thumbnail ? (
              <img
                src={scene.thumbnail}
                alt=""
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            ) : (
              <span>{scene.id}</span>
            )}
          </div>
          <div className="info">
            <div className="name">
              {scene.id}. {scene.title}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 2 }}>
              {scene.layers?.length || 0} layers
              {scene.status === "done" && " - ready"}
              {scene.status === "generating" && " - generating..."}
            </div>
          </div>
          {scene.status === "planned" && (
            <button
              className="primary"
              style={{ fontSize: 10, padding: "3px 8px" }}
              onClick={(e) => {
                e.stopPropagation();
                handleGenerate(scene);
              }}
            >
              Gen
            </button>
          )}
          {scene.status === "generating" && (
            <div className="status-dot generating" />
          )}
          {scene.status === "done" && <div className="status-dot ready" />}
        </div>
      ))}
    </div>
  );
}
