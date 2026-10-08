/**
 * RUM event schema and redaction helpers (#1420).
 *
 * This module is the single allowlist for what may leave the browser as
 * perceived-load telemetry. It is deliberately pure: no `import.meta.env`,
 * no browser APIs, no side effects — so the e2e suite can import it from
 * Node and assert the redaction rules directly against the same functions
 * the shipping bundle calls.
 *
 * The wire contract (`hive.rum.v1`) and everything a receiver may rely on is
 * documented in `packages/hive-conductor/docs/RUM.md`. The one-line summary:
 * timings, a normalized route template, an outcome class, and — when the
 * server sent one — the already-validated `X-Request-ID`. Nothing else.
 */

/** Wire schema version. Bump on any breaking field change. */
export const RUM_SCHEMA = "hive.rum.v1";

/** Largest number of events in one batch (also the server's ingest cap). */
export const MAX_BATCH_EVENTS = 25;

/** Longest normalized route template sent for any event. */
export const MAX_ROUTE_LENGTH = 80;

const ROUTE_SEGMENT_RE = /^[A-Za-z0-9._-]{1,64}$/;
const PAGE_SEGMENT_RE = /^[a-z0-9-]{1,40}$/;

/** Stable, literal SPA roots. Like API paths, the page location is input: a
 * direct `/customer-id` navigation must not become a telemetry dimension. */
const PAGE_ROUTE_ROOTS = new Set([
  "agents",
  "audit",
  "backlog",
  "chat",
  "cli",
  "containers",
  "credentials",
  "dags",
  "dag-runs",
  "dashboard",
  "decks",
  "design-studio",
  "docs",
  "evolution",
  "knowledge",
  "login",
  "mcp",
  "memory",
  "messages",
  "missions",
  "optimization-inbox",
  "optimizer",
  "profile",
  "quotas",
  "rsi",
  "schedules",
  "settings",
  "setup",
  "skills",
  "topology",
  "work-items",
]);

/**
 * Stable, literal API collection roots mounted by the Conductor.  The shared
 * client accepts caller-supplied paths, so accepting arbitrary second path
 * segments would make `/v1/<customer-or-workspace-id>` a telemetry route.
 * Unknown/future roots intentionally collapse to `unknown` until they are
 * reviewed here; reporting a coarser route is preferable to exporting an id.
 */
const API_COLLECTION_ROOTS = new Set([
  "agents",
  "audit",
  "auth",
  "backlog",
  "canvas",
  "capabilities",
  "chat",
  "cli",
  "containers",
  "credentials",
  "dag-metrics",
  "dag-runs",
  "dags",
  "dashboard",
  "design",
  "eval-judge",
  "evolution",
  "harness",
  "hitl",
  "install",
  "mcp",
  "memory",
  "messages",
  "optimizer",
  "profile",
  "program",
  "projects",
  "providers",
  "quotas",
  "rsi",
  "rum",
  "schedules",
  "settings",
  "setup",
  "setup-checklist",
  "skills",
  "tasks",
  "topology",
  "voice",
  "widgets",
  "work-items",
  "workspaces",
  "ws",
]);
const HTTP_METHOD_RE = /^[A-Z]{3,10}$/;

/**
 * Mirrors `maistro.observability.middleware`'s accepted request-ID charset:
 * 1–128 ASCII letters/digits/dots/underscores/hyphens with at least one
 * letter or digit. A response header failing this is treated as absent —
 * the shared client must never forward an unvalidated header value to the
 * collector (or anywhere else).
 */
const REQUEST_ID_RE = /^[A-Za-z0-9._-]{1,128}$/;

export const WEB_VITAL_NAMES = ["LCP", "load"] as const;
export type WebVitalName = (typeof WEB_VITAL_NAMES)[number];

function isWebVitalName(value: string): value is WebVitalName {
  return (WEB_VITAL_NAMES as readonly string[]).includes(value);
}

export type WebVitalEvent = {
  type: "web_vital";
  name: WebVitalName;
  /** Milliseconds from navigation start (timeOrigin) to the metric boundary. */
  value_ms: number;
  /** Normalized SPA page-route template (e.g. "/dashboard"), never a URL. */
  route: string;
  /** Epoch milliseconds when the event was recorded. */
  ts: number;
};

export type ApiOutcome = "ok" | "http_error" | "timeout" | "network_error";

export type ApiRequestEvent = {
  type: "api_request";
  /** Upper-case HTTP method, e.g. "GET". */
  method: string;
  /** Normalized API path template (e.g. "/v1/agents/*"), never the raw URL. */
  route: string;
  /** First digit of the response status, 0 for transport failure. */
  status_class: 0 | 2 | 3 | 4 | 5;
  outcome: ApiOutcome;
  /** Milliseconds from just before fetch() to body-read/parse or failure. */
  duration_ms: number;
  /** Server `X-Request-ID` from the response, validated; null when absent. */
  request_id: string | null;
  ts: number;
};

