/**
 * @vitest-environment jsdom
 *
 * Security regression tests: the browser bundle must NEVER hold provider keys
 * and must NEVER call provider endpoints directly. All LLM/image traffic goes
 * through the same-origin Express proxy (/api/llm/*), which holds the keys
 * server-side (non-VITE env).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("llmClient — server-proxy routing", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("chat() posts to the same-origin proxy, not LiteLLM directly", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ choices: [{ message: { content: "hi" } }] }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { chat } = await import("../src/lib/llmClient");
    const out = await chat([{ role: "user", content: "hello" }], "gemini-flash");

    expect(out).toBe("hi");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0][0];
    expect(url).toBe("/api/llm/chat");
  });

  it("chat() never sends an Authorization / Bearer header from the client", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ choices: [{ message: { content: "x" } }] }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { chat } = await import("../src/lib/llmClient");
    await chat([{ role: "user", content: "hello" }]);

    const opts = fetchMock.mock.calls[0][1] || {};
    const headers = opts.headers || {};
    const headerKeys = Object.keys(headers).map((k) => k.toLowerCase());
    expect(headerKeys).not.toContain("authorization");
    expect(headerKeys).not.toContain("api-key");
    const serialized = JSON.stringify(headers);
    expect(serialized).not.toContain("Bearer");
  });

  it("generateImage() posts to the same-origin image proxy", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ image: "data:image/png;base64,AAAA" }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    const { generateImage } = await import("../src/lib/llmClient");
    const out = await generateImage({ prompt: "a cat", model_id: "azure-gpt-image-2" });

    expect(out).toBe("data:image/png;base64,AAAA");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/llm/image");
  });
});

describe("client source — no embedded secrets", () => {
  // The literal key must not appear anywhere in shipped client lib source.
  // Split so the literal does not itself land in this test as a copy of the secret.
  const FORBIDDEN = ["sk-conductor", "litellm", "2026"].join("-");

  const libFiles = [
    "api.js",
    "bookApi.js",
    "storyApi.js",
    "renderingPipeline.js",
    "llmClient.js",
  ];

  it.each(libFiles)("%s contains no hardcoded LiteLLM key fallback", async (file) => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    // vitest runs with cwd at the frontend package root.
    const path = join(process.cwd(), "src", "lib", file);
    const src = readFileSync(path, "utf8");
    expect(src).not.toContain(FORBIDDEN);
  });

  it.each(libFiles)("%s reads no VITE_ provider key from the bundle", async (file) => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    // vitest runs with cwd at the frontend package root.
    const path = join(process.cwd(), "src", "lib", file);
    const src = readFileSync(path, "utf8");
    expect(src).not.toContain("VITE_LITELLM_KEY");
    expect(src).not.toContain("VITE_AZURE_KEY");
    expect(src).not.toContain("VITE_GEMINI_API_KEY");
  });
});
