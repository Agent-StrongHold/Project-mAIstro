import express from "express";
import cors from "cors";
import pg from "pg";
import { resolveSecurityConfig, isOriginAllowed, requireToken } from "./server/security.js";
import {
  createHandoffStore,
  handoffLink,
  HANDOFF_EXPIRED,
  HANDOFF_ORIGIN_MISMATCH,
} from "./server/handoff.js";

const { Pool } = pg;
const pool = new Pool({
  host: process.env.CANVAS_DB_HOST || "127.0.0.1",
  port: Number(process.env.CANVAS_DB_PORT || 5440),
  user: process.env.CANVAS_DB_USER || "canvas",
  password: process.env.CANVAS_DB_PASSWORD || "",
  database: process.env.CANVAS_DB_NAME || "canvas_studio",
});

const security = resolveSecurityConfig();

const handoffs = createHandoffStore();

const app = express();
app.use(cors({ origin: (o, cb) => cb(null, isOriginAllowed(o, security.origins)), credentials: true }));
app.use(express.json({ limit: security.bodyLimit }));

// No credential this server issues may reach a third party through a header
// the browser adds on its own. `Referer` is the one that does that by default,
// and a Canvas page links out (asset hosts, docs), so the policy is set for
// every response rather than per-route (#372).
app.use((req, res, next) => {
  res.set("Referrer-Policy", "no-referrer");
  next();
});

// Unauthenticated on purpose: the handoff code IS the credential being
// presented, so requiring one to redeem it would be circular. It is safe to
// leave open because the code is single-use, expires in two minutes, and is
// bound to the origin it was minted for — and because the response says
// nothing a guesser can use (see the store's UNKNOWN reason).
//
// Mounted BEFORE the /api token guard so the redeem itself is reachable.
app.post("/api/handoff/redeem", (req, res) => {
  // A credential must never be cached by a proxy or the browser's bfcache.
  res.set("Cache-Control", "no-store");
  const result = handoffs.redeem(req.body?.code, { origin: req.get("origin") });
  if (result.ok) {
    // The code is deliberately absent from this log line. A code in a log is
    // the same exposure the URL fragment was.
    console.log("Canvas handoff redeemed; session issued");
    return res.json({ token: result.token, expiresAt: result.expiresAt });
  }
  // 401 for every rejection, with the reason only as a recovery hint. The
  // status code must not distinguish "never existed" from "already used".
  return res.status(401).json({
    error: "handoff_rejected",
    reason: result.reason,
    recovery:
      result.reason === HANDOFF_EXPIRED
        ? "This link has expired. Ask the operator for a fresh one."
        : result.reason === HANDOFF_ORIGIN_MISMATCH
          ? "This link was issued for a different Canvas deployment."
          : "This link has already been used, or is not valid. Ask the operator for a fresh one.",
  });
});

app.use("/api", requireToken(security, handoffs));

function safeKey(key) {
  return (key || "untitled").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
}

