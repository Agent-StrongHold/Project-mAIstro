import { describe, it, expect, vi } from "vitest";
import { resolveSecurityConfig, isOriginAllowed, requireToken } from "./security.js";

// Review finding C4. `server.js` bound 0.0.0.0 with `cors()` wide open and no
// authentication, while proxying operator LiteLLM/Azure/Gemini credentials and
// spawning python3 per request. These tests pin the guard rails that replaced
// that; none of them pass against the pre-fix server.js, which had no security
// module at all.

describe("resolveSecurityConfig", () => {
  it("defaults to loopback with no token required", () => {
    const cfg = resolveSecurityConfig({});
    expect(cfg.host).toBe("127.0.0.1");
    expect(cfg.exposed).toBe(false);
    expect(cfg.token).toBe("");
  });

  it("refuses a routable bind without a token", () => {
    // The whole point of the fix: making the server reachable must be a
    // deliberate act that also supplies credentials, not a default.
    expect(() => resolveSecurityConfig({ CANVAS_HOST: "0.0.0.0" })).toThrow(/CANVAS_API_TOKEN/);
  });

  it("allows a routable bind once a token is set", () => {
    const cfg = resolveSecurityConfig({ CANVAS_HOST: "0.0.0.0", CANVAS_API_TOKEN: "t" });
    expect(cfg.exposed).toBe(true);
    expect(cfg.token).toBe("t");
  });

  it("keeps bulk delete off unless explicitly enabled", () => {
    expect(resolveSecurityConfig({}).allowTruncate).toBe(false);
    expect(resolveSecurityConfig({ CANVAS_ALLOW_TRUNCATE: "true" }).allowTruncate).toBe(true);
    // Any other value is not consent.
    expect(resolveSecurityConfig({ CANVAS_ALLOW_TRUNCATE: "1" }).allowTruncate).toBe(false);
  });

  it("exposes export caps", () => {
    const cfg = resolveSecurityConfig({
      CANVAS_MAX_EXPORT_PAGES: "5",
      CANVAS_MAX_CONCURRENT_EXPORTS: "1",
    });
    expect(cfg.maxExportPages).toBe(5);
    expect(cfg.maxConcurrentExports).toBe(1);
  });

  it("falls back to the default rather than NaN on a malformed cap", () => {
    // NaN would be the dangerous outcome: `pages.length > NaN` is false, so a
    // typo would silently disable the cap instead of restoring it.
    for (const bad of ["unlimited", "two", "0", "-1", "abc"]) {
      const cfg = resolveSecurityConfig({
        CANVAS_MAX_EXPORT_PAGES: bad,
        CANVAS_MAX_CONCURRENT_EXPORTS: bad,
      });
      expect(cfg.maxExportPages).toBe(400);
      expect(cfg.maxConcurrentExports).toBe(2);
    }
  });

  it("truncates a fractional cap instead of comparing against a float", () => {
    expect(resolveSecurityConfig({ CANVAS_MAX_CONCURRENT_EXPORTS: "2.9" }).maxConcurrentExports).toBe(2);
  });
});

describe("isOriginAllowed", () => {
  const origins = ["http://localhost:5173"];

  it("permits a listed origin", () => {
    expect(isOriginAllowed("http://localhost:5173", origins)).toBe(true);
  });

  it("rejects an unlisted origin", () => {
    expect(isOriginAllowed("https://evil.example", origins)).toBe(false);
  });

  it("permits a request with no Origin header", () => {
    // curl and the export tooling send none; Origin-based rules only bind
    // browsers, which always send one.
    expect(isOriginAllowed(undefined, origins)).toBe(true);
  });
});

describe("requireToken", () => {
  const res = () => {
    const r = { code: null, body: null };
    r.status = (c) => ((r.code = c), r);
    r.json = (b) => ((r.body = b), r);
    return r;
  };
  const req = (headers) => ({ get: (k) => headers[k.toLowerCase()] });

  it("is a no-op when no token is configured (loopback mode)", () => {
    const next = vi.fn();
    requireToken({ token: "" })(req({}), res(), next);
    expect(next).toHaveBeenCalled();
  });

  it("rejects a missing token when one is configured", () => {
    const next = vi.fn();
    const r = res();
    requireToken({ token: "secret" })(req({}), r, next);
    expect(next).not.toHaveBeenCalled();
    expect(r.code).toBe(401);
  });

  it("rejects a wrong token", () => {
    const next = vi.fn();
    const r = res();
    requireToken({ token: "secret" })(req({ authorization: "Bearer nope" }), r, next);
    expect(next).not.toHaveBeenCalled();
    expect(r.code).toBe(401);
  });

  it("accepts the token via Bearer or x-canvas-token", () => {
    const a = vi.fn();
    requireToken({ token: "secret" })(req({ authorization: "Bearer secret" }), res(), a);
    expect(a).toHaveBeenCalled();

    const b = vi.fn();
    requireToken({ token: "secret" })(req({ "x-canvas-token": "secret" }), res(), b);
    expect(b).toHaveBeenCalled();

    const c = vi.fn();
    const basic = Buffer.from("canvas:secret").toString("base64");
    requireToken({ token: "secret" })(req({ authorization: `Basic ${basic}` }), res(), c);
    expect(c).toHaveBeenCalled();
  });
});
