/**
 * Production perceived-load telemetry (#1420).
 *
 * The dev-console timing logs in `debug.ts` never leave the machine they run
 * on, so field perceived-performance regressions were unmeasurable. This
 * module is the production counterpart: a named browser load metric (LCP,
 * with a documented `load` fallback), the shared API client's request
 * duration/outcome, and correlation with the server's existing
 * `X-Request-ID` — sent to the Conductor's own collector.
 *
 * Operator decisions this encoding assumes (full contract in
 * `packages/hive-conductor/docs/RUM.md`):
 *  - Collection is OFF unless the build set `VITE_RUM_ENABLED=true`; there
 *    is no runtime way for a page to switch it on.
 *  - The collector is same-origin (`VITE_RUM_ENDPOINT`, default
 *    `/v1/rum/events`), so the CSP's `connect-src 'self'` already covers it.
 *  - Sessions are sampled at `VITE_RUM_SAMPLE_RATE` (default 1.0) once per
 *    page load; a sampled-out session buffers and sends nothing.
 *  - Batches are bounded (25 events), failed sends are dropped (never
 *    retried), and three consecutive failures disable the reporter for the
 *    rest of the session. Nothing here can retry unboundedly or buffer
 *    without bound.
 *
 * The prime directive, inherited from every other lib here: telemetry must
 * never break rendering or block a user's request. Every entry point is
 * wrapped so any unexpected failure is a silent no-op for the app.
 */

import {
  MAX_BATCH_EVENTS,
  buildApiRequestEvent,
  buildEnvelope,
  buildWebVitalEvent,
  normalizePageRoute,
  type ApiOutcome,
  type RumEvent,
  sanitizeRequestId,
} from "./rumSchema";

interface RumEnv {
  readonly enabled: boolean;
  readonly sampleRate: number;
  readonly endpoint: string;
  readonly buildId: string;
}

/** Bounds documented in docs/RUM.md; the server enforces matching caps. */
const FLUSH_INTERVAL_MS = 10_000;
const MAX_CONSECUTIVE_FAILURES = 3;
/** Session id: 12 hex chars, regenerated every page load, never persisted. */
const SESSION_ID = randomSessionId();

function randomSessionId(): string {
  try {
    const bytes = new Uint8Array(6);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return Math.floor(Math.random() * 0xffffffffffff).toString(16);
  }
}

/**
 * The Vite-injected env, read defensively. Vite statically replaces these
 * accesses in a real build, but the e2e harnesses bundle shipped pages with
 * plain esbuild (no Vite), where `import.meta.env` is undefined — the module
 * must evaluate there without throwing, reporting "collection off".
 */
const IMPORT_META_ENV: Record<string, string | undefined> =
  (import.meta as { env?: Record<string, string | undefined> }).env ?? {};

function readEnv(): RumEnv {
  const rawRate = IMPORT_META_ENV.VITE_RUM_SAMPLE_RATE;
  const parsedRate = rawRate === undefined ? 1 : Number(rawRate);
  const sampleRate =
    typeof parsedRate === "number" && Number.isFinite(parsedRate)
      ? Math.min(1, Math.max(0, parsedRate))
      : 1;
  return {
    enabled: IMPORT_META_ENV.VITE_RUM_ENABLED === "true",
    sampleRate,
    endpoint: IMPORT_META_ENV.VITE_RUM_ENDPOINT || "/v1/rum/events",
    buildId: (IMPORT_META_ENV.VITE_RUM_BUILD_ID || "dev").slice(0, 64),
  };
}

type Reporter = {
  env: RumEnv;
  buffer: RumEvent[];
  consecutiveFailures: number;
  disabled: boolean;
  timer: number | undefined;
  latestLcpMs: number | null;
  lcpSent: boolean;
  lcpObserver: PerformanceObserver | null;
  loadSent: boolean;
  /** The page route this document navigation started on. Both load metrics
   * describe that navigation, so their route is fixed once at init — not
   * re-read from the mutable location at flush time, where an SPA route
   * change would misattribute the document's own load timing. */
  readonly navigationRoute: string;
};

let reporter: Reporter | null = null;

function currentPageRoute(): string {
  return normalizePageRoute(window.location.pathname, IMPORT_META_ENV.BASE_URL || "/");
}

function nowMs(): number {
  return Date.now();
}

/**
 * Navigation-load timing, in milliseconds from timeOrigin to the `load`
 * event's end. 0 until the load event has actually fired, which is why the
 * reporter keeps trying at each flush and sends only a finalized value.
 */
