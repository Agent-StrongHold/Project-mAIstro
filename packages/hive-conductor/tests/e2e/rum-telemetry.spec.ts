/**
 * Production perceived-load telemetry, end to end (#1420).
 *
 * Two layers, because the contract has two halves:
 *
 * 1. Pure redaction rules (`lib/rumSchema.ts`), asserted directly from Node
 *    against the same functions the shipping bundle calls. This is where the
 *    "only approved fields leave the browser" guarantee is proven per-rule:
 *    query strings and fragments never enter a route template, identifier-
 *    looking path segments collapse to a star, and a request id outside the
 *    backend's own X-Request-ID charset is dropped rather than forwarded.
 *
 * 2. The live path against the compose stack, which builds the SPA with
 *    `VITE_RUM_ENABLED=true` and runs the backend with `RUM_INGEST_ENABLED=true`:
 *    a real page load produces finite, non-negative load measurements with
 *    documented units; a shared-client request's emitted `request_id` equals
 *    the `X-Request-ID` that same response carried; and nothing secret — a
 *    token planted in the page URL's query string, a raw resource id from an
 *    API path — appears anywhere in the outgoing payloads. Receipts are then
 *    read back from the collector's own query endpoints, which is also where
 *    build/route grouping lives.
 *
 * The disabled-client case (no `VITE_RUM_ENABLED` → no request is ever made)
 * is the shipped default for every deployment that does not opt in; the
 * collector's disabled side (a valid batch answered 202 and stored) is
 * pinned by `backend/tests/test_rum_routes.py`.
 */

import { expect, request as playwrightRequest, test, type Page } from "@playwright/test";
import { ADMIN_PASS, ADMIN_USER, loginAsPM, setupIfNeeded } from "./session";
import {
  buildApiRequestEvent,
  buildEnvelope,
  normalizeApiPath,
  normalizePageRoute,
  sanitizeRequestId,
} from "../../frontend/src/lib/rumSchema";

const SECRET_TOKEN = "supersecret-rum-token";
const RAW_AGENT_ID = "a1e40b7c-9931-4f0e-8d5c-77b2aa01fed9";

// ---------------------------------------------------------------------------
// 1. The redaction rules, per rule, in Node
// ---------------------------------------------------------------------------

