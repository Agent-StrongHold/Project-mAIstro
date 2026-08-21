const API = "/api";

function safeKey(name) {
  return (name || "untitled").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
}

export async function saveTemplate(template) {
  const key = safeKey(template.name);
  try {
    await fetch(`${API}/templates/${encodeURIComponent(key)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(template),
    });
  } catch (e) { console.warn("Save template failed:", e); }
}

export async function listTemplates() {
  try {
    const res = await fetch(`${API}/templates`);
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch (e) { console.warn("List templates failed:", e); return []; }
}

export async function deleteTemplate(key) {
  try {
    await fetch(`${API}/templates/${encodeURIComponent(key)}`, { method: "DELETE" });
  } catch (e) { console.warn("Delete template failed:", e); }
}
