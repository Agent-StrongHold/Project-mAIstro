---
id: SPEC-193
title: Slot-aware local inference gateway
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-02
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-094
  - maistro-engine#ADR-002
implements: []
related:
  - maistro-engine#SPEC-194
  - maistro-engine#SPEC-195
  - maistro-engine#ADR-091
contracts:
  - boundary
  - behavioral
tests:
  - apps/conductor-gateway/tests/
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-02
---

# SPEC-193: Slot-aware local inference gateway

## Context

ADR-094 cut pydantic-ai and established that the conductor calls an OpenAI-compatible
gateway directly. For **local inference** (P40 hardware, llama.cpp / ik_llama.cpp),
that gateway needs to be more than a pass-through proxy: it must manage the KV-cache
slot lifecycle of the inference server to make prefix reuse practical and to enable
parallel diverse generation (SPEC-194).

A reference implementation exists as a frozen snapshot in git history — see
`potential-dead-code/code-worth-implementing-from-Conductor/snapshot/gateway/` at
commit `d6603c9^` (removed from the working tree per SPEC-178 / PR #98).
This spec defines the port target, contracts, and acceptance criteria.

## Decision

Ship a standalone FastAPI app at **`apps/conductor-gateway/`** that:

1. Proxies OpenAI-compatible `/v1/chat/completions` to a local llama-server.
2. Manages a **slot pool** (template slot 0 + N worker slots 1…N).
3. Persists per-project **KV cache** to disk with content-hash invalidation.
4. Exposes `/v1/ultra-think` for parallel diverse generation (SPEC-194).
5. Exposes project-lifecycle and introspection endpoints.
6. Emits structured metrics for every request.

When the gateway is absent, the conductor calls llama-server directly at tier 1
(single generation). The gateway is an optional enhancement, not a hard dependency
for the core engine.

## Architecture

```
Conductor Orchestrator
        │ HTTP (OpenAI-compatible)
        ▼
┌─────────────────────────┐
│  conductor-gateway      │  :9090
│  ┌──────────────────┐   │
│  │   SlotManager    │   │
│  │  slot-0: template│   │
│  │  slot-1..N: work │   │
│  └────────┬─────────┘   │
│           │             │
│  ┌────────┴──────────┐  │
│  │  PrefixCacheManager│  │
│  │  hash → .bin + meta│  │
│  └────────┬──────────┘  │
└───────────┼─────────────┘
            │ HTTP
            ▼
    llama-server  :8080
    (ik_llama.cpp or compatible)
```

## API Surface

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Gateway + llama-server liveness |
| `POST` | `/v1/chat/completions` | OpenAI-compatible proxy (tier 1) |
| `POST` | `/v1/ultra-think` | Parallel diverse generation (SPEC-194) |
| `POST` | `/v1/project/load` | Load project context into template slot |
| `POST` | `/v1/project/save` | Persist template KV cache to disk |
| `POST` | `/v1/project/restore` | Restore template KV cache from disk |
| `GET` | `/v1/slots/status` | Pool utilization + per-slot cached prefix lengths |
| `GET` | `/v1/metrics` | Throughput, cache hits, latency histogram |

## Endpoint schemas

### `POST /v1/project/load`
Request: `{"project_id": "...", "layer0_text": "...", "knowledge_context": ""}` (knowledge_context optional)
Response: `{"project_id": "...", "cache_reused": true}`

### `POST /v1/project/save`
Request: `{"project_id": "..."}`
Response: `{"project_id": "...", "save_time_ms": 42.1}`

### `POST /v1/project/restore`
Request: `{"project_id": "..."}`
Response: `{"project_id": "...", "status": "ok"}`
**Note: v1 stub.** The template cache is already in memory after `/load`; an explicit
restore from disk is not yet implemented. This endpoint exists for API completeness and
returns `ok` without performing a slot action.

### `GET /health`
Response (llama-server reachable): `{"gateway": "ok", "inference_engine": "ok"}` — HTTP 200
Response (llama-server unreachable): `{"gateway": "ok", "inference_engine": "unreachable"}` — HTTP 200
The health endpoint **always** returns HTTP 200 if the gateway process itself is alive.
Callers must inspect the `inference_engine` field to detect backend unavailability.
HTTP 503 is returned only if the gateway has not been initialized (lifespan not complete).

### `GET /v1/slots/status`
Response: `{"slots": [{"slot_id": 1, "state": "idle", "task_id": null, "cached_prefix_tokens": 0}], "available_workers": 4}`
Slot states: `"idle"`, `"reserved"`, `"processing"`. Template slot 0 is not included.

### `GET /v1/metrics`
Response: `{"entries": [...]}` — last 100 JSONL rows from the metrics log.
Metrics log rotates at **10 MB** (renamed to `gateway.jsonl.old`; one generation kept).

## Input validation

All endpoints that accept `project_id` or `task_id` validate against these patterns
(implemented in `gateway/validation.py`):

| Field | Pattern | Max length |
|-------|---------|-----------|
| `project_id` | `^[a-zA-Z0-9][a-zA-Z0-9_-]*$` | 64 chars |
| `task_id` | `^[a-zA-Z0-9][a-zA-Z0-9_-]*$` | 128 chars |

Path traversal characters (`..`, `/`, `\`) are explicitly rejected even if they match
the regex. Invalid input returns HTTP 400 with a human-readable detail string.

## Slot contract (invariants)

- **Slot 0 is template-only.** The gateway never routes generation to slot 0.
  `SlotManager.release_worker()` raises `ValueError` if called with slot 0 as a guard.
  Callers cannot override the slot assignment — the gateway assigns slots internally;
  no `id_slot` parameter is exposed in any public request schema.
- **Worker slots are acquired from a pool.** An `asyncio.Queue` of available slot
  IDs blocks callers until a slot is free (bounded by `generation_timeout_seconds`).
- **Template is always restored into a worker before generation.** A worker that
  has not had the template restored still functions (llama-server handles it), but
  loses the prefix-cache speedup. Restore failures are logged at WARNING and treated
  as non-fatal.
- **Workers are always released in a `finally` block**, even on exception, to
  prevent pool starvation.

## Prefix cache contract

Cache key: `SHA-256(layer0_constraints_text + knowledge_context_text)`.

- **Cache hit:** restore from disk into template slot via llama-server `/slots` API.
  No LLM tokens consumed. Returns in `slot_restore_timeout_seconds`.
- **Cache miss:** send prefix to template slot with `cache_prompt=true, max_tokens=0`
  to warm the KV cache without generating output, then save to disk.
- **Invalidation:** explicit call to `PrefixCacheManager.invalidate(project_id)` OR
  whenever the Layer 0 content hash changes on the next `ensure_project_loaded` call.
- **Layout** (under `CONDUCTOR_KV_CACHE_DIR`):
  ```
  projects/{project_id}/template.meta.json   ← hash + token_count + created_at
  metrics/cache_stats.jsonl                  ← hit/miss log
  ```
  The `.bin` files are written by llama-server directly into `kv_cache_dir` via
  `--slot-save-path`; the gateway only owns the metadata sidecar.

## Configuration

All values are `pydantic-settings`-driven with `env_prefix = "CONDUCTOR_"`.

| Setting | Default | Notes |
|---------|---------|-------|
| `llama_server_url` | `http://localhost:8080` | Target inference server |
| `template_slot_id` | `0` | Never used for generation |
| `worker_slot_ids` | `[1,2,3,4]` | Adjust to match `-np` value − 1 |
| `kv_cache_dir` | `./kv-cache` | Must match `--slot-save-path` |
| `tier1_candidates` | `1` | |
| `tier2_candidates` | `3` | |
| `tier3_candidates` | `5` | |
| `default_max_tokens` | `4096` | |
| `generation_timeout_seconds` | `300` | |
| `slot_restore_timeout_seconds` | `30` | |
| `prefix_warm_timeout_seconds` | `120` | |
| `http_client_timeout_seconds` | `600` | Total request timeout for the httpx client |
| `health_check_path` | `/health` | Path appended to `llama_server_url` for liveness check |
| `metrics_log_path` | `./metrics/gateway.jsonl` | |
| `log_format` | `text` | `"text"` for development; `"json"` for structured production logs (`CONDUCTOR_LOG_FORMAT=json`) |

## Per-request telemetry

Every proxied generation records:

```json
{
  "task_id": "...",
  "slot_restore_time_ms": 45.2,
  "prefix_tokens_cached": 1024,
  "suffix_tokens_processed": 312,
  "generation_time_ms": 8400,
  "tokens_per_second": 37.1
}
```

## Reference bundle

Source files (in git history at `d6603c9^`,
path `potential-dead-code/code-worth-implementing-from-Conductor/snapshot/`):

| Snapshot file | Port target |
|---------------|-------------|
| `gateway/slot_manager.py` | `apps/conductor-gateway/gateway/slot_manager.py` |
| `gateway/prefix_cache.py` | `apps/conductor-gateway/gateway/prefix_cache.py` |
| `gateway/ultra_think.py` | `apps/conductor-gateway/gateway/ultra_think.py` (see SPEC-194) |
| `gateway/config.py` | `apps/conductor-gateway/gateway/config.py` |
| `gateway/server.py` | `apps/conductor-gateway/gateway/server.py` |
| `gateway/validation.py` | `apps/conductor-gateway/gateway/validation.py` |
| `tests/test_slot_manager.py` | `apps/conductor-gateway/tests/test_slot_manager.py` |
| `tests/test_prefix_cache.py` | `apps/conductor-gateway/tests/test_prefix_cache.py` |
| `tests/test_ultra_think.py` | `apps/conductor-gateway/tests/test_ultra_think.py` |
| `tests/test_validation.py` | `apps/conductor-gateway/tests/test_validation.py` |

## Acceptance criteria

1. **Slot 0 protection** — `SlotManager.release_worker(0)` raises `ValueError`.
   A `/v1/chat/completions` request never uses slot 0 for generation, confirmed by
   inspecting the slot ID logged in the metrics output.
2. **Prefix cache hit** — a second `/v1/project/load` with identical `layer0_text`
   returns `{"cache_reused": true}` without calling llama-server's
   `/v1/chat/completions` (verified via mock request log).
3. **Prefix cache invalidation** — modifying `layer0_text` on a subsequent
   `/v1/project/load` call triggers a miss; `.meta.json` `content_hash` field changes.
4. **Pool exhaustion** — requesting more workers than `len(worker_slot_ids)` blocks
   until a slot is released; does not deadlock (test with timeout assertion).
5. **Slot always released** — if a generation raises an exception, the slot is
   released and `/v1/slots/status` shows it as `"idle"`.
6. **Health endpoint contract** — `/health` returns HTTP 200 in both cases; the
   `inference_engine` field is `"ok"` when llama-server mock returns 200, and
   `"unreachable"` when it times out or refuses connection.
7. **Input validation** — `project_id` containing `".."` or `"/"` returns HTTP 400
   with a non-empty detail string; a valid alphanumeric id passes through.
8. **Restore non-fatal** — `/v1/project/restore` returns HTTP 200 `{"status": "ok"}`
   even when no cache file exists on disk (v1 stub behavior).
9. All tests pass with a mock llama-server (no real GPU required in CI).
