const API = "/api";

export async function logGenerationAttempt({ bookKey, sceneId, layerId, attemptType, prompt, modelId, quality, verdict, data }) {
  try {
    const res = await fetch(`${API}/generation-attempts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book_key: bookKey,
        scene_id: sceneId,
        layer_id: layerId,
        attempt_type: attemptType,
        prompt: prompt || "",
        model_id: modelId || null,
        quality: quality || "draft",
        verdict: verdict || "pending",
        data: data || {},
      }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    console.warn("Log generation failed:", e);
    return null;
  }
}

export async function updateVerdict(attemptId, verdict) {
  try {
    await fetch(`${API}/generation-attempts/${attemptId}/verdict`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict }),
    });
  } catch (e) {
    console.warn("Update verdict failed:", e);
  }
}

export async function saveLayoutVersion({ bookKey, sceneId, layout, diff }) {
  try {
    const res = await fetch(`${API}/layout-versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book_key: bookKey,
        scene_id: sceneId,
        layout,
        diff,
      }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    console.warn("Save layout version failed:", e);
    return null;
  }
}
