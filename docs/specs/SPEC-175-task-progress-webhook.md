---
id: SPEC-175
title: Task progress webhook (conductor-router compatibility)
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-05-13
accepted: 2026-05-13
implemented: 2026-05-13
substrate:
  - maistro-engine#ADR-002
  - maistro-engine#ADR-032
implements: []
related:
  - maistro-engine#ADR-018
  - maistro-engine#SPEC-178
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/tasks/test_progress_webhook.py
ac-modules:
  AC-1: maistro.tasks.runner
  AC-2: maistro.tasks.progress_webhook
  AC-3: maistro.tasks.progress_webhook
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Accepted
    date: 2026-05-13
  - status: AC Defined
    date: 2026-05-13
---

# SPEC-175: Task progress webhook

## Context

`Project_mAIstro` shipped a `ProgressReporter` that POSTed JSON task snapshots to a **conductor-router** dashboard (`/v1/conductor/progress`). `maistro-engine` already exposes task state via the in-process queue and HTTP `GET /tasks`, but operators who still run a separate router UI need the same outbound signal without blocking task execution.

## Decision

Port the behavior into **`maistro-core`** as an optional, injectable **`ProgressWebhookNotifier`**:

- Configuration via **`Settings`** on the server (`task_progress_webhook_url`, `task_progress_webhook_api_key`).
- When the URL is **empty**, the feature is **off** (zero HTTP traffic).
- When enabled, the **`TaskRunner`** sends a JSON body **compatible** with the legacy reporter (same top-level keys) after meaningful lifecycle transitions.
- Failures (network, 5xx, timeout) are **logged at debug** and **never** fail the task pipeline (same contract as source `progress.py`).

### Out of scope

- Inbound dashboard routes inside `maistro-server` (router remains external).
- Retries, backoff, or dead-letter queues (follow-up spec if needed).
- Persisted delivery guarantees.

## Interface (spec)

### Environment / settings

| Variable | Type | Default | Semantics |
|----------|------|---------|------------|
| `TASK_PROGRESS_WEBHOOK_URL` | string | `""` | Full URL for `POST` (include path, e.g. `http://localhost:8100/v1/conductor/progress`). Empty disables notifier. |
| `TASK_PROGRESS_WEBHOOK_API_KEY` | string | `""` | Optional `Authorization: Bearer …` header. |

### HTTP contract

- **Method:** `POST`
- **Headers:** `Authorization: Bearer <key>` if key non-empty; `Content-Type: application/json`
- **Timeout:** 5 seconds (aligns with legacy `httpx.AsyncClient(timeout=5)`)
- **Body (JSON):** see boundary model below.

### Python surface

- `maistro.tasks.progress_webhook.ConductorProgressPayload` — Pydantic model for the POST body.
- `maistro.tasks.progress_webhook.ProgressWebhookNotifier` — async `notify(payload)` and `aclose()`.
- `maistro.tasks.progress_webhook.payload_from_task(task: TaskResponse) -> ConductorProgressPayload`
- `TaskRunner(..., progress_webhook: ProgressWebhookNotifier | None = None)` — when set, runner invokes notifier at defined lifecycle points (awaited, bounded by client timeout).

## Acceptance Criteria

- **AC-1**: When `TASK_PROGRESS_WEBHOOK_URL` is unset or empty, no outbound HTTP requests are made for progress mirroring.
- **AC-2**: When `TASK_PROGRESS_WEBHOOK_URL` points to a reachable HTTP server and a task transitions through planning and coding, the server receives at least one POST whose JSON includes `task_id`, `status`, `current_step`, `steps_total`, `steps_completed`, `details`, and `error` fields.
- **AC-3**: When `TASK_PROGRESS_WEBHOOK_URL` points to a blackhole or returns 500, the task still completes successfully and no exception propagates from the webhook layer.

### BDD — feature: optional progress webhook

**Feature:** Operators can mirror task lifecycle to an external HTTP endpoint.

