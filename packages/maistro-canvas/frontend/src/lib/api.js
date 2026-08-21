import { chat, generateImage } from "./llmClient";

// Keys are server-side only (see server.js /api/llm/*). Nothing here holds them.

function makePlaceholderImage(prompt) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext("2d");
  const hue = [prompt].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  const grad = ctx.createLinearGradient(0, 0, 512, 512);
  grad.addColorStop(0, `hsl(${hue}, 60%, 25%)`);
  grad.addColorStop(1, `hsl(${(hue + 60) % 360}, 70%, 40%)`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 512, 512);
  ctx.fillStyle = "rgba(255,255,255,0.08)";
  for (let i = 0; i < 8; i++) {
    ctx.beginPath();
    ctx.arc(Math.random() * 512, Math.random() * 512, 30 + Math.random() * 100, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.font = "16px monospace";
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.textAlign = "center";
  const words = prompt.split(" ").slice(0, 6);
  words.forEach((w, i) => ctx.fillText(w, 256, 230 + i * 24));
  return canvas.toDataURL("image/png");
}

const IMAGE_MODELS = {
  draft: [
    { id: "imagen-4-fast", name: "Imagen 4 Fast", provider: "google" },
    { id: "together-black-forest-labs/flux.1-schnell", name: "FLUX.1 Schnell", provider: "together" },
    { id: "together-rundiffusion/juggernaut-lightning-flux", name: "Juggernaut Lightning", provider: "together" },
  ],
  proof: [
    { id: "azure-gpt-image-2", name: "GPT-Image 2", provider: "azure" },
    { id: "google-imagen-4.0-ultra-generate-001", name: "Imagen 4 Ultra", provider: "google" },
    { id: "together-black-forest-labs/flux.2-pro", name: "FLUX.2 Pro", provider: "together" },
    { id: "together-ideogram-ai/ideogram-3.0", name: "Ideogram 3.0", provider: "together" },
    { id: "together-black-forest-labs/flux.1.1-pro", name: "FLUX.1.1 Pro", provider: "together" },
    { id: "together-black-forest-labs/flux.1-kontext-pro", name: "FLUX Kontext Pro", provider: "together" },
    { id: "google-gemini-3-pro-image", name: "Gemini 3 Pro Image", provider: "google" },
    { id: "together-rundiffusion/juggernaut-pro-flux", name: "Juggernaut Pro", provider: "together" },
    { id: "together-qwen/qwen-image-2.0-pro", name: "Qwen Image 2.0 Pro", provider: "together" },
    { id: "together-google/imagen-4.0-ultra", name: "Imagen 4 Ultra (Together)", provider: "together" },
  ],
};

let _canvases = [];
let _layers = {};
let _idCounter = 1;
let _layerIdCounter = 1;
let _jobIdCounter = 1;

function uid() { return "c" + _idCounter++; }
function layerUid() { return "l" + _layerIdCounter++; }
function jobUid() { return "j" + _jobIdCounter++; }
function delay(ms = 50) { return new Promise((r) => setTimeout(r, ms)); }

const api = {
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
        "1:1": [1024, 1024], "16:9": [1824, 1024], "9:16": [1024, 1824],
        "3:2": [1536, 1024], "2:3": [1024, 1536], "4:3": [1360, 1024],
        "3:4": [1024, 1360],
      };
      [width, height] = ratios[body.aspect_ratio] || [1024, 1024];
    }
    const canvas = {
      id: uid(), name: body.name || "Untitled", width, height,
      background_color: body.background_color || "#FFFFFF", org_id: "demo",
      layer_count: 0, created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(), archived_at: null,
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
    const z = body.z_index != null ? body.z_index
      : existing.length > 0 ? Math.max(...existing.map((l) => l.z_index)) + 1 : 0;
    const layer = {
      id: layerUid(), canvas_id: canvasId, name: body.name || "Layer",
      layer_type: body.layer_type || "background", z_index: z,
      x: body.x || 0, y: body.y || 0, scale: body.scale ?? 1,
      rotation: body.rotation || 0, opacity: body.opacity ?? 1,
      blend_mode: body.blend_mode || "normal", visible: body.visible !== false,
      locked: !!body.locked, image_path: null, image_url: null,
      width: null, height: null, prompt: body.prompt || null,
      negative_prompt: body.negative_prompt || null, model_id: null,
      tier: body.tier || "draft", created_at: new Date().toISOString(),
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
    _layers[canvasId] = (_layers[canvasId] || []).filter((l) => l.id !== layerId);
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
    const list = _layers[canvasId] || [];
    const layer = list.find((l) => l.id === layerId);
    if (!layer) throw new Error("Layer not found");

    const modelId = body.model_id || IMAGE_MODELS.draft[0].id;
    const jobId = jobUid();
    layer._generating = true;

    try {
      let dataUrl = null;

      // Provider selection + credentials live server-side (see server.js
      // /api/llm/image). The server tries Azure / LiteLLM / Gemini in turn.
      try {
        dataUrl = await generateImage({
          prompt: body.prompt,
          model_id: modelId,
          n: body.count || 1,
          size: "1024x1024",
        });
      } catch (genErr) {
        console.warn("Image gen failed:", genErr.message);
      }

      if (!dataUrl) {
        console.warn("All providers failed, using placeholder");
        dataUrl = makePlaceholderImage(body.prompt || "generated");
      }
      layer.image_url = dataUrl;
      layer.image_path = dataUrl;
      layer.width = 1024;
      layer.height = 1024;
      layer.prompt = body.prompt;
      layer.model_id = modelId;

      layer._generating = false;
      layer.updated_at = new Date().toISOString();
      return { job_id: jobId, status: "done" };
    } catch (err) {
      layer._generating = false;
      throw err;
    }
  },

  async getJob(jobId) {
    await delay(10);
    return { id: jobId, status: "done", result_paths: [] };
  },

  async cancelJob() { await delay(); },
  async acceptVariant() { await delay(); },

  async composite(canvasId) {
    await delay(200);
    const c = _canvases.find((c) => c.id === canvasId);
    if (!c) throw new Error("not found");
    const canvas = document.createElement("canvas");
    canvas.width = c.width;
    canvas.height = c.height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = c.background_color || "#FFFFFF";
    ctx.fillRect(0, 0, c.width, c.height);

    const sorted = [...(_layers[canvasId] || [])]
      .filter((l) => l.visible !== false && l.image_url)
      .sort((a, b) => (a.z_index ?? 0) - (b.z_index ?? 0));

    for (const ly of sorted) {
      try {
        const img = new Image();
        img.crossOrigin = "anonymous";
        const src = ly.image_url;
        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = reject;
          img.src = src;
        });
        ctx.globalAlpha = ly.opacity ?? 1;
        ctx.save();
        ctx.translate(ly.x || 0, ly.y || 0);
        const w = img.naturalWidth * (ly.scale || 1);
        const h = img.naturalHeight * (ly.scale || 1);
        ctx.drawImage(img, 0, 0, w, h);
        ctx.restore();
      } catch { /* best-effort draw; a tainted or unloadable source leaves the canvas as-is */ }
    }
    ctx.globalAlpha = 1;

    const b64 = canvas.toDataURL("image/png").replace(/^data:image\/png;base64,/, "");
    return { image_b64: b64 };
  },

  async getLatestComposite(canvasId) {
    return api.composite(canvasId);
  },

  exportUrl(canvasId, format = "png") {
    return `#export-${canvasId}-${format}`;
  },

  async listModels() {
    return [
      ...IMAGE_MODELS.draft.map((m) => ({ ...m, tier_class: "draft", is_free: m.id.includes("schnell") })),
      ...IMAGE_MODELS.proof.map((m) => ({ ...m, tier_class: "proof", is_free: false })),
    ];
  },

  getImageModels() {
    return IMAGE_MODELS;
  },
};

