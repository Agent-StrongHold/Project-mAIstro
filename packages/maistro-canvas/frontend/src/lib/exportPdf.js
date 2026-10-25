export async function exportBookPdf({ title, pages, productId, mode }) {
  const res = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: mode || "interior",
      title: title || "My Book",
      author: "Main Character Press",
      product_id: productId || "landscape_10x8",
      pages: pages.map((p) => ({
        composite: p.composite || null,
        layers: (p.layers || []).map((l) => ({
          id: l.id,
          name: l.name,
          type: l.type,
          image_url: l.image_url || null,
          text_content: l.text_content || null,
          style: l.style || null,
          x: l.x,
          y: l.y,
          width: l.width,
          height: l.height,
        })),
      })),
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Export failed (${res.status})`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(title || "book").replace(/[^a-zA-Z0-9_-]/g, "_")}_${mode || "interior"}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
