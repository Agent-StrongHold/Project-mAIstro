# Production perceived-load telemetry (RUM) — `hive.rum.v1`

Issue #1420: until now, every timing the frontend measured (`performance.now()`
in `lib/api.ts`, the `debugApi` console logs) existed only in a developer's
console. Field perceived-performance regressions were unmeasurable. This is
the production measurement path: small, self-hosted, off by default, and
bounded in every dimension.

The audit's original local numbers (TTFB 5 ms, FCP 68 ms at `93fedc8b`) are
provenance for the *problem*, not a field-performance SLO and not a CI timing
threshold. Nothing here introduces one.

## The decisions, stated (the part #1420 requires to be explicit)

| Decision | Value |
|---|---|
| Receiving collector | The Hive Conductor backend itself, same origin as the SPA: `POST /v1/rum/events`. No third-party vendor. |
| Who operates it | The instance maintainer — the person who runs the Conductor. Ingest accepts any authenticated session (every browser must be able to report); the read-back/summary endpoints additionally require the `rum.read` scope (admin role, or an account assigned `rum.read` and task-elevated) — the ring is an instance-wide aggregate of every principal's navigation telemetry, the same operator-only posture as persona-wide feedback. |
| Where observations are retrieved | `GET /v1/rum/events?limit=N` (raw ring, newest last) and `GET /v1/rum/events/summary` (grouped aggregation with percentiles). |
| Enable/disable | Two independent switches, both default **off**: the SPA collects only when its build set `VITE_RUM_ENABLED=true`; the backend stores only when `RUM_INGEST_ENABLED=true`. Either side alone produces nothing — an enabled client facing a disabled collector gets a bounded `202` and discards. There is no runtime way for a page to switch collection on. |
| Sampling | Per page-load session, Bernoulli at `VITE_RUM_SAMPLE_RATE` (default `1.0`, clamped to `[0,1]`). A sampled-out session buffers nothing and sends nothing. The server does no further sampling. |
| Batch/flush limits | Buffer flushes at 10 s intervals, when 25 events accumulate, and on the `pagehide`/hidden lifecycle (beacon). One request carries at most 25 events; the server refuses more (422). The server also refuses a raw body over 64 KiB (413) before parsing it, so the bound holds even for a client that pads unknown fields (`extra="ignore"` cannot bound bytes). |
| Retry policy | None. A failed send is dropped, never retried. Three consecutive failures disable the reporter for the rest of the session and clear the buffer. Bounded by construction. |
| Retention / deletion | In-memory ring bounded by `RUM_MAX_EVENTS` (default 500, clamped to `[50, 10000]`), oldest evicted first. Nothing is written to disk; a restart is the deletion policy. |
| Build/route identification | `build_id` comes from `VITE_RUM_BUILD_ID` at build time (CI should stamp the short commit sha); routes are normalized templates (below), never URLs. |

## What is measured — boundaries, units, lifecycle, fallbacks

| Metric | Start boundary | End boundary | Unit | Lifecycle | Fallback |
|---|---|---|---|---|---|
| `web_vital` / `LCP` | Navigation start (`performance.timeOrigin`) | Render time of the largest contentful element, as of the first flush after candidates are observed (LCP finalizes at first user input or pagehide, whichever comes first) | ms (fractional), one event per navigation | Buffered `PerformanceObserver({type:"largest-contentful-paint"})` | None — browsers without LCP support (e.g. Firefox) simply omit it |
| `web_vital` / `load` | Navigation start | `PerformanceNavigationTiming.loadEventEnd` | ms, once per page load | Sent on the first flush after the `load` event | If the Performance API is unavailable, the metric is absent; this is the documented equivalent that every browser reports |
| `api_request` | Immediately before the shared client's `fetch()` (`lib/api.ts`) | After the response body is read (headers → body, matching the client's 30 s timeout window) or at the transport failure | ms (fractional), one event per request through the shared client | Emitted per call; batched like everything else | Transport failures are `outcome: "timeout"` / `"network_error"` with `status_class: 0` and **no** `request_id` — none is fabricated |

