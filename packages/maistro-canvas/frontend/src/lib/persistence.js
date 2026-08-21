const API = "/api";

function safeKey(bookTitle) {
  return (bookTitle || "untitled").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
}

export async function saveState(bookTitle, state) {
  const key = safeKey(bookTitle);
  try {
    await fetch(`${API}/books/${encodeURIComponent(key)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state),
    });
  } catch (e) {
    console.warn("Save failed:", e);
  }
}

export async function loadState(bookTitle) {
  const key = safeKey(bookTitle);
  try {
    const res = await fetch(`${API}/books/${encodeURIComponent(key)}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Load ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("Load failed:", e);
    return null;
  }
}

export async function listSaved() {
  try {
    const res = await fetch(`${API}/books`);
    if (!res.ok) throw new Error(`List ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("List failed:", e);
    return [];
  }
}

export async function clearState(bookTitle) {
  const key = safeKey(bookTitle);
  try {
    await fetch(`${API}/books/${encodeURIComponent(key)}`, { method: "DELETE" });
  } catch (e) {
    console.warn("Delete failed:", e);
  }
}

export async function clearAll() {
  try {
    await fetch(`${API}/books`, { method: "DELETE" });
  } catch (e) {
    console.warn("Clear all failed:", e);
  }
}