function navigationLoadMs(): number | null {
  try {
    const nav = performance.getEntriesByType("navigation")[0];
    if (nav && "loadEventEnd" in nav) {
      const value = (nav as PerformanceNavigationTiming).loadEventEnd;
      if (Number.isFinite(value) && value > 0) return value;
    }
  } catch {
    // Performance API unavailable or broken: this metric is simply absent.
  }
  return null;
}

/**
 * LCP via buffered PerformanceObserver; null where unsupported (Firefox).
 * The observer stays active until first input, so candidates can keep
 * arriving; callers must hold the latest candidate and finalize at a
 * lifecycle boundary, never on a timer flush.
 */
function observeLcp(onValue: (ms: number) => void): PerformanceObserver | null {
  try {
    if (typeof PerformanceObserver === "undefined") return null;
    const observer = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1];
      if (last) onValue(last.startTime);
    });
    observer.observe({ type: "largest-contentful-paint", buffered: true } as PerformanceObserverInit);
    return observer;
  } catch {
    // No LCP support (e.g. Firefox): the `load` fallback metric still ships.
    return null;
  }
}

function recordEvent(event: RumEvent | null): void {
  const rep = reporter;
  if (!rep || rep.disabled || !event) return;
  rep.buffer.push(event);
  if (rep.buffer.length >= MAX_BATCH_EVENTS) void flush("batch-full");
}

/**
 * Ship the LCP candidate exactly once, at a lifecycle boundary (first user
 * input or pagehide) — the point at which the browser stops producing LCP
 * candidates and the value is final. Interval flushes deliberately never
 * touch it: clearing the candidate on a timer would emit a premature value
 * and, if a later paint arrived, a second nominal LCP for one navigation.
 */
function finalizeLcp(rep: Reporter): void {
  if (rep.lcpSent || rep.latestLcpMs === null) return;
  const lcpEvent = buildWebVitalEvent({
    name: "LCP",
    value_ms: rep.latestLcpMs,
    route: rep.navigationRoute,
    ts: nowMs(),
  });
  rep.lcpSent = true;
  rep.latestLcpMs = null;
  try {
    rep.lcpObserver?.disconnect();
  } catch {
    // A dead observer must not break the report it finalized.
  }
  if (lcpEvent) rep.buffer.unshift(lcpEvent);
}

async function flush(reason: "interval" | "pagehide" | "batch-full"): Promise<void> {
  const rep = reporter;
  if (!rep || rep.disabled) return;
  // Ship the load metric once: the first flush after the load event fired
  // sends its finalized value. LCP is not handled here — it finalizes only
  // at the first-input/pagehide boundary (see finalizeLcp). Both describe
  // the document navigation, so both carry the route captured at init —
  // never wherever the SPA happens to be navigating at flush time.
  const loadMs = navigationLoadMs();
  if (loadMs !== null && !rep.loadSent) {
    const event = buildWebVitalEvent({
      name: "load",
      value_ms: loadMs,
      route: rep.navigationRoute,
      ts: nowMs(),
    });
    if (event) {
      rep.buffer.unshift(event);
      rep.loadSent = true;
    }
  }
  if (rep.buffer.length === 0) return;
  const batch = rep.buffer.splice(0, MAX_BATCH_EVENTS);
  const envelope = buildEnvelope({
    buildId: rep.env.buildId,
    sessionId: SESSION_ID,
    events: batch,
  });
  if (!envelope) return; // Redaction rejected the whole batch — send nothing.
  const sent = await send(rep, envelope, reason);
  if (!sent) {
    // Dropped, never retried: a failed batch is gone. The breaker below is
    // what stops a dead collector from being fed forever.
    rep.consecutiveFailures += 1;
    if (rep.consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
      rep.disabled = true;
      rep.buffer = [];
      if (rep.timer !== undefined) window.clearInterval(rep.timer);
    }
  } else {
    rep.consecutiveFailures = 0;
  }
}