```gherkin
@AC-1
Scenario: Webhook disabled by default
  Given TASK_PROGRESS_WEBHOOK_URL is unset or empty
  When tasks run through TaskRunner
  Then no outbound HTTP requests are made for progress mirroring

@AC-2
Scenario: Webhook emits compatible JSON when enabled
  Given TASK_PROGRESS_WEBHOOK_URL points to a reachable HTTP server
  And a task transitions through planning and coding
  When the runner updates status and progress
  Then the server receives at least one POST whose JSON includes task_id, status, current_step, steps_total, steps_completed, details, and error fields

@AC-3
Scenario: Webhook failure does not fail the task
  Given TASK_PROGRESS_WEBHOOK_URL points to a blackhole or returns 500
  When a task completes successfully in Maistro
  Then the task still ends in status completed
  And Maistro does not raise from the webhook layer
```

### Behavioral contracts (ADR-032)

| ID | Pre-condition | Post-condition | Invariant |
|----|---------------|----------------|-----------|
| BC-175-1 | `TASK_PROGRESS_WEBHOOK_URL` is empty | No HTTP client is used for progress mirroring | Task queue semantics unchanged vs pre-SPEC-175 |
| BC-175-2 | URL non-empty, peer accepts POST | At least one POST per hooked transition for a long-running task | Payload validates as `ConductorProgressPayload` |
| BC-175-3 | Peer hangs or resets connection | Task terminal state matches executor outcome | Notifier logs and returns without propagating exception to executor |

## Contracts (boundary)

### JSON body (`ConductorProgressPayload`)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `task_id` | string | yes | Maistro task id |
| `filename` | string | no | Legacy field; default `""` |
| `status` | string | yes | Lowercase `TaskStatus` value |
| `current_step` | string | no | Maps from `TaskProgress.current` |
| `steps_total` | integer | no | Maps from `TaskProgress.subtasks` |
| `steps_completed` | integer | no | Maps from `TaskProgress.completed` |
| `details` | object | no | Default `{}` |
| `error` | string or null | no | From `TaskResult.error` when present |

Invalid synthetic JSON must fail `ConductorProgressPayload.model_validate` with `ValidationError`.

## Test plan

| ID | Scope | Kind | Asserts |
|----|-------|------|---------|
| T-175-1 | unit | boundary | Valid / invalid `ConductorProgressPayload` |
| T-175-2 | unit | behavioral | `ProgressWebhookNotifier` POSTs expected JSON (httpx `MockTransport`) |
| T-175-3 | unit | behavioral | notifier swallows transport errors |
| T-175-4 | integration | behavioral | `TaskRunner` with mock notifier receives calls across a mocked executor path (no real LLM) |

**E2E (deferred):** Full stack POST to a containerized mock router is not required for SPEC-175 closure; track under `docs/audit/TESTING-AUDIT-2026-02-20.md` (historical) or a fresh CI compose-profile spec if CI gains one.

## Implementation order

1. This spec (SPEC-175) merged or accepted on branch.
2. Failing tests T-175-1…T-175-4 (minimal stubs acceptable first).
3. `ProgressWebhookNotifier` + payload mapper + `TaskRunner` hooks.
4. `maistro-server` wiring from `Settings` + lifespan `aclose`.
5. Archive superseded `progress.py` under `potential-dead-code/` per ADR-002.

## Quality gates (post-implementation)

| Tool | Result (2026-05-13) |
|------|---------------------|
| `uv run pytest packages/maistro-core/tests/tasks/test_progress_webhook.py` | 5 passed |
| `uv run ruff check` (touched paths) | clean (import order auto-fixed in `main.py`) |
| `uv run mypy` (touched modules) | clean |
| `uvx bandit -r packages/maistro-core/src/maistro/tasks/progress_webhook.py` | no findings |
| `uvx vulture … --min-confidence 80` | no findings |
| pylint | not wired in this workspace (ruff-first per `docs/quality-gates.md`); run ad hoc if needed |

**Note:** Running `pytest` across `maistro-core` and `maistro-server` test trees in one invocation can hit `ImportPathMismatchError` on duplicate `tests.conftest` module names; run per package tree in CI (existing pattern).

## Source references

- `potential-dead-code/code-worth-implementing-from-Project-mAIstro/conductor-orchestrator/progress.py` — original `ProgressReporter` (verbatim reference; superseded implementation in `packages/maistro-core`).

## Clarifications (resolved for v1)

- **URL shape:** full URL including path (operators copy the same value they used for `router_url` + path in legacy code).
- **Payload compatibility:** keep legacy key names so existing conductor-router builds accept the body without change.
