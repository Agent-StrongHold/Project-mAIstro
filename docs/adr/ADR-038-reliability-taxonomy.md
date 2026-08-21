---
id: ADR-038
title: Reliability Taxonomy
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-030
  - maistro-engine#ADR-037
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-038: Reliability Taxonomy

## Context

The inventory flagged Reliability & Failure Management as having no engine-level ADR. `AgentTuring` covers parts of it via `phase2-verifier`, `epic-01-eval-substrate`, and `epic-09-canary-ab-tournament`. `stronghold` has circuit breakers in triggers, LiteLLM fallback, and a quota module. Engine itself has none of this codified at the ADR level, so each consumer reinvents.

## Decision

Five reliability primitives, each with engine-level defaults that products inherit via Copier (ADR-033).

### 1. Retries

- **Idempotent operations** retry on transient failure (network, 5xx, 429). Default policy: exponential backoff `2s, 4s, 8s, 16s`, max 4 attempts.
- **Non-idempotent operations** do not retry without an explicit `idempotency_key`. The engine refuses to retry an operation lacking one.
- LiteLLM handles LLM-call retries directly. Engine wraps non-LLM IO (DB, MCP, A2A, HTTP) with a shared `retry()` decorator.
- Retries respect circuit-breaker state (no retries while open).

### 2. Circuit breakers

Per upstream dependency — each LLM provider, each MCP server, each A2A peer, each database. State machine:

```
closed ──(N failures in W)──► open ──(T cool-down)──► half-open ──(success)──► closed
                                                  │
                                          (failure) │
                                                  ▼
                                                open
```

Defaults: `N=5`, `W=60s`, `T=30s`. Per-dependency tunable. State changes emit `maistro_circuit_state` (ADR-037) and a `circuit.state_change` event.

### 3. Fallbacks

- LiteLLM fallback chain handles model unavailability (e.g. `Sonnet → Opus → Gemini → local Qwen`). Configured in `litellm_config.yaml`.
- Engine provides a `Fallback[T]` type for non-LLM fallbacks. Three kinds:
  - **Cached value** — last known good
  - **Default value** — declared in spec
  - **Alternate agent** — e.g. Warden answers when the primary agent's circuit is open

Fallbacks are explicit at the call site. Implicit fallback is forbidden.

### 4. Error budgets and SLOs

Every public service-key gets a service-level objective. Reliability **declares**
`maistro_slo_remaining_budget_seconds` per `(service_key, slo)` to the ADR-037 observability
substrate (ADR-037 owns the naming/registry contract; reliability owns the metric's meaning).
When budget burn rate exceeds 2x sustained over 1h, the orchestrator throttles non-critical work (low-priority tasks defer; the router scoring formula — ADR-007 — already accepts a scarcity input).

SLO numbers per product land in product ROADMAPs, not in this ADR.

### 5. Healthchecks

Three levels per service:

- **Liveness** (`/health/live`) — process is up. Cheap.
- **Readiness** (`/health/ready`) — ready to accept traffic. Verifies upstream deps reachable, cache warm, migrations applied.
- **Startup** (`/health/startup`) — initial bootstrap done. K8s uses this to delay liveness probes during slow boot.

K8s probes hit these directly; `Project_mAIstro` runs them via systemd or Docker healthcheck.

### Verification (per ADR-032)

Reliability primitives are verifiable contracts:

- **Circuit-breaker state transitions** — Hypothesis property tests over the state machine
- **Retry policies** — unit tests for exponential timing and max-attempts
- **Fallback chains** — integration tests
- **Healthchecks** — smoke tests; readiness must reflect dep state within 5s
- **SLO calculations** — property tests on burn-rate math

## Consequences

- Every engine module that calls an upstream wraps the call in `retry()` + circuit-breaker. PRs that don't are blocked at review.
- Engine grows a `reliability/` module (or extends `quota/`) with the primitives. Products inherit via Copier.
- SLO definitions per service-key become a v1.0 requirement for all three products. ROADMAPs name initial numbers; they are tightened in monthly iterations.
- Compliance mappings (stronghold's COMPLIANCE.md) anchor to these primitives — OWASP Agentic Top 10 "Resource Overload" and "Cascading Failures" map directly to circuit breakers and error budgets.

## Out of scope

- Specific SLO numbers per product — per-product ROADMAP.
- Disaster-recovery / backup-restore — separate engine ADR.
- Chaos-engineering harness — separate engine ADR.
- Multi-region failover — stronghold-only concern, separate ADR there.
