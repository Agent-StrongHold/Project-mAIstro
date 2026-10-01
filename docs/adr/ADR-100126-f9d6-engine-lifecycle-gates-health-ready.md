---
id: ADR-100126-f9d6
title: "Engine lifecycle state gates /health/ready with a 503; liveness stays 200"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-10-01
accepted: 2026-10-01
substrate:
  - maistro-engine#ADR-096
implements: []
related:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-097
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_engine_startup_atomicity.py
  - packages/hive-conductor/backend/tests/test_engine_service.py
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-01
  - status: Accepted
    date: 2026-10-01
---

# ADR-100126-f9d6: Engine lifecycle state gates /health/ready with a 503; liveness stays 200

## Context

#1181 made `EngineService.start()` atomic: a required-step failure unwinds the boot,
marks the instance `startup_failed`, and `start_engine()` publishes the singleton only
after a fully successful start. That new, truthful lifecycle state is only useful to
operators if the probes the Docker/Compose healthchecks poll act on it. Historically
`/health/ready` was keyed on `checks["api"] and checks["workspace_authority"]` only, so
a conductor with a failed or mid-boot engine kept answering 200 and stayed in rotation
while every chat/mission surface failed closed. This is a public-contract change to
`/health/ready` (a new condition that can produce a 503) and therefore needs a recorded
decision per the repository's PR conventions.

## Decision

- `/health/ready` adds `checks["engine"]`, true only for engine states
  `ready`, `degraded`, or `not_started`; any other state (`startup_failed`, `starting`,
  `stopped`, unreadable probe) is not-ready and the endpoint answers 503 so the image
  and Compose healthchecks take the instance out of rotation.
- `not_started` keeps the historical contract for contexts that never run the app
  lifespan (tests, scripts) — they are not taken out of rotation for never having
  booted an engine. An unreadable engine probe reports `unknown` and is not-ready:
  never ready.
- Liveness (`/health`) stays 200 `ok`; it carries `engine` and a widened `degraded`
  flag informationally. Readiness, not liveness, owns rotation.

## Consequences

### Positive
- A failed boot is health-visible end to end: the load balancer stops routing to a
  conductor whose product surfaces cannot serve.
- Liveness stays stable, so orchestrators restart on their own policy instead of
  flapping on a probe that was never meant to gate.

### Negative / Trade-offs
- Clients keying on the old `api`+`workspace_authority`-only readiness see new 503s
  during failed/mid-boot engines; that is the intended fail-closed behavior.
- Scripts that import the app without the lifespan must tolerate `not_started`
  answering ready.

### Neutral
- The engine probe keeps the endpoint's defensive contract: `/health*` answers even
  when the engine module itself is broken (`unknown` → not-ready, never ready).

## Acceptance criteria

- Injecting a failure at every startup stage yields `startup_failed`, a 503 from
  `/health/ready` with `checks["engine"] == false`, and no published singleton
  (retryable) — asserted by `test_engine_startup_atomicity.py`.
- `degraded` engines (bridge→stub fallback, capability wiring to SAFE_NOOP) stay ready
  but raise `degraded` in `/health`.