app.post("/api/books/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  const payload = { ...req.body, savedAt: new Date().toISOString() };
  try {
    await pool.query(
      `INSERT INTO books (key, data, updated_at) VALUES ($1, $2, now())
       ON CONFLICT (key) DO UPDATE SET data = $2, updated_at = now()`,
      [key, JSON.stringify(payload)]
    );
    res.json({ ok: true, savedAt: payload.savedAt });
  } catch (e) {
    console.error("Save error:", e.message);
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/books/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    const { rows } = await pool.query("SELECT data FROM books WHERE key = $1", [key]);
    if (rows.length === 0) return res.status(404).json({ error: "not found" });
    res.json(rows[0].data);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/books", async (_req, res) => {
  try {
    const { rows } = await pool.query(
      "SELECT key, data->>'savedAt' as saved_at, data->>'step' as step, data->'bookSpec'->>'title' as title, data->'bookSpec'->>'premise' as premise FROM books ORDER BY updated_at DESC"
    );
    const results = rows.map((r) => ({
      key: r.key,
      title: r.title || r.premise?.slice(0, 40) || r.key,
      step: r.step,
      bookSpec: { title: r.title, premise: r.premise },
      savedAt: r.saved_at,
    }));
    res.json(results);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.delete("/api/books/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    await pool.query("DELETE FROM books WHERE key = $1", [key]);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.delete("/api/books", async (_req, res) => {
  if (!security.allowTruncate) {
    return res.status(403).json({ error: "bulk delete disabled; set CANVAS_ALLOW_TRUNCATE=true" });
  }
  try {
    await pool.query("TRUNCATE books");
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── Templates ─────────────────────────────────────────────────────────────

app.get("/api/templates", async (_req, res) => {
  try {
    const { rows } = await pool.query("SELECT key, data FROM templates ORDER BY updated_at DESC");
    res.json(rows.map((r) => ({ key: r.key, ...r.data })));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post("/api/templates/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    await pool.query(
      `INSERT INTO templates (key, data, updated_at) VALUES ($1, $2, now())
       ON CONFLICT (key) DO UPDATE SET data = $2, updated_at = now()`,
      [key, JSON.stringify(req.body)]
    );
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.delete("/api/templates/:key", async (req, res) => {
  try {
    await pool.query("DELETE FROM templates WHERE key = $1", [safeKey(req.params.key)]);
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ── Characters ─────────────────────────────────────────────────────────────

app.get("/api/characters", async (_req, res) => {
  try {
    const { rows } = await pool.query("SELECT key, data FROM characters ORDER BY updated_at DESC");
    res.json(rows.map((r) => ({ key: r.key, ...r.data })));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get("/api/characters/:key", async (req, res) => {
  try {
    const { rows } = await pool.query("SELECT data FROM characters WHERE key = $1", [safeKey(req.params.key)]);
    if (rows.length === 0) return res.status(404).json({ error: "not found" });
    res.json(rows[0].data);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post("/api/characters/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    await pool.query(
      `INSERT INTO characters (key, data, updated_at) VALUES ($1, $2, now())
       ON CONFLICT (key) DO UPDATE SET data = $2, updated_at = now()`,
      [key, JSON.stringify({ ...req.body, savedAt: new Date().toISOString() })]
    );
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.delete("/api/characters/:key", async (req, res) => {
  try {
    await pool.query("DELETE FROM characters WHERE key = $1", [safeKey(req.params.key)]);
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ── Lulu Print-on-Demand ─────────────────────────────────────────────────
// The Lulu client runs as a separate Python service at LULU_SERVICE_URL.
// See server/lulu/ for the Python implementation.

const LULU_SERVICE_URL = process.env.LULU_SERVICE_URL || "http://localhost:8260";

app.get("/api/print/packages", async (_req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/packages`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/shipping-cost", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query).toString();
    const r = await fetch(`${LULU_SERVICE_URL}/shipping-cost?${params}`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.post("/api/print/order", async (req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Lulu service ${r.status}`);
    }
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/orders", async (_req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/orders`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/orders/:id", async (req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/orders/${req.params.id}`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.post("/api/print/orders/:id/cancel", async (req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/orders/${req.params.id}/cancel`, { method: "POST" });
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/health", async (_req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/health`, { signal: AbortSignal.timeout(3000) });
    res.json(await r.json());
  } catch {
    res.json({ configured: false, healthy: false });
  }
});

const PORT = Number(process.env.CANVAS_PORT || 5174);

// ── Generation Attempts (training data) ──────────────────────────────────

app.post("/api/generation-attempts", async (req, res) => {
  const { book_key, scene_id, layer_id, attempt_type, prompt, model_id, quality, verdict, data } = req.body;
  if (!book_key || !scene_id || !layer_id || !attempt_type) {
    return res.status(400).json({ error: "book_key, scene_id, layer_id, attempt_type required" });
  }
  try {
    const { rows } = await pool.query(
      `INSERT INTO generation_attempts (book_key, scene_id, layer_id, attempt_type, prompt, model_id, quality, verdict, data)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id, created_at`,
      [book_key, scene_id, layer_id, attempt_type, prompt || "", model_id || null, quality || "draft", verdict || "pending", JSON.stringify(data || {})]
    );
    res.json({ ok: true, id: rows[0].id, created_at: rows[0].created_at });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.patch("/api/generation-attempts/:id/verdict", async (req, res) => {
  const { verdict } = req.body;
  if (!verdict) return res.status(400).json({ error: "verdict required" });
  try {
    const { rowCount } = await pool.query(
      "UPDATE generation_attempts SET verdict = $1 WHERE id = $2", [verdict, req.params.id]
    );
    if (rowCount === 0) return res.status(404).json({ error: "not found" });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/generation-attempts", async (req, res) => {
  const { book_key, scene_id } = req.query;
  try {
    const clauses = [];
    const params = [];
    if (book_key) { params.push(book_key); clauses.push(`book_key = $${params.length}`); }
    if (scene_id) { params.push(scene_id); clauses.push(`scene_id = $${params.length}`); }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const { rows } = await pool.query(
      `SELECT id, book_key, scene_id, layer_id, attempt_type, prompt, model_id, quality, verdict, created_at FROM generation_attempts ${where} ORDER BY id DESC LIMIT 500`, params
    );
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── Page Layout Versions (training data) ──────────────────────────────────

app.post("/api/layout-versions", async (req, res) => {
  const { book_key, scene_id, layout, diff } = req.body;
  if (!book_key || !scene_id || !layout) {
    return res.status(400).json({ error: "book_key, scene_id, layout required" });
  }
  try {
    const { rows: prev } = await pool.query(
      "SELECT version FROM page_layout_versions WHERE book_key = $1 AND scene_id = $2 ORDER BY version DESC LIMIT 1",
      [book_key, scene_id]
    );
    const version = prev.length > 0 ? prev[0].version + 1 : 1;
    const { rows } = await pool.query(
      `INSERT INTO page_layout_versions (book_key, scene_id, version, layout, diff) VALUES ($1,$2,$3,$4,$5) RETURNING id, version, created_at`,
      [book_key, scene_id, version, JSON.stringify(layout), diff ? JSON.stringify(diff) : null]
    );
    res.json({ ok: true, id: rows[0].id, version: rows[0].version, created_at: rows[0].created_at });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/layout-versions", async (req, res) => {
  const { book_key, scene_id } = req.query;
  try {
    const clauses = [];
    const params = [];
    if (book_key) { params.push(book_key); clauses.push(`book_key = $${params.length}`); }
    if (scene_id) { params.push(scene_id); clauses.push(`scene_id = $${params.length}`); }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const { rows } = await pool.query(
      `SELECT id, book_key, scene_id, version, layout, diff, created_at FROM page_layout_versions ${where} ORDER BY id DESC LIMIT 200`, params
    );
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── PDF Export ────────────────────────────────────────────────────────────

import { execFile } from "child_process";
import { mkdtemp, rmdir, stat } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

const EXPORT_SCRIPT = join(import.meta.dirname, "server", "export_book.py");

// /api/export spawns a python3 process per request with a caller-supplied page
// list and a 100MB stdout buffer. Without a cap, one client can hold the box's
// entire CPU and memory budget: N concurrent requests => N python processes.
let activeExports = 0;

app.post("/api/export", async (req, res) => {
  const { mode, title, author, product_id, pages, front_cover, back_cover } = req.body;
  if (!pages?.length) return res.status(400).json({ error: "pages required" });
  if (pages.length > security.maxExportPages) {
    return res.status(413).json({
      error: `too many pages: ${pages.length} > ${security.maxExportPages} (CANVAS_MAX_EXPORT_PAGES)`,
    });
  }
  if (activeExports >= security.maxConcurrentExports) {
    return res.status(503).json({ error: "export queue full, retry shortly" });
  }
  activeExports += 1;
  let released = false;
  let tmpDir;
  let childProcess = null;
  let streamStarted = false;

  const release = () => {
    if (released) return;
    released = true;
    activeExports -= 1;
    if (tmpDir) rmdir(tmpDir, { recursive: true }).catch(() => {});
  };

  // A disconnected client must not free the slot while its renderer is still
  // consuming CPU/memory. Kill the active renderer, but let execFile's exit
  // callback/catch path release the slot only after the process is actually
  // reaped. If rendering has already finished, either the file stream owns the
  // remaining lifetime or there is nothing left to hold.
  res.on("close", () => {
    if (childProcess && childProcess.exitCode === null && !childProcess.killed) {
      childProcess.kill("SIGKILL");
      return;
    }
    if (!streamStarted) release();
  });

  try {
    tmpDir = await mkdtemp(join(tmpdir(), "canvas-export-"));
    const payload = JSON.stringify({ mode: mode || "interior", title, author, product_id, pages, front_cover, back_cover, output_dir: tmpDir });

    await new Promise((resolve, reject) => {
      childProcess = execFile("python3", [EXPORT_SCRIPT], { maxBuffer: 100 * 1024 * 1024 }, (err, stdout, stderr) => {
        childProcess = null;
        if (err) return reject(stderr || err.message);
        try {
          const result = JSON.parse(stdout.trim());
          if (!result.ok) return reject(result.error || "export failed");
          resolve(result.path);
        } catch (e) { reject(e.message); }
      });
      childProcess.stdin.write(payload);
      childProcess.stdin.end();
    });

    // The response may have disappeared just as the child exited. There is no
    // stream to own cleanup in that case, so release now and do not touch the
    // destroyed socket.
    if (res.destroyed && !res.writableEnded) {
      release();
      return;
    }

    const pdfName = mode === "cover" ? "cover.pdf" : "interior.pdf";
    const pdfPath = join(tmpDir, pdfName);
    const pdfStat = await stat(pdfPath);

    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Length", pdfStat.size);
    res.setHeader("Content-Disposition", `attachment; filename="${(title || "book").replace(/[^a-zA-Z0-9_-]/g, "_")}_${pdfName}"`);

    const { createReadStream } = await import("fs");
    const stream = createReadStream(pdfPath);
    streamStarted = true;
    // Once rendering is complete, the response stream owns the slot/tempdir.
    // 'close' covers both normal completion and a torn-down pipe.
    stream.on("close", release);
    stream.on("error", release);
    stream.pipe(res);
  } catch (e) {
    release();
    console.error("Export error:", e);
    if (!res.headersSent && !res.destroyed) {
      res.status(500).json({ error: typeof e === "string" ? e : e.message });
    }
  }
});

// ── LLM / Image proxy ──────────────────────────────────────────────────────
// SECURITY: provider credentials live here, server-side, in NON-VITE env vars.
// The browser bundle never holds keys and never calls providers directly.
//   LITELLM_URL, LITELLM_KEY  — LiteLLM gateway (chat + image)
//   AZURE_ENDPOINT, AZURE_KEY — Azure OpenAI image generation
//   GEMINI_API_KEY            — Google Gemini native image generation

const LITELLM_URL = process.env.LITELLM_URL || "http://localhost:4000";
const LITELLM_KEY = process.env.LITELLM_KEY || "";
const AZURE_ENDPOINT = process.env.AZURE_ENDPOINT || "";
const AZURE_KEY = process.env.AZURE_KEY || "";
const AZURE_DEPLOYMENT = process.env.AZURE_DEPLOYMENT || "gpt-image-2-1";
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";

function litellmHeaders() {
  const h = { "Content-Type": "application/json" };
  if (LITELLM_KEY) h.Authorization = `Bearer ${LITELLM_KEY}`;
  return h;
}

// Chat completions — proxied verbatim to the LiteLLM gateway.
app.post("/api/llm/chat", async (req, res) => {
  try {
    const r = await fetch(`${LITELLM_URL}/v1/chat/completions`, {
      method: "POST",
      headers: litellmHeaders(),
      body: JSON.stringify(req.body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = data.error?.message || data.detail || `LLM ${r.status}`;
      return res.status(r.status).json({ error: msg });
    }
    res.json(data);
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

async function azureImage(prompt, opts = {}) {
  if (!AZURE_KEY || !AZURE_ENDPOINT) throw new Error("No Azure config");
  const url = `${AZURE_ENDPOINT}/openai/deployments/${AZURE_DEPLOYMENT}/images/generations?api-version=2025-03-01-preview`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "api-key": AZURE_KEY },
    body: JSON.stringify({
      prompt,
      n: opts.n || 1,
      size: opts.size || "1024x1024",
      quality: opts.quality || "medium",
    }),
    signal: AbortSignal.timeout(120000),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(e.error?.message || `Azure ${r.status}`);
  }
  const data = await r.json();
  const img = data.data?.[0];
  if (!img) throw new Error("No image from Azure");
  if (img.b64_json) return `data:image/png;base64,${img.b64_json}`;
  if (img.url) return img.url;
  throw new Error("No image data from Azure");
}

async function litellmImage(prompt, model, opts = {}) {
  const r = await fetch(`${LITELLM_URL}/v1/images/generations`, {
    method: "POST",
    headers: litellmHeaders(),
    body: JSON.stringify({
      model,
      prompt,
      n: opts.n || 1,
      size: opts.size || "1024x1024",
      response_format: "b64_json",
    }),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(e.error?.message || `LiteLLM ${r.status}`);
  }
  const data = await r.json();
  const img = data.data?.[0];
  if (!img) throw new Error("No image from LiteLLM");
  if (img.b64_json) return `data:image/png;base64,${img.b64_json}`;
  if (img.url) return img.url;
  throw new Error("No image data from LiteLLM");
}

async function geminiImage(prompt) {
  if (!GEMINI_API_KEY) throw new Error("No Gemini key");
  const r = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key=${GEMINI_API_KEY}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: `Generate an image: ${prompt}` }] }],
        generationConfig: { responseModalities: ["TEXT", "IMAGE"] },
      }),
    }
  );
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(e.error?.message || `Gemini ${r.status}`);
  }
  const data = await r.json();
  const part = data?.candidates?.[0]?.content?.parts?.find((p) => p.inlineData);
  if (!part) throw new Error("No image from Gemini");
  return `data:${part.inlineData.mimeType};base64,${part.inlineData.data}`;
}

// Image generation — server selects provider by model_id and available keys.
// Tries Azure (for azure-* models) / LiteLLM / Gemini, in turn. Returns
// { image: <data-or-remote-url> } or 502 if every configured provider failed.
app.post("/api/llm/image", async (req, res) => {
  const { prompt, model_id, size, quality, n } = req.body || {};
  if (!prompt) return res.status(400).json({ error: "prompt required" });

  const opts = { size, quality, n };
  const useAzure = typeof model_id === "string" && model_id.startsWith("azure");
  const errors = [];

  if (useAzure && AZURE_KEY && AZURE_ENDPOINT) {
    try {
      return res.json({ image: await azureImage(prompt, opts) });
    } catch (e) {
      errors.push(`azure: ${e.message}`);
    }
  }

  if (!useAzure && LITELLM_URL) {
    try {
      return res.json({ image: await litellmImage(prompt, model_id, opts) });
    } catch (e) {
      errors.push(`litellm: ${e.message}`);
    }
  }

  if (AZURE_KEY && AZURE_ENDPOINT) {
    try {
      return res.json({ image: await azureImage(prompt, opts) });
    } catch (e) {
      errors.push(`azure: ${e.message}`);
    }
  }

  if (GEMINI_API_KEY) {
    try {
      return res.json({ image: await geminiImage(prompt) });
    } catch (e) {
      errors.push(`gemini: ${e.message}`);
    }
  }

  res.status(502).json({
    error: errors.length ? errors.join("; ") : "no image provider configured",
  });
});

// Multi-deployment image generation (used by the rendering pipeline). Tries a
// list of Azure deployments / api-versions server-side, then falls back to
// Gemini. Returns { image } or 502.
const AZURE_GEN_DEPLOYMENTS = (process.env.AZURE_GEN_DEPLOYMENTS ||
  "gpt-image-1-5,gpt-image-2-1").split(",").map((s) => s.trim()).filter(Boolean);
const AZURE_DRAFT_DEPLOYMENTS = (process.env.AZURE_DRAFT_DEPLOYMENTS ||
  "gpt-image-1-mini").split(",").map((s) => s.trim()).filter(Boolean);
const AZURE_API_VERSIONS = ["2025-04-01-preview", "2025-03-01-preview"];

async function azureMultiDeploymentImage(prompt, deployments, opts = {}) {
  if (!AZURE_KEY || !AZURE_ENDPOINT) throw new Error("No Azure config");
  const body = JSON.stringify({
    prompt,
    n: 1,
    size: opts.size || "1024x1024",
    quality: opts.quality || "medium",
  });
  for (const dep of deployments) {
    for (const apiVer of AZURE_API_VERSIONS) {
      try {
        const r = await fetch(
          `${AZURE_ENDPOINT}/openai/deployments/${dep}/images/generations?api-version=${apiVer}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", "api-key": AZURE_KEY },
            body,
            signal: AbortSignal.timeout(180000),
          }
        );
        if (!r.ok) {
          if (r.status === 404 || r.status === 400 || r.status === 429) continue;
          const e = await r.json().catch(() => ({}));
          throw new Error(e.error?.message || `Azure ${r.status}`);
        }
        const data = await r.json();
        const img = data.data?.[0];
        if (img?.b64_json) return `data:image/png;base64,${img.b64_json}`;
        if (img?.url) return img.url;
      } catch (err) {
        if (err.name === "TimeoutError") throw err;
        continue;
      }
    }
  }
  throw new Error("All Azure deployments failed");
}

// Pipeline image generation: tier "draft" uses the mini deployments.
app.post("/api/llm/pipeline-image", async (req, res) => {
  const { prompt, size, quality, tier } = req.body || {};
  if (!prompt) return res.status(400).json({ error: "prompt required" });
  const deployments = tier === "draft" ? AZURE_DRAFT_DEPLOYMENTS : AZURE_GEN_DEPLOYMENTS;
  const errors = [];
  if (AZURE_KEY && AZURE_ENDPOINT) {
    try {
      return res.json({ image: await azureMultiDeploymentImage(prompt, deployments, { size, quality }) });
    } catch (e) { errors.push(`azure: ${e.message}`); }
  }
  if (GEMINI_API_KEY) {
    try { return res.json({ image: await geminiImage(prompt) }); }
    catch (e) { errors.push(`gemini: ${e.message}`); }
  }
  res.status(502).json({ error: errors.length ? errors.join("; ") : "no image provider configured" });
});

// Image edit (Azure multipart). Client sends data-URL images + prompt as JSON;
// the server reconstructs the multipart form so credentials stay server-side.
function dataUrlToBuffer(dataUrl) {
  const m = /^data:([^;]+);base64,(.+)$/.exec(dataUrl || "");
  if (!m) return null;
  return { mime: m[1], buf: Buffer.from(m[2], "base64") };
}

app.post("/api/llm/image-edit", async (req, res) => {
  if (!AZURE_KEY || !AZURE_ENDPOINT) {
    return res.status(502).json({ error: "No Azure config" });
  }
  const { images, prompt, size, quality, input_fidelity } = req.body || {};
  if (!prompt) return res.status(400).json({ error: "prompt required" });
  const urls = Array.isArray(images) ? images : [images];
  const parsed = urls.map(dataUrlToBuffer).filter(Boolean);
  if (parsed.length === 0) return res.status(400).json({ error: "no valid images" });

  const errors = [];
  for (const dep of AZURE_GEN_DEPLOYMENTS) {
    try {
      const form = new FormData();
      for (const { mime, buf } of parsed) {
        const ext = mime.includes("png") ? "png" : "jpg";
        form.append("image[]", new Blob([buf], { type: mime }), `image.${ext}`);
      }
      form.append("prompt", prompt);
      form.append("size", size || "1024x1024");
      form.append("n", "1");
      form.append("quality", quality || "medium");
      if (input_fidelity != null) {
        form.append("input_fidelity", input_fidelity >= 0.7 ? "high" : "low");
      }
      const r = await fetch(
        `${AZURE_ENDPOINT}/openai/deployments/${dep}/images/edits?api-version=${AZURE_API_VERSIONS[0]}`,
        { method: "POST", headers: { "api-key": AZURE_KEY }, body: form, signal: AbortSignal.timeout(180000) }
      );
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        const msg = e.error?.message || `Azure edit ${r.status} on ${dep}`;
        errors.push(msg);
        if (r.status === 404 || r.status === 400 || r.status === 429) continue;
        throw new Error(msg);
      }
      const data = await r.json();
      const img = data.data?.[0];
      if (img?.b64_json) return res.json({ image: `data:image/png;base64,${img.b64_json}` });
      if (img?.url) return res.json({ image: img.url });
    } catch (err) {
      if (err.name === "TimeoutError") break;
      errors.push(err.message);
      continue;
    }
  }
  res.status(502).json({ error: `All Azure edit deployments failed: ${errors.join("; ")}` });
});

// Bind loopback by default. The previous hardcoded "0.0.0.0" published a server
// that proxies operator LiteLLM/Azure/Gemini credentials and spawns python3 on
// every interface of whatever machine ran it, with no authentication at all.
// resolveSecurityConfig() refuses to return a non-loopback host without a token.
app.listen(PORT, security.host, () => {
  console.log(`Canvas Studio API → Postgres :5440, listening on ${security.host}:${PORT}`);
  if (!security.exposed) return;
  // One link, printed once, to the operator's own terminal — not into a chat
  // window, a ticket, or a screenshot. It carries a two-minute single-use code
  // rather than CANVAS_API_TOKEN, so a link that leaks after it is used, or
  // after two minutes, is worth nothing (#372).
  const origin = security.origins[0] || `http://${security.host}:${PORT}`;
  const { code, expiresAt } = handoffs.mint({ origin });
  const seconds = Math.round((expiresAt - Date.now()) / 1000);
  console.log(`Open Canvas within ${seconds}s: ${handoffLink(origin, code)}`);
  console.log("That link admits one browser, once. It is not the API token.");
});