export type RumEvent = WebVitalEvent | ApiRequestEvent;

export type RumEnvelope = {
  schema: typeof RUM_SCHEMA;
  /** Build identifier from VITE_RUM_BUILD_ID — how builds are told apart. */
  build_id: string;
  /** Per-page-load random id (not a user identifier; never persisted). */
  session_id: string;
  events: RumEvent[];
};

const UNKNOWN_ROUTE = "unknown";

function stripQueryAndFragment(raw: string): string {
  const q = raw.indexOf("?");
  const h = raw.indexOf("#");
  let end = raw.length;
  if (q !== -1) end = Math.min(end, q);
  if (h !== -1) end = Math.min(end, h);
  return raw.slice(0, end);
}

function isFiniteNonNegative(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

/**
 * Collapse a shared-client API path to a route template safe to emit.
 *
 * For `/v1` requests, only a reviewed, literal collection root survives;
 * everything deeper — raw resource identifiers, names, anything — collapses
 * to a star. An arbitrary second segment is also rejected: the shared client
 * accepts caller-supplied paths, so `/v1/<workspace-id>` must not turn that id
 * into a route template. Query strings and fragments are stripped before any
 * inspection, so a token smuggled into the query never reaches the template.
 */
export function normalizeApiPath(rawPath: string): string {
  // The shared client accepts only same-origin path references. Reject an
  // absolute or scheme-relative URL before splitting: otherwise its hostname
  // would look like an ordinary first path segment and leak as a route.
  if (typeof rawPath !== "string" || !rawPath.startsWith("/") || rawPath.startsWith("//")) {
    return UNKNOWN_ROUTE;
  }
  const path = stripQueryAndFragment(rawPath);
  const segments = path.split("/").filter((s) => s.length > 0);
  if (segments[0] === "v1" && segments.length >= 2) {
    const root = segments[1];
    if (!ROUTE_SEGMENT_RE.test(root) || !API_COLLECTION_ROOTS.has(root)) return UNKNOWN_ROUTE;
    const route = `/v1/${root}${segments.length > 2 ? "/*" : ""}`;
    return route.length <= MAX_ROUTE_LENGTH ? route : UNKNOWN_ROUTE;
  }
  // The health probe is the only non-/v1 shared-client path. Its literals
  // are fixed by the backend, and it has no user-controlled segment.
  if (segments[0] === "health") return segments.length === 1 ? "/health" : "/health/*";
  return UNKNOWN_ROUTE;
}

/**
 * Collapse the SPA location to its page-route template.
 *
 * Every Hive route is a single segment under the router basename
 * (`/dashboard`, `/work-items`), so only the first segment survives; deeper
 * segments collapse to `*`. The basename (Vite `base`, e.g. `/pm`) is
 * removed first so a sub-path deployment reports the same template as a
 * root deployment.
 */
export function normalizePageRoute(rawPathname: string, basename = "/"): string {
  if (typeof rawPathname !== "string") return UNKNOWN_ROUTE;
  let path = stripQueryAndFragment(rawPathname);
  const base = (basename || "/").replace(/\/$/, "");
  if (base && path.startsWith(base)) path = path.slice(base.length) || "/";
  if (!path.startsWith("/")) path = `/${path}`;
  const segments = path.split("/").filter((s) => s.length > 0);
  if (segments.length === 0) return "/";
  const first = segments[0];
  if (!PAGE_SEGMENT_RE.test(first) || !PAGE_ROUTE_ROOTS.has(first)) return UNKNOWN_ROUTE;
  const route = `/${first}${segments.length > 1 ? "/*" : ""}`;
  return route.length <= MAX_ROUTE_LENGTH ? route : UNKNOWN_ROUTE;
}

/** Validate a response `X-Request-ID` down to the backend's own charset. */
export function sanitizeRequestId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (!REQUEST_ID_RE.test(value)) return null;
  if (!/[A-Za-z0-9]/.test(value)) return null;
  return value;
}

function clampMethod(method: unknown): string | null {
  if (typeof method !== "string") return null;
  const upper = method.toUpperCase();
  return HTTP_METHOD_RE.test(upper) ? upper : null;
}

function statusClassOf(status: unknown): 0 | 2 | 3 | 4 | 5 | null {
  if (typeof status !== "number" || !Number.isInteger(status)) return null;
  if (status === 0) return 0;
  if (status >= 200 && status <= 299) return 2;
  if (status >= 300 && status <= 399) return 3;
  if (status >= 400 && status <= 499) return 4;
  if (status >= 500 && status <= 599) return 5;
  return null;
}

/**
 * Build a `web_vital` event from raw observations, or null when the input
 * is not a finite, non-negative timing. This is the only constructor the
 * reporter uses: fields outside the schema cannot survive it.
 */
