let _canvases = [];
let _layers = {};
let _idCounter = 1;
let _layerIdCounter = 1;
let _jobIdCounter = 1;

function uid() {
  return "c" + _idCounter++;
}

function layerUid() {
  return "l" + _layerIdCounter++;
}

function jobUid() {
  return "j" + _jobIdCounter++;
}

function delay(ms = 80) {
  return new Promise((r) => setTimeout(r, ms));
}

function makeFakeImage(w, h) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");

  const hue = Math.floor(Math.random() * 360);
  ctx.fillStyle = `hsl(${hue}, 60%, 30%)`;
  ctx.fillRect(0, 0, w, h);

  for (let i = 0; i < 6; i++) {
    ctx.fillStyle = `hsla(${(hue + i * 40) % 360}, 70%, 50%, 0.5)`;
    const x = Math.random() * w;
    const y = Math.random() * h;
    const r = 30 + Math.random() * 80;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  return canvas.toDataURL("image/png");
}

const mock = {
  async listCanvases() {
    await delay();
    return _canvases.filter((c) => !c.archived_at);
  },

  async getCanvas(id) {
    await delay();
    const c = _canvases.find((c) => c.id === id);
    if (!c) throw new Error("Canvas not found");
    return { ...c, layers: (_layers[id] || []).map((l) => ({ ...l })) };
  },

  async createCanvas(body) {
    await delay();
    let width = body.width || 1024;
    let height = body.height || 1024;
    if (body.aspect_ratio) {
      const ratios = {
        "1:1": [1024, 1024],
        "16:9": [1824, 1024],
        "9:16": [1024, 1824],
        "3:2": [1536, 1024],
        "2:3": [1024, 1536],
        "4:3": [1360, 1024],
        "3:4": [1024, 1360],
      };
      [width, height] = ratios[body.aspect_ratio] || [1024, 1024];
    }
    const canvas = {
      id: uid(),
      name: body.name || "Untitled",
      width,
      height,
      background_color: body.background_color || "#FFFFFF",
      org_id: "demo",
      layer_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      archived_at: null,
    };
    _canvases.push(canvas);
    _layers[canvas.id] = [];
    return { ...canvas };
  },

  async updateCanvas(id, body) {
    await delay();
    const c = _canvases.find((c) => c.id === id);
    if (!c) throw new Error("not found");
    Object.assign(c, body, { updated_at: new Date().toISOString() });
    return { ...c };
  },

  async deleteCanvas(id) {
    await delay();
    const c = _canvases.find((c) => c.id === id);
    if (c) c.archived_at = new Date().toISOString();
  },

  async listLayers(canvasId) {
    await delay();
    return (_layers[canvasId] || []).map((l) => ({ ...l }));
  },

  async addLayer(canvasId, body) {
    await delay();
    const existing = _layers[canvasId] || [];
    const z =
      body.z_index != null
        ? body.z_index
        : existing.length > 0
          ? Math.max(...existing.map((l) => l.z_index)) + 1
          : 0;
    const layer = {
      id: layerUid(),
      canvas_id: canvasId,
      name: body.name || "Layer",
      layer_type: body.layer_type || "background",
      z_index: z,
      x: body.x || 0,
      y: body.y || 0,
      scale: body.scale ?? 1,
      rotation: body.rotation || 0,
      opacity: body.opacity ?? 1,
      blend_mode: body.blend_mode || "normal",
      visible: body.visible !== false,
      locked: !!body.locked,
      image_path: null,
      image_url: null,
      width: null,
      height: null,
      prompt: body.prompt || null,
      negative_prompt: body.negative_prompt || null,
      model_id: null,
      tier: body.tier || "draft",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    existing.push(layer);
    _layers[canvasId] = existing;
    const c = _canvases.find((c) => c.id === canvasId);
    if (c) c.layer_count = existing.length;
    return { ...layer };
  },

  async updateLayer(canvasId, layerId, body) {
    await delay();
    const list = _layers[canvasId] || [];
    const layer = list.find((l) => l.id === layerId);
    if (!layer) throw new Error("Layer not found");
    Object.assign(layer, body, { updated_at: new Date().toISOString() });
    return { ...layer };
  },

  async deleteLayer(canvasId, layerId) {
    await delay();
    _layers[canvasId] = (_layers[canvasId] || []).filter(
      (l) => l.id !== layerId
    );
    const c = _canvases.find((c) => c.id === canvasId);
    if (c) c.layer_count = _layers[canvasId].length;
  },

  async reorderLayers(canvasId, assignments) {
    await delay();
    const list = _layers[canvasId] || [];
    for (const a of assignments) {
      const layer = list.find((l) => l.id === a.layer_id);
      if (layer) layer.z_index = a.z_index;
    }
    return list.map((l) => ({ ...l }));
  },

  async startGenerate(canvasId, layerId, body) {
    await delay();
    const list = _layers[canvasId] || [];
    const layer = list.find((l) => l.id === layerId);
    if (!layer) throw new Error("Layer not found");

    const jobId = jobUid();

    setTimeout(() => {
      const img = makeFakeImage(
        256 + Math.floor(Math.random() * 256),
        256 + Math.floor(Math.random() * 256)
      );
      layer.image_url = img;
      layer.image_path = img;
      layer.width = 512;
      layer.height = 512;
      layer.prompt = body.prompt;
      layer.updated_at = new Date().toISOString();
    }, 1500 + Math.random() * 1500);

    return { job_id: jobId, status: "pending" };
  },

  async getJob(jobId) {
    await delay(50);
    return { id: jobId, status: "done", result_paths: [] };
  },

  async cancelJob() {
    await delay();
  },

  async acceptVariant() {
    await delay();
  },

  async composite(canvasId) {
    await delay(300);
    const c = _canvases.find((c) => c.id === canvasId);
    if (!c) throw new Error("not found");
    const img = makeFakeImage(c.width, c.height);
    return { image_b64: img.replace(/^data:image\/png;base64,/, "") };
  },

  async getLatestComposite(canvasId) {
    await delay();
    const c = _canvases.find((c) => c.id === canvasId);
    if (!c) throw new Error("not found");
    const img = makeFakeImage(c.width, c.height);
    return { image_b64: img.replace(/^data:image\/png;base64,/, "") };
  },

  exportUrl(canvasId, format = "png", quality = 90) {
    return `/api/canvas/${canvasId}/export?format=${format}&quality=${quality}`;
  },

  async listModels() {
    await delay();
    return [
      {
        id: "dall-e-3",
        display_name: "DALL-E 3",
        provider: "openai",
        tier_class: "proof",
        cost_per_image_usd: 0.04,
        is_free: false,
      },
      {
        id: "gemini-flash",
        display_name: "Gemini Flash",
        provider: "google",
        tier_class: "draft",
        cost_per_image_usd: 0,
        is_free: true,
      },
    ];
  },
};

export default mock;