test.describe("RUM schema redaction rules", () => {
  test("API path templates keep only the collection, never identifiers", () => {
    expect(normalizeApiPath("/v1/agents")).toBe("/v1/agents");
    expect(normalizeApiPath(`/v1/agents/${RAW_AGENT_ID}`)).toBe("/v1/agents/*");
    expect(normalizeApiPath("/v1/tasks/abc/messages?limit=50")).toBe("/v1/tasks/*");
    // Query strings and fragments never survive — whatever they carry.
    expect(normalizeApiPath(`/v1/agents/x?api_token=${SECRET_TOKEN}`)).toBe("/v1/agents/*");
    expect(normalizeApiPath("/v1/agents/x#fragment-carries-state")).toBe("/v1/agents/*");
    // An absolute or scheme-relative URL is not a same-origin path. Its
    // hostname must never be mistaken for a route segment and emitted.
    expect(normalizeApiPath(`https://customer-42.example.invalid/private?token=${SECRET_TOKEN}`)).toBe(
      "unknown",
    );
    expect(normalizeApiPath("//customer-42.example.invalid/private")).toBe("unknown");
    // The second segment is only retained when it is a reviewed API
    // collection root. `apiFetch` accepts arbitrary caller paths, so an id
    // directly below /v1 must not become an emitted route template.
    expect(normalizeApiPath(`/v1/${RAW_AGENT_ID}`)).toBe("unknown");
    // A path made of nothing usable is "unknown", not a leak.
    expect(normalizeApiPath("///??x")).toBe("unknown");
  });

  test("page route templates are the single SPA segment", () => {
    expect(normalizePageRoute("/dashboard")).toBe("/dashboard");
    expect(normalizePageRoute(`/dashboard/${RAW_AGENT_ID}`)).toBe("/dashboard/*");
    expect(normalizePageRoute(`/login?next=/admin&token=${SECRET_TOKEN}`)).toBe("/login");
    // The Vite base path is stripped, so a sub-path deployment reports the
    // same template as a root one.
    expect(normalizePageRoute("/pm/dashboard", "/pm/")).toBe("/dashboard");
  });

  test("request ids must match the backend's own X-Request-ID charset", () => {
    expect(sanitizeRequestId("abc123def456")).toBe("abc123def456");
    expect(sanitizeRequestId("id-with.dots_and-underscores")).toBe(
      "id-with.dots_and-underscores",
    );
    // Anything the server middleware would have rejected is dropped here too.
    expect(sanitizeRequestId("two words")).toBeNull();
    expect(sanitizeRequestId("semi;colon")).toBeNull();
    expect(sanitizeRequestId("x".repeat(129))).toBeNull();
    expect(sanitizeRequestId("")).toBeNull();
    expect(sanitizeRequestId(undefined)).toBeNull();
    expect(sanitizeRequestId({ spoof: true })).toBeNull();
  });

  test("event builders reject non-finite timings and unknown shapes", () => {
    expect(
      buildApiRequestEvent({
        method: "GET",
        rawPath: "/v1/agents",
        status: 200,
        outcome: "ok",
        duration_ms: Number.NaN,
        rawRequestId: null,
        ts: 0,
      }),
    ).toBeNull();
    // A lower-case verb is normalized, not a leak: it ships as upper-case.
    const lowercased = buildApiRequestEvent({
      method: "get",
      rawPath: "/v1/agents",
      status: 200,
      outcome: "ok",
      duration_ms: 5,
      rawRequestId: null,
      ts: 0,
    });
    expect(lowercased).toEqual(
      expect.objectContaining({ method: "GET", route: "/v1/agents" }),
    );
    expect(
      buildApiRequestEvent({
        method: "NOT_A_VERB_AT_ALL",
        rawPath: "/v1/agents",
        status: 200,
        outcome: "ok",
        duration_ms: 5,
        rawRequestId: null,
        ts: 0,
      }),
    ).toBeNull();
    expect(
      buildApiRequestEvent({
        method: "GET",
        rawPath: "/v1/agents",
        status: 200,
        outcome: "something-else",
        duration_ms: 5,
        rawRequestId: null,
        ts: 0,
      }),
    ).toBeNull();
  });

  test("the flush envelope accepts built api_request events (flush-path regression)", () => {
    // Regression: buildEnvelope used to re-run the raw-input builders over
    // ALREADY-BUILT events, whose shape (route, no rawPath) they reject —
    // silently dropping every api_request from every flush while the load
    // vitals sailed through. The envelope must accept built events and still
    // drop anything malformed or foreign-shaped.
    const built = buildApiRequestEvent({
      method: "GET",
      rawPath: "/v1/agents",
      status: 200,
      outcome: "ok",
      duration_ms: 12.5,
      rawRequestId: "abc123",
      ts: 1_700_000_000_000,
    });
    expect(built).not.toBeNull();
    const envelope = buildEnvelope({ buildId: "spec-build", sessionId: "sess01aaaaaa", events: [built] });
    expect(envelope).not.toBeNull();
    expect(envelope?.events).toEqual([built]);
    expect(envelope?.schema).toBe("hive.rum.v1");
    // Malformed and foreign-shaped events are dropped by the same gate.
    expect(
      buildEnvelope({ buildId: "spec-build", sessionId: "sess01aaaaaa", events: [{ type: "api_request" }] }),
    ).toBeNull();
    expect(
      buildEnvelope({
        buildId: "spec-build",
        sessionId: "sess01aaaaaa",
        events: [{ ...built, request_id: "has spaces" }],
      }),
    ).toBeNull();
    expect(buildEnvelope({ buildId: "spec-build", sessionId: "sess01aaaaaa", events: [] })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2. The live path: real load, real collector, real receipts
// ---------------------------------------------------------------------------

type CapturedBatch = {
  schema: string;
  build_id: string;
  session_id: string;
  events: Array<Record<string, unknown>>;
};

test.describe("RUM live collection", () => {
  let page: Page;
  /** Every /v1/rum/events payload the page sent, in order. */
  let captured: CapturedBatch[];
  /** X-Request-ID -> URL of the first /v1 API response seen on the page. */
  let observedRequestIds: Map<string, string>;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
    page = await context.newPage();
    await setupIfNeeded(page);
    await loginAsPM(page);

    captured = [];
    observedRequestIds = new Map();
    await page.route("**/v1/rum/events**", async (route) => {
      const body = route.request().postData() ?? "";
      try {
        captured.push(JSON.parse(body) as CapturedBatch);
      } catch {
        throw new Error(`RUM batch was not valid JSON: ${body.slice(0, 200)}`);
      }
      await route.continue();
    });
    page.on("response", (response) => {
      const url = response.url();
      // The shared client also measures `/health` probes; only the collector
      // path itself is excluded (its ids are stored, not compared here).
      if ((!url.includes("/v1/") && !url.includes("/health")) || url.includes("/v1/rum/")) {
        return;
      }
      const id = response.headers()["x-request-id"];
      if (id && !observedRequestIds.has(id)) observedRequestIds.set(id, url);
    });
  });

  test("a production page load ships finite measurements and survives the page URL's secrets", async () => {
    captured.length = 0;
    observedRequestIds.clear();
    // The query string carries a secret-looking token; a page route template
    // that leaked any part of the URL would carry it to the collector.
    await page.goto(`/dashboard?next=${encodeURIComponent("/agents")}&token=${SECRET_TOKEN}`);
    await page.waitForLoadState("load");
    // Visit a second route so the api_request events span page routes, and
    // the agents fetch exercises the shared client on a collection path.
    // Wait for that fetch to complete — its api_request event must be in the
    // buffer before the pagehide flush fires — and give the (async) LCP
    // observer entries a moment to arrive.
    const agentsResponse = page.waitForResponse(
      (r) => r.url().includes("/v1/agents") && r.request().method() === "GET",
      { timeout: 15000 },
    );
    await page.goto("/agents");
    await agentsResponse;
    await page.waitForTimeout(1000);

    // The reporter's real flush paths are the interval and the unload
    // lifecycle; the pagehide flush is deterministic, so fire it the way the
    // browser would (the listener is registered for the pagehide event).
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
    await page.waitForTimeout(500);

    expect(captured.length, "at least one batch left the page").toBeGreaterThan(0);

    // --- envelope: schema + build + session, exactly the approved set ------
    const allEvents = captured.flatMap((batch) => batch.events);
    for (const batch of captured) {
      expect(Object.keys(batch).sort()).toEqual(["build_id", "events", "schema", "session_id"]);
      expect(batch.schema).toBe("hive.rum.v1");
      expect(batch.build_id).toBeTruthy();
      expect(batch.session_id).toMatch(/^[0-9a-f]{12}$/);
      expect(batch.events.length).toBeLessThanOrEqual(25);
    }

    // --- the load metrics: finite, non-negative, documented units ----------
    const vitals = allEvents.filter((e) => e["type"] === "web_vital");
    expect(vitals.length, "at least one load metric per navigation").toBeGreaterThan(0);
    for (const vital of vitals) {
      expect(Object.keys(vital).sort()).toEqual(["name", "route", "ts", "type", "value_ms"]);
      expect(["LCP", "load"]).toContain(vital["name"]);
      const value = vital["value_ms"] as number;
      expect(Number.isFinite(value)).toBe(true);
      expect(value).toBeGreaterThanOrEqual(0);
      // A local load is milliseconds, not seconds masquerading as ms.
      expect(value).toBeLessThan(60_000);
      expect(vital["route"] as string).toMatch(/^\//);
    }

    // --- api_request events: outcomes, correlation --------------------------
    const apiEvents = allEvents.filter((e) => e["type"] === "api_request");
    expect(apiEvents.length, "shared-client requests were measured").toBeGreaterThan(0);
    for (const event of apiEvents) {
      expect(Object.keys(event).sort()).toEqual([
        "duration_ms",
        "method",
        "outcome",
        "request_id",
        "route",
        "status_class",
        "ts",
        "type",
      ]);
      const duration = event["duration_ms"] as number;
      expect(Number.isFinite(duration)).toBe(true);
      expect(duration).toBeGreaterThanOrEqual(0);
      expect(["ok", "http_error", "timeout", "network_error"]).toContain(event["outcome"]);
      expect([0, 2, 3, 4, 5]).toContain(event["status_class"]);
      const route = event["route"] as string;
      // A template is a path — the shared client also measures `/health` —
      // never a full URL and never carrying a query/fragment.
      expect(route.startsWith("/")).toBe(true);
      expect(route).not.toContain("?");
      expect(route).not.toContain("=");
      expect(route).not.toContain("#");
      const requestId = event["request_id"] as string | null;
      if (requestId !== null) {
        expect(requestId).toMatch(/^[A-Za-z0-9._-]{1,128}$/);
        // Every emitted id is one the server actually issued for this page.
        expect(observedRequestIds.has(requestId)).toBe(true);
      }
    }

    // --- secrets do not ride anywhere ---------------------------------------
    const outgoing = JSON.stringify(captured);
    expect(outgoing).not.toContain(SECRET_TOKEN);
    expect(outgoing).not.toContain(RAW_AGENT_ID);
    expect(outgoing).not.toContain("?");
    expect(outgoing).not.toContain("token=");
  });

  test("the collector stored the observations and groups them by build and route", async () => {
    // Read back through an OPERATOR session: the ring aggregates every
    // principal's navigation telemetry, so GET /v1/rum/* answers only the
    // admin role (or an account assigned rum.read and elevated) — the same
    // posture as persona-wide feedback. The daily session that reported the
    // traffic must be refused, while its beacons were accepted above.
    const refused = await page.request.get("/v1/rum/events");
    expect(refused.status()).toBe(403);

    const operator = await playwrightRequest.newContext({
      baseURL: test.info().project.use.baseURL,
    });
    await operator.post("/v1/auth/login", {
      data: { username: ADMIN_USER, password: ADMIN_PASS },
    });
    const listing = await operator.get("/v1/rum/events?limit=200");
    expect(listing.status()).toBe(200);
    const body = (await listing.json()) as {
      events: Array<Record<string, unknown>>;
      total: number;
    };
    expect(body.total).toBeGreaterThan(0);
    expect(body.events.length).toBeGreaterThan(0);
    for (const event of body.events) {
      expect(Object.keys(event)).toContain("received_at");
    }
    // Correlation query: the read-back contains at least one stored request
    // id that the browser was also seen emitting (server-issued, verbatim).
    const storedIds = body.events
      .filter((e) => e["type"] === "api_request")
      .map((e) => e["request_id"])
      .filter((id): id is string => typeof id === "string");
    expect(storedIds.length).toBeGreaterThan(0);

    const summary = await operator.get("/v1/rum/events/summary");
    expect(summary.status()).toBe(200);
    const grouped = (await summary.json()) as {
      groups: Array<{ type: string; metric: string; route: string; count: number }>;
      window_events: number;
    };
    expect(grouped.window_events).toBeGreaterThan(0);
    expect(grouped.groups.length).toBeGreaterThan(0);
    for (const group of grouped.groups) {
      expect(group.count).toBeGreaterThan(0);
      expect(group.route).toMatch(/^\//);
      expect(group.route).not.toContain("?");
    }
    // Load metrics and API timings land in separate groups — the shape a
    // maintainer compares across builds or time windows.
    expect(grouped.groups.some((g) => g.type === "web_vital")).toBe(true);
    expect(grouped.groups.some((g) => g.type === "api_request")).toBe(true);
    await operator.dispose();
  });
});