The two raw-fetch paths (chat streaming, dashboard assistant) deliberately keep
their own fetch budgets and are out of scope (#1420): the shared client is the
measured surface.

## The schema (`hive.rum.v1`)

Envelope:

```json
{
  "schema": "hive.rum.v1",
  "build_id": "<short build identifier, [A-Za-z0-9._-]{1,64}>",
  "session_id": "<12 hex chars, random per page load; kept only in the collector's in-memory ring>",
  "events": [ { ... }, ... ]
}
```

`web_vital` event — exactly these fields:

| Field | Type | Meaning |
|---|---|---|
| `type` | `"web_vital"` | discriminator |
| `name` | `"LCP" \| "load"` | which load metric |
| `value_ms` | finite float ≥ 0 | the timing, in milliseconds |
| `route` | string ≤ 80 chars | normalized page-route template, e.g. `/dashboard` |
| `ts` | finite epoch ms ≥ 0 | when it was recorded; the server refuses NaN/Infinity/negative (Python's JSON parser would otherwise accept them) |

`api_request` event — exactly these fields:

| Field | Type | Meaning |
|---|---|---|
| `type` | `"api_request"` | discriminator |
| `method` | upper-case verb | e.g. `GET` |
| `route` | string ≤ 80 chars | normalized API path template, e.g. `/v1/agents/*` |
| `status_class` | `0 \| 2 \| 3 \| 4 \| 5` | first status digit; `0` = transport failure |
| `outcome` | `ok \| http_error \| timeout \| network_error` | outcome class |
| `duration_ms` | finite float ≥ 0 | request duration in ms |
| `request_id` | string or null | the response's `X-Request-ID`, re-validated client-side against the backend middleware's own charset (`[A-Za-z0-9._-]{1,128}`, ≥1 alphanumeric); null when the server sent none |
| `ts` | finite epoch ms ≥ 0 | when it was recorded; same refusal rule as the web-vital `ts` |

The server store adds the envelope's `build_id` and `session_id` to every
stored observation (re-validated against the same charsets the route
enforces), plus one server-clock field on receipt (`received_at`) for
latency-of-delivery debugging. Those are the only fields that are not
client-sent event fields. Retaining the identifiers is what lets the raw
read-back and the summary distinguish observations while several builds
share the ring.

### Route templates

`normalizeApiPath` (client) accepts only a same-origin, single-slash path.
For `/v1` it retains only a reviewed literal API collection root and collapses
everything deeper to `*`: `/v1/tasks/<id>/messages` → `/v1/tasks/*`. An
arbitrary second segment such as `/v1/<workspace-id>` is `unknown`, not a route
label; new API roots must be explicitly reviewed in the client allowlist.
Absolute and scheme-relative URLs are likewise `unknown` rather than allowing
a hostname to become a route segment. Query strings and fragments are stripped
before any inspection. `normalizePageRoute` does the same for the SPA location
after stripping the Vite base path — every Hive route is one segment, so
`/dashboard` stays `/dashboard` and anything deeper becomes `/dashboard/*`.
A segment that is not plain path text yields `unknown`.

### What must never leave the browser (and cannot)

The reporter constructs events exclusively through `lib/rumSchema.ts`, whose
builders copy the approved fields and nothing else. Request/response bodies,
prompts, credentials, cookies, headers other than the validated correlation
id, raw error objects, user/workspace names or ids, URL query strings,
fragments, and raw resource identifiers have no field to land in. The e2e spec
(`rum-telemetry.spec.ts`) drives a page whose URL carries a planted token and
asserts it appears nowhere in any outgoing payload; the backend repeats the
defense independently (`routes/rum.py` refuses route templates outside the
path charset and request ids outside the `X-Request-ID` charset, and the store
projects each event onto approved fields), so a client that skipped its own
redaction still cannot widen what is stored. The dev-only `debugApi(..., extra)`
arguments are console-only and are not forwarded anywhere.

## Correlation

The backend's `RequestIDMiddleware` already stamped `X-Request-ID` on every
response and log line and exposes it through CORS (`expose_headers`). The
reporter reads that header from each shared-client response, re-validates it
against the same charset the middleware enforces, and emits it verbatim on the
event. A maintainer joins a slow `api_request` event to the server's log lines
by that id. A request that never got a response (timeout, network failure)
carries `request_id: null` — there is nothing to fabricate. The collector's
own responses carry the header too, so even the ingest call can be correlated.

## Retention, bounds, and failure behavior

- Buffer ≤ 25 events before a flush is forced; a failed batch is dropped.
- One ingest request ≤ 25 events and each field is length-capped, so a
  request is bounded at a few tens of kilobytes regardless of the client.
  The route enforces this twice: per-field caps in the schema, and a 64 KiB
  cap on the raw body — enforced before JSON parsing, while enabled or not.
- Server ring ≤ `RUM_MAX_EVENTS` events; oldest evicted; nothing on disk.
- Collector down or rejecting: the reporter counts the failure, drops the
  batch, and after 3 consecutive failures turns itself off for the session.
  Rendering, the user's requests, and error handling are untouched — every
  reporter entry point is a guarded no-op on any internal error.
- Unsupported performance APIs: the affected metric is absent; the rest ships.

## Smoke procedure (repeatable)

```bash
cd packages/hive-conductor

# 1. Build the SPA with collection explicitly configured.
#    (In CI the compose build below does exactly this via build args.)
docker compose -f docker-compose.test.yml up --build -d hive
#    equivalent ad hoc build:
#    cd frontend && VITE_RUM_ENABLED=true VITE_RUM_BUILD_ID=<sha> npm run build

# 2. Drive a real browser through a load + a shared-client request.
docker compose -f docker-compose.test.yml run --rm e2e-tests \
  npx playwright test --config=tests/e2e/playwright.config.ts rum-telemetry.spec.ts

# 3. Read the receipts (an operator session — the admin account, or one
#    assigned the rum.read scope and elevated; from the host):
curl -s localhost:8101/v1/rum/events/summary   # grouped by metric/route/outcome
#    (login first: POST /v1/auth/login, keep the session cookie)
#    On a machine whose 8101 is already bound by another stack, run the same
#    harness with the optional port override —
#    `docker compose -f docker-compose.test.yml -f docker-compose.e2e-port.yml ...`
#    — which republishes the service on 18101, and read localhost:18101.
```

The spec's own assertions are the receipt evidence: finite non-negative
values at the endpoint, stored observations read back, and build/route
grouping — no console.log, no dev server, no synthetic number.

### Comparing a load metric across builds or time windows

Stamp `VITE_RUM_BUILD_ID=<short sha>` per build. `GET /v1/rum/events/summary`
groups `count / min / p50 / p95 / max` by `(build_id, type, metric, route,
outcome, status_class)`, so builds A and B resident in the ring at the same
time land in separate rows. Percentiles are nearest-rank: the p-value reported
is the smallest observed value at or above that fraction of the group
(`ceil(p·n) - 1`, 0-indexed) — for 20 samples, p95 is the 19th ordered value,
not the maximum, and an even-sized p50 is the lower middle.
`window_events` reports the retained window the
percentiles were computed over (the ring is a trailing window, not history).
To compare build A against build B, ingest A's traffic and read its summary
rows, then let B's traffic flow and diff the rows sharing A's build ids —
no manual note-taking against an unlabelled aggregate is required. For
longitudinal analysis beyond the ring, an operator can poll the summary (or
raw `GET /v1/rum/events`) into their own log aggregation — the schema is
stable and versioned precisely so that stays possible.

## Files

| File | Role |
|---|---|
| `frontend/src/lib/rumSchema.ts` | Pure schema + redaction (Node-importable, unit-asserted from the e2e spec) |
| `frontend/src/lib/rum.ts` | Reporter: sampling, buffer, flush, LCP/load observers, breaker |
| `frontend/src/lib/api.ts` | Emits `api_request` events; reads + re-validates `X-Request-ID` |
| `backend/routes/rum.py` | Ingest/read/summary endpoints; server-side schema enforcement |
| `backend/services/rum_store.py` | Bounded ring, field projection, aggregation |
| `backend/tests/test_rum_routes.py` | The collector contract |
| `tests/e2e/rum-telemetry.spec.ts` | Redaction rules + live path against the compose stack |