const PLANNER_MODEL = "gemini-flash";
const PLANNER_PROMPT = `You are a scene decomposition engine for a layered image compositor. 

Given a scene description, break it into discrete layers ordered back-to-front (z_index 0 = background, highest = foreground). Each layer should be a single visual element that can be independently generated and positioned.

Return ONLY valid JSON - no markdown, no explanation:
{
  "name": "scene name",
  "aspect_ratio": "16:9",
  "background_color": "#HEX",
  "layers": [
    {
      "name": "layer name",
      "layer_type": "background|character|object|text",
      "prompt": "detailed image generation prompt for this specific layer element on transparent/white background",
      "z_index": 0
    }
  ]
}

Rules:
- 2-6 layers max
- Background layer is always first (z_index 0)
- Each prompt must describe ONLY that element, suitable for standalone generation
- Characters/objects should specify "on transparent background" or "on pure white background"
- Prompts should be detailed enough for high quality generation
- Think about depth: sky/environment -> midground -> foreground subjects -> overlay effects`;

async function planScene(description) {
  const text = await chat(
    [
      { role: "system", content: PLANNER_PROMPT },
      { role: "user", content: description },
    ],
    PLANNER_MODEL,
    { temperature: 0.7, max_tokens: 2000 }
  );
  const jsonMatch = text.match(/\{[\s\S]*\}/);
  if (!jsonMatch) throw new Error("AI returned invalid plan");
  return JSON.parse(jsonMatch[0]);
}

export { api, IMAGE_MODELS, planScene };
export default api;

export function pollJob(jobId, interval = 2000) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const job = await api.getJob(jobId);
        if (job.status === "done" || job.status === "failed") {
          clearInterval(timer);
          resolve(job);
        }
      } catch (err) {
        clearInterval(timer);
        reject(err);
      }
    }, interval);
  });
}
