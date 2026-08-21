// Same-origin LLM/image client.
//
// SECURITY: the browser must never hold provider credentials. All LLM chat and
// image-generation traffic is routed through the Express server proxy at
// /api/llm/*, which injects the LiteLLM / Azure / Gemini keys server-side from
// non-VITE environment variables. No Authorization/api-key header is ever set
// here, and no provider endpoint is ever called directly from the bundle.
//
// In dev, Vite proxies /api -> the Express server (see vite.config.js).

const CHAT_PATH = "/api/llm/chat";
const IMAGE_PATH = "/api/llm/image";
const PIPELINE_IMAGE_PATH = "/api/llm/pipeline-image";
const IMAGE_EDIT_PATH = "/api/llm/image-edit";

/**
 * Send a chat completion request through the server proxy.
 * @param {Array} messages OpenAI-style messages array.
 * @param {string} model   LiteLLM model id.
 * @param {object} opts    Optional { temperature, max_tokens }.
 * @returns {Promise<string>} assistant message content.
 */
export async function chat(messages, model = "gemini-flash", opts = {}) {
  const res = await fetch(CHAT_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      messages,
      temperature: opts.temperature ?? 0.5,
      max_tokens: opts.max_tokens ?? 4000,
    }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error?.message || e.error || `LLM ${res.status}`);
  }
  const data = await res.json();
  return data.choices?.[0]?.message?.content || "";
}

/**
 * Generate an image through the server proxy. The server picks the provider
 * (Azure / LiteLLM / Gemini) based on model_id and available server-side keys.
 * @param {object} body { prompt, model_id?, size?, quality?, n? }
 * @returns {Promise<string|null>} a data: URL or remote URL, or null if none.
 */
export async function generateImage(body) {
  const res = await fetch(IMAGE_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error?.message || e.error || `Image ${res.status}`);
  }
  const data = await res.json();
  return data.image || null;
}

/**
 * Rendering-pipeline image generation (multi-deployment Azure + Gemini fallback,
 * resolved server-side). Throws if every configured provider failed.
 * @param {object} body { prompt, size?, quality?, tier? }
 * @returns {Promise<string|null>}
 */
export async function pipelineImage(body) {
  const res = await fetch(PIPELINE_IMAGE_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error?.message || e.error || `Image ${res.status}`);
  }
  const data = await res.json();
  return data.image || null;
}

/**
 * Image edit via the server proxy (Azure multipart, reconstructed server-side).
 * @param {object} body { images: string[]|string, prompt, size?, quality?, input_fidelity? }
 * @returns {Promise<string|null>}
 */
export async function editImage(body) {
  const res = await fetch(IMAGE_EDIT_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error?.message || e.error || `Image edit ${res.status}`);
  }
  const data = await res.json();
  return data.image || null;
}