export function buildWebVitalEvent(fields: Record<string, unknown>): WebVitalEvent | null {
  const name = fields.name;
  if (typeof name !== "string" || !isWebVitalName(name)) return null;
  if (!isFiniteNonNegative(fields.value_ms)) return null;
  if (typeof fields.route !== "string") return null;
  if (typeof fields.ts !== "number" || !Number.isFinite(fields.ts)) return null;
  return {
    type: "web_vital",
    name,
    value_ms: fields.value_ms,
    route: fields.route,
    ts: Math.floor(fields.ts),
  };
}

/**
 * Build an `api_request` event from the shared client's raw observations,
 * or null when the shape is not reportable. `rawRequestId` runs through
 * `sanitizeRequestId`; anything the server did not send — or sent in a
 * charset it would itself have rejected — becomes null, never a fabricated
 * or forwarded value.
 */
export function buildApiRequestEvent(fields: Record<string, unknown>): ApiRequestEvent | null {
  const method = clampMethod(fields.method);
  if (!method) return null;
  if (typeof fields.rawPath !== "string") return null;
  const status_class = statusClassOf(fields.status);
  // NB: `0` (transport failure) is a valid class but falsy — compare to null.
  if (status_class === null) return null;
  const outcome = fields.outcome;
  if (
    outcome !== "ok" &&
    outcome !== "http_error" &&
    outcome !== "timeout" &&
    outcome !== "network_error"
  ) {
    return null;
  }
  if (!isFiniteNonNegative(fields.duration_ms)) return null;
  if (typeof fields.ts !== "number" || !Number.isFinite(fields.ts)) return null;
  return {
    type: "api_request",
    method,
    route: normalizeApiPath(fields.rawPath),
    status_class,
    outcome,
    duration_ms: fields.duration_ms,
    request_id: sanitizeRequestId(fields.rawRequestId),
    ts: Math.floor(fields.ts),
  };
}

/**
 * Validate an already-built event. `buildEnvelope` runs this over everything
 * it is about to serialize: it is the last gate before the network, so a
 * malformed or foreign-shaped object is dropped here rather than sent. (The
 * raw-input builders above are for constructing events; re-running them on
 * built events would wrongly demand pre-normalization inputs like `rawPath`.)
 */
function isBuiltRumEvent(event: Record<string, unknown>): event is RumEvent {
  if (event["type"] === "web_vital") {
    return (
      typeof event["name"] === "string" &&
      isWebVitalName(event["name"]) &&
      isFiniteNonNegative(event["value_ms"]) &&
      typeof event["route"] === "string" &&
      event["route"].length <= MAX_ROUTE_LENGTH &&
      typeof event["ts"] === "number" &&
      Number.isFinite(event["ts"])
    );
  }
  if (event["type"] === "api_request") {
    const outcome = event["outcome"];
    return (
      typeof event["method"] === "string" &&
      HTTP_METHOD_RE.test(event["method"]) &&
      typeof event["route"] === "string" &&
      event["route"].length <= MAX_ROUTE_LENGTH &&
      typeof event["status_class"] === "number" &&
      [0, 2, 3, 4, 5].includes(event["status_class"]) &&
      (outcome === "ok" ||
        outcome === "http_error" ||
        outcome === "timeout" ||
        outcome === "network_error") &&
      isFiniteNonNegative(event["duration_ms"]) &&
      (event["request_id"] === null || typeof sanitizeRequestId(event["request_id"]) === "string") &&
      typeof event["ts"] === "number" &&
      Number.isFinite(event["ts"])
    );
  }
  return false;
}

/**
 * Strip an envelope down to the approved wire shape. Applied as the last
 * step before serialization so a caller cannot widen the payload by passing
 * extra properties — anything unknown is dropped here, not merely ignored
 * by the receiver.
 */
export function buildEnvelope(fields: {
  buildId: unknown;
  sessionId: unknown;
  events: unknown;
}): RumEnvelope | null {
  if (typeof fields.buildId !== "string" || fields.buildId.length === 0) return null;
  if (fields.buildId.length > 64 || !ROUTE_SEGMENT_RE.test(fields.buildId)) return null;
  if (typeof fields.sessionId !== "string" || !ROUTE_SEGMENT_RE.test(fields.sessionId)) {
    return null;
  }
  if (!Array.isArray(fields.events) || fields.events.length === 0) return null;
  if (fields.events.length > MAX_BATCH_EVENTS) return null;
  const events: RumEvent[] = [];
  for (const event of fields.events) {
    if (!event || typeof event !== "object") continue;
    const record = event as Record<string, unknown>;
    if (isBuiltRumEvent(record)) events.push(record);
  }
  if (events.length === 0) return null;
  return {
    schema: RUM_SCHEMA,
    build_id: fields.buildId,
    session_id: fields.sessionId,
    events,
  };
}
