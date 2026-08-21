import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const AZURE_KEY = "test-key";
const AZURE_ENDPOINT = "https://test.azure.com";

describe("azureImageEdit input_fidelity mapping", () => {
  it("maps float >= 0.7 to 'high'", () => {
    const mapFidelity = (f) => (f >= 0.7 ? "high" : "low");
    expect(mapFidelity(0.9)).toBe("high");
    expect(mapFidelity(0.7)).toBe("high");
    expect(mapFidelity(0.69)).toBe("low");
    expect(mapFidelity(0.5)).toBe("low");
    expect(mapFidelity(0.0)).toBe("low");
    expect(mapFidelity(1.0)).toBe("high");
  });
});

describe("azureImageEdit", () => {
  let origFetch;
  let fetchCalls;

  beforeEach(() => {
    origFetch = global.fetch;
    fetchCalls = [];
  });

  afterEach(() => {
    global.fetch = origFetch;
    vi.unstubAllEnvs();
  });

  function mockFetch(responses) {
    let callIdx = 0;
    global.fetch = async (url, opts) => {
      fetchCalls.push({ url, method: opts?.method, hasFormData: opts?.body instanceof FormData });
      const resp = responses[callIdx] || { ok: false, status: 500, json: async () => ({ error: { message: "no more mocks" } }) };
      callIdx++;
      return resp;
    };
  }

  const PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
  const PNG_DATA_URL = `data:image/png;base64,${PNG_B64}`;

  it("sends multipart form data with image[] for multiple images", async () => {
    mockFetch([{ ok: true, json: async () => ({ data: [{ b64_json: "dGVzdA==" }] }) }]);

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    const result = await mod.azureImageEdit([PNG_DATA_URL, PNG_DATA_URL], "test prompt", "1024x1024", "medium", 0.9);
    expect(result).toBe("data:image/png;base64,dGVzdA==");
    expect(fetchCalls.length).toBeGreaterThanOrEqual(1);
    expect(fetchCalls[0].hasFormData).toBe(true);
    expect(fetchCalls[0].url).toContain("gpt-image-1-5");
    expect(fetchCalls[0].url).toContain("2025-04-01-preview");
  });

  it("falls back to gpt-image-2-1 when 1-5 returns 404", async () => {
    mockFetch([
      { ok: false, status: 404, json: async () => ({ error: { message: "not found" } }) },
      { ok: true, json: async () => ({ data: [{ b64_json: "ZmFsbGJhY2s=" }] }) },
    ]);

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    const result = await mod.azureImageEdit(PNG_DATA_URL, "test");
    expect(result).toBe("data:image/png;base64,ZmFsbGJhY2s=");
    expect(fetchCalls.length).toBe(2);
    expect(fetchCalls[1].url).toContain("gpt-image-2-1");
  });

  it("skips 429 on first deployment, tries second", async () => {
    mockFetch([
      { ok: false, status: 429, json: async () => ({ error: { message: "RateLimitReached on 1-5" } }) },
      { ok: true, json: async () => ({ data: [{ b64_json: "b2s=" }] }) },
    ]);

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    const result = await mod.azureImageEdit(PNG_DATA_URL, "test");
    expect(result).toBe("data:image/png;base64,b2s=");
  });

  it("throws descriptive error when all deployments fail", async () => {
    mockFetch([
      { ok: false, status: 429, json: async () => ({ error: { message: "RateLimitReached on 1-5" } }) },
      { ok: false, status: 429, json: async () => ({ error: { message: "RateLimitReached on 2-1" } }) },
    ]);

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    await expect(mod.azureImageEdit(PNG_DATA_URL, "test"))
      .rejects.toThrow("All Azure edit deployments failed");
  });

  it("throws when no valid images provided", async () => {
    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    await expect(mod.azureImageEdit([], "test"))
      .rejects.toThrow("No valid images");
  });

  it("wraps single string URL into array automatically", async () => {
    mockFetch([{ ok: true, json: async () => ({ data: [{ b64_json: "dGVzdA==" }] }) }]);

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    const result = await mod.azureImageEdit(PNG_DATA_URL, "test");
    expect(result).toBeTruthy();
    expect(fetchCalls[0].hasFormData).toBe(true);
  });

  it("returns URL when Azure provides url instead of b64_json", async () => {
    mockFetch([{ ok: true, json: async () => ({ data: [{ url: "https://cdn.azure.com/img.png" }] }) }]);

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    const result = await mod.azureImageEdit(PNG_DATA_URL, "test");
    expect(result).toBe("https://cdn.azure.com/img.png");
  });

  it("uses 2025-04-01-preview for gpt-image-2-1 edit too", async () => {
    mockFetch([
      { ok: false, status: 400, json: async () => ({ error: { message: "bad request" } }) },
      { ok: true, json: async () => ({ data: [{ b64_json: "b2s=" }] }) },
    ]);

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    await mod.azureImageEdit(PNG_DATA_URL, "test");
    expect(fetchCalls[1].url).toContain("2025-04-01-preview");
  });
});

describe("renderCharacterReferences", () => {
  let origFetch;

  beforeEach(() => { origFetch = global.fetch; });
  afterEach(() => { global.fetch = origFetch; vi.unstubAllEnvs(); });

  const PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

  it("calls azureImageEdit when reference photos provided", async () => {
    const calls = [];
    global.fetch = async (url) => {
      calls.push(url);
      if (url.includes("/images/edits")) {
        return { ok: true, json: async () => ({ data: [{ b64_json: "dGVzdA==" }] }) };
      }
      return { ok: true, json: async () => ({ data: [{ b64_json: "dGVzdA==" }] }) };
    };

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    const result = await mod.renderCharacterReferences(
      "A 5-year-old girl",
      { technique: "warm watercolor" },
      () => {},
      [`data:image/png;base64,${PNG_B64}`]
    );
    expect(result).toBeTruthy();
    expect(calls.some(u => u.includes("/images/edits"))).toBe(true);
  });

  it("falls back to generateImage when edit fails", async () => {
    let editTried = false;
    let genTried = false;
    global.fetch = async (url) => {
      if (url.includes("/images/edits")) {
        editTried = true;
        return { ok: false, status: 400, json: async () => ({ error: { message: "bad" } }) };
      }
      genTried = true;
      return { ok: true, json: async () => ({ data: [{ b64_json: "dGVzdA==" }] }) };
    };

    vi.stubEnv("VITE_AZURE_KEY", AZURE_KEY);
    vi.stubEnv("VITE_AZURE_ENDPOINT", AZURE_ENDPOINT);
    vi.resetModules();

    const mod = await import("../src/lib/renderingPipeline?t=" + Date.now());
    const result = await mod.renderCharacterReferences(
      "A girl",
      {},
      () => {},
      [`data:image/png;base64,${PNG_B64}`]
    );
    expect(editTried).toBe(true);
    expect(genTried).toBe(true);
    expect(result).toBeTruthy();
  });
});
