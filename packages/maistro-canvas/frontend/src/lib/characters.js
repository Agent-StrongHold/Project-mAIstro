const API = "/api";

function safeKey(name) {
  return (name || "untitled").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
}

export async function listCharacters() {
  try {
    const res = await fetch(`${API}/characters`);
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("List characters failed:", e);
    return [];
  }
}

export async function getCharacter(name) {
  const key = safeKey(name);
  try {
    const res = await fetch(`${API}/characters/${encodeURIComponent(key)}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Load ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("Get character failed:", e);
    return null;
  }
}

export async function saveCharacter(character) {
  const key = safeKey(character.name);
  try {
    await fetch(`${API}/characters/${encodeURIComponent(key)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(character),
    });
  } catch (e) {
    console.warn("Save character failed:", e);
  }
}

export async function deleteCharacter(key) {
  try {
    await fetch(`${API}/characters/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
  } catch (e) {
    console.warn("Delete character failed:", e);
  }
}