async function send(
  rep: Reporter,
  envelope: ReturnType<typeof buildEnvelope>,
  reason: "interval" | "pagehide" | "batch-full",
): Promise<boolean> {
  if (!envelope) return false;
  const body = JSON.stringify(envelope);
  try {
    if (reason === "pagehide" && typeof navigator.sendBeacon === "function") {
      // Beacons cannot be checked for delivery; treat queuing as success and
      // lean on the server's caps rather than a follow-up.
      return navigator.sendBeacon(
        rep.env.endpoint,
        new Blob([body], { type: "application/json" }),
      );
    }
    const controller = new AbortController();
    const giveUp = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(rep.env.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        credentials: "same-origin",
        keepalive: true,
        signal: controller.signal,
      });
      // 2xx and the disabled-collector 202 both count as delivered: the
      // collector answered, so the reporter should not churn.
      return response.status >= 200 && response.status < 300;
    } finally {
      clearTimeout(giveUp);
    }
  } catch {
    return false;
  }
}

/**
 * Hook for the shared API client: report one request's duration and
 * outcome. `rawRequestId` must be the response's own `X-Request-ID` header
 * value; it is re-validated here and dropped if it does not match the
 * charset the backend itself enforces.
 */
export function rumApiRequest(fields: {
  method: string;
  path: string;
  status: number;
  outcome: ApiOutcome;
  durationMs: number;
  rawRequestId: string | null;
}): void {
  try {
    const rep = reporter;
    if (!rep || rep.disabled) return;
    recordEvent(
      buildApiRequestEvent({
        method: fields.method,
        rawPath: fields.path,
        status: fields.status,
        outcome: fields.outcome,
        duration_ms: fields.durationMs,
        rawRequestId: fields.rawRequestId,
        ts: nowMs(),
      }),
    );
  } catch {
    // Telemetry must never break the request that fed it.
  }
}

/**
 * `fetch` wrapped with the same measurement the shared client gets (#1420):
 * duration, outcome class and the response's validated `X-Request-ID` are
 * reported as an `api_request` event; the Response (or error) itself is
 * returned/thrown untouched, so callers keep their own semantics. GET-only
 * by contract — the boot-time probes that gate first content (AuthGuard's
 * setup/whoami) are reads; anything else goes through `lib/api.ts`. Lives
 * in `lib/` with the other shared HTTP helpers because that is where the
 * typed-client ratchet expects shared transport code.
 */
export async function instrumentedGet(path: string): Promise<Response> {
  const started = performance.now();
  try {
    const res = await fetch(path, { credentials: "same-origin" });
    rumApiRequest({
      method: "GET",
      path,
      status: res.status,
      outcome: res.ok ? "ok" : "http_error",
      durationMs: performance.now() - started,
      rawRequestId: sanitizeRequestId(res.headers.get("X-Request-ID")),
    });
    return res;
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    rumApiRequest({
      method: "GET",
      path,
      status: 0,
      outcome: timedOut ? "timeout" : "network_error",
      durationMs: performance.now() - started,
      rawRequestId: null,
    });
    throw err;
  }
}

/**
 * Initialize collection for this page load. Called once from `main.tsx`.
 * A no-op unless the build enabled collection AND this session was sampled
 * in — after which nothing can switch it off except the failure breaker.
 */
export function initRum(): void {
  if (reporter) return;
  const env = readEnv();
  if (!env.enabled) return;
  if (env.sampleRate < 1 && Math.random() >= env.sampleRate) return;
  if (typeof window === "undefined") return;

  const rep: Reporter = {
    env,
    buffer: [],
    consecutiveFailures: 0,
    disabled: false,
    timer: undefined,
    latestLcpMs: null,
    lcpSent: false,
    lcpObserver: null,
    loadSent: false,
    navigationRoute: currentPageRoute(),
  };
  reporter = rep;

  rep.lcpObserver = observeLcp((ms) => {
    // LCP candidates keep arriving until the first user input; keep only
    // the latest so the finalized value is the largest paint. Held until
    // the boundary below — never cleared by an interval flush.
    rep.latestLcpMs = ms;
  });

  const onLcpBoundary = () => {
    finalizeLcp(rep);
    void flush("pagehide");
  };
  rep.timer = window.setInterval(() => void flush("interval"), FLUSH_INTERVAL_MS);
  // First input finalizes LCP (the browser stops producing candidates);
  // flush so the final value leaves with the interaction batch.
  window.addEventListener("pointerdown", onLcpBoundary, { once: true });
  window.addEventListener("keydown", onLcpBoundary, { once: true });
  window.addEventListener("pagehide", onLcpBoundary, { once: true });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") onLcpBoundary();
  });
}

/** Test/e2e seam: current pending event count (0 when not collecting). */
export function rumPendingForTests(): number {
  return reporter ? reporter.buffer.length : 0;
}
