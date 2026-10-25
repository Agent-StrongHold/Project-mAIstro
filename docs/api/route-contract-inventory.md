# API route-contract inventory — success-shaped no-op elimination (#389)

Parent initiative: #450. Machine-checked half: `quality/api-route-contracts.json`,
enforced by `scripts/check-api-route-contracts.py` in CI. This page names, for
every shipped route the audit found answering success/empty/hard-coded data
without performing the implied operation, its **intended contract**, the
**canonical durable owner** it now implements against (or its explicit
unsupported status), and how the five answer states stay distinct.

## The distinctness rule

Every state-touching or query surface in this inventory separates five answers:

| State          | Wire shape                                                      |
| -------------- | --------------------------------------------------------------- |
| Empty-valid    | `200` with an empty collection / zero counts **from the owner** |
| Unavailable    | `503` naming the dependency that could not be reached           |
| Unimplemented  | `501` with a detail that says so (and what to use instead)      |
| Failed         | `4xx`/`5xx` for the specific failure (conflict, invalid, ...)   |
| Unauthorized   | `401`/`403` from the auth layer, before the handler runs        |

A `200` is only ever sent for an operation that actually happened or a query
the owner actually answered.

## Settings (`routes/settings.py`, prefix `/v1/settings`)

| Route              | Before (#389 audit)                    | Now                                                                                                                                 |
| ------------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /reload`     | `{"status": "reloaded"}` — nothing reloaded | Drops the settings cache and re-reads `services.settings_store`; returns the fresh record (revision included). Store read failure → `503`. Owner: `services.settings_store`. |
| `GET /audit`       | `return []` forever                    | The settings-change trail (`settings_update` / `settings_patch` / `settings_reload` actions), newest first, from the one durable audit log `GET /v1/audit` serves (read through the shared `routes.audit.audit_entries_view`). Empty = no settings write recorded. Owner: `routes.audit.audit_entries_view` (core store first, hive dict fallback). |
| `GET /quotas`      | `{"providers": []}` forever            | Delegates to the LiteLLM-backed provider aggregation behind `GET /v1/quotas/providers` — same envelope, one owner. Owner: `services.provider_usage.provider_panel` (a service module, so this route imports no router file). |
| `GET/PUT/DELETE /volatile` | real, but unlabelled           | Marked **Preview** in the OpenAPI summary + description: deliberately non-durable overlay values, never written to the record. |

## Schedules (`routes/schedules.py`, prefix `/v1/schedules`)

| Route          | Before            | Now                                                                                                                                                                                                         |
| -------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /history` | `return []` forever | Fire receipts from the durable audit log (`schedule_fire` occurrence receipts and `schedule_run` outcomes — run ids, refusals with `detail.error`), restricted to schedules in Workspaces the caller is authorized to see, newest first, `limit`-capped. Empty = no fire recorded; foreign-Workspace entries are absent, not an error. Owner: `routes.audit.audit_entries_view` + `stores.schedules`. |

## Memory (`routes/memory.py`, prefix `/v1/memory`)

| Route                              | Before                                                              | Now                                                                                                                                                                          |
| ---------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /namespaces`                  | Hard-coded seed `[{name: "default", entry_count: 1, size_bytes: 1024}]` | Derived from the authenticated principal's own durable entries: real namespace names, real entry counts, real byte sizes, sorted. Empty = no entries. Owner: `stores.memory_entries` (owned view). |
| `POST /entries/{id}/contradict`    | Checked existence, then `{"status": "contradiction_registered"}` — nothing stored | A real state change: increments the entry's durable `contradictions` count (new field on `MemoryEntry`), returns the updated entry. `404` keeps its one answer for missing/foreign. Owner: `stores.memory_entries` (owned view). |

## Quota panel (`routes/quotas.py`, prefix `/v1/quotas`)

| Route             | Before                                                             | Now                                                                                                                                                                                                        |
| ----------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /providers`  | `request_count` initialized to 0 and never incremented; any LiteLLM error → `200 []` | Envelope answer: `ok` / `no_data` / `unavailable` (unconfigured) / `error` (unreachable) are distinct. `request_count` aggregates each model's reported counts (`num_requests`, or `usage.api_requests`); `None` when no source reports one. Owner: LiteLLM proxy. |
| `GET /outcomes`   | Hard-coded zeroed structure no event could change                  | Envelope answer from the canonical outcome store (`services.feedback_service`-bound; the engine bridge points it at the durable container store) for the last 7 days: `ok` measured, `no_data` genuinely empty, `error` on store failure. Owner: maistro outcome store. |
| `GET /models`     | Any LiteLLM error → `200 []`                                       | Envelope answer: `ok` / `no_data` / `unavailable` / `error` distinct; invented neutral tier/quality/speed defaults are `None`. Owner: LiteLLM proxy `/model/info`.                                                                        |

## Explicitly unsupported (`501`)

Operations that shipped canned success with nothing behind them now refuse
honestly. `501` is the distinct "unimplemented" answer; the detail names the
wired alternative where one exists.

| Route                          | Before                                                   | Now                        |
| ------------------------------ | -------------------------------------------------------- | -------------------------- |
| `POST /v1/containers/build`    | `{"status": "building", "log": "Building..."}`           | `501` — no build started.  |
| `POST /v1/containers/suggest`  | Hard-coded stock Dockerfile for any description          | `501`.                     |
| `POST /v1/mcp/servers/{id}/scan` | `{"findings": [], "status": "clean"}` — nothing scanned | `404` unknown server; `501` real server. |
| `POST /v1/mcp/discover`        | `{"tools": [], "status": "scanning"}`                    | `501`, points at `POST /v1/mcp/test`. |
| `GET /v1/rsi/models`           | Baked-in model catalog that drifted from the gateway     | `501`, points at `GET /v1/quotas/models`. |

## CI enforcement

`scripts/check-api-route-contracts.py` (wired into `.github/workflows/ci.yml`)
AST-scans every router handler in `packages/hive-conductor/backend/routes/` and
refuses any handler whose every `return` is a pure-constant literal and whose
body performs no call except `HTTPException` — the shape of a canned answer.
It also refuses inventory rot: every entry in
`quality/api-route-contracts.json` must resolve to a live handler. A canned
handler can only ship by registering a `temporary` disposition with a tracking
issue and an unexpired review date.

## Proof

Contract tests: `packages/hive-conductor/backend/tests/test_noop_route_contracts.py`
(state-change and seeded-non-empty proofs for the implemented routes, `501`
proofs for the unsupported set, OpenAPI preview/unsupported marking, gate
self-check), plus the updated `test_memory_routes.py` and `test_quotas.py`.
