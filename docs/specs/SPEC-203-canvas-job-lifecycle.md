---
id: SPEC-203
title: "Canvas job lifecycle — background runner, queue states, model-listing honesty"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-09
substrate:
  - maistro-engine#ADR-042
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-09
---

# SPEC-203: Canvas Job Lifecycle

## Problem

The canvas generation engine has a correct execution core (`_execute_action`
dispatches to real `_image_client` protocol with proper error wrapping). Two gaps:

1. **No background runner exists.** `start_job` creates `PENDING` jobs; nothing
   advances them without manual `run_job` calls. The "production background runner"
   is imaginary infrastructure.

2. **`list_models` fails silent-empty.** Returns `200 []` whether backend is unwired
   or genuinely empty. Reaches into private `executor._image_client` via `hasattr`.

## Design

### 1. Job lifecycle states

```
PENDING ──claim──▶ RUNNING ──▶ DONE
   │                  │
   │                  └──▶ FAILED ──(retryable, attempts<max)──▶ PENDING
   └──(stuck > lease_ttl)──▶ reclaimed by reaper ──▶ PENDING or FAILED
```

`GenerationJobRecord` gains: `attempts`, `max_attempts=3`, `leased_by`, `lease_expires_at`.

### 2. Background runner (`CanvasJobRunner`)

- **Atomic claim:** `store.claim_next_pending(worker_id, lease_ttl)` — single
  `UPDATE...WHERE status='PENDING'...RETURNING`. No TOCTOU.
- **Executes** via existing `run_job` (unchanged — it is correct).
- **Leases, not locks.** Dead worker → expired lease → reaper reclaims.
- **Reaper:** periodic sweep, moves expired-lease jobs to `PENDING` (if retriable)
  or `FAILED`.
- **Retry bound:** `attempts >= max_attempts` → terminal `FAILED`.

### 3. `start_job` honesty

Fire-and-queue: persists `PENDING`, returns id. Does not promise execution.
Startup check (§5) catches deployments with no runner.

### 4. `list_models` fix

- `_ModelRegistryProtocol` gains `list_image_models()` as first-class method
- Backend not wired → `503` ("image model registry not configured")
- Genuinely empty → `200 []`
- Private-attribute reach deleted

### 5. Startup check

If job-creating routes are mounted but no `CanvasJobRunner` registered → WARNING banner at boot.

## Acceptance criteria

- [ ] `CanvasJobRunner` exists; `PENDING` job reaches `DONE` with no manual `run_job` call
- [ ] `store.claim_next_pending` is atomic: two runners, one job → exactly one claims
- [ ] Dead-worker job reclaimed by reaper; retried or moved to `FAILED`
- [ ] Retry bound: `max_attempts` failures → terminal `FAILED`
- [ ] No docstring references "assumed" external background runner
- [ ] `list_models` returns `503` when unconfigured, `200 []` when empty (both tested)
- [ ] `/models` route calls protocol method, not `executor._image_client`
- [ ] Startup WARNING when job routes mounted without runner
- [ ] `run_job` still works standalone for CLI/test (no regression)
