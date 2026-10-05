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
tests:
  - packages/maistro-server/tests/api/test_health.py
  - packages/maistro-server/tests/api/test_main.py
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
- LiteLLM handles retries internal to its configured upstream routing. A MAIstro caller repeating a gateway request still crosses canonical Attempt/Invocation policy and effect admission; gateway retry behavior is not evidence that a previous request was not applied. Engine wraps eligible non-LLM IO (DB, MCP, A2A, HTTP) with the shared `retry()` decorator.
- Retries respect circuit-breaker state (no retries while open).

**Canonical reattempts and external effects (clarified 2026-10-05, #1084).**
A physical retry/resume creates the next Attempt under its existing NodeRun.
A policy-controlled graph revisit after logical failure may create another
NodeRun, subject to its declared replay semantics and attempt bounds. Neither
operation erases external-effect history or independently proves that a Provider
call is safe to repeat. The Run/NodeRun/Attempt lifecycle and replay semantics
remain the existing authorities; protocol adapters do not add a retry lifecycle.

For the same logical effect, a completed Invocation replays the persisted result.
An active or UNKNOWN Invocation blocks redispatch until the existing Invocation
reconciliation authority receives sufficient evidence. APPLIED reconciliation
settles completion; NOT_APPLIED settles failure and permits the next ordinary
admission; INDETERMINATE retains the uncertainty. A new Attempt, NodeRun, client,
protocol choice or generated effect key must not be used to escape this guard.
A deliberate follow-up after a known completed response is a distinct effect,
not a retry of an uncertain one.

The effect guard has an explicit scope: ordinary model effects are currently
NodeRun-scoped; Run-wide `EFFECT_KEY` guarding is opt-in. Physical retries keep
the NodeRun and its effect identity. Authorized graph revisits follow the node's
declared replay semantics. This rule does not assert universal deduplication
across every new NodeRun or new chat Run; callers must preserve the distinction
between an authorized new operation and recovery of the same uncertain effect.

### 2. Circuit breakers

Per upstream dependency — each LLM provider, each MCP server, each A2A peer, each database. State machine:

```
closed ──(N failures in W)──► open ──(T cool-down)──► half-open ──(leased probe succeeds)──► closed
                                                  │
                                    (probe failure) │
                                                  ▼
                                                open
```

Defaults: `N=5`, `W=60s`, `T=30s`. Per-dependency tunable. State changes emit `maistro_circuit_state` (ADR-037) and a `circuit.state_change` event.

**Probe ownership (clarified 2026-08-31).** `allow_request()` atomically grants the
HALF_OPEN probe to one execution owner (thread or asyncio task). In HALF_OPEN,
`record_success()` closes the circuit only when called by the owner whose
`allow_request()` call acquired the current exclusive probe lease; success from any
other caller is ignored. The owner may call `release_probe()` so another caller can
claim the probe without changing state. An abandoned lease eventually reopens the
circuit after its configured probe timeout.

### 3. Fallbacks

- LiteLLM fallback chain handles model unavailability (e.g. `Sonnet → Opus → Gemini → local Qwen`). Configured in `litellm_config.yaml`.
- Engine provides a `Fallback[T]` type for non-LLM fallbacks. Three kinds:
  - **Cached value** — last known good
  - **Default value** — declared in spec
  - **Alternate agent** — e.g. Warden answers when the primary agent's circuit is open

Fallbacks are explicit at the call site. Implicit fallback is forbidden.

**Model ingress fallback (owner clarification 2026-10-05, #1084).**
Responses, Messages or Interactions may fall back to Chat Completions when the
preferred ingress is explicitly unsupported. This is a protocol compatibility
choice for the same authorized gateway, model and logical effect, not permission
to widen the Binding or choose another provider. Trusted capability information
can select the alternate before dispatch. After a physical request, fallback
requires evidence identifying the attempted ingress and proving rejection before
model application. Each physical request retains its own canonical Invocation;
a proven non-applied rejection settles before the alternate enters ordinary
Binding, policy, credential and quota admission.

A bare HTTP status, authentication/quota failure, timeout, partial output, empty
text, malformed frame or unexplained stream termination does not prove an
ingress unsupported. Ambiguous outcomes use the existing reconciliation process.
Connection failure may independently prove non-application and allow a canonical
reattempt, but does not establish that another protocol should be selected.
An idempotency/effect key alone is not evidence of upstream deduplication.

[SPEC-197](../specs/SPEC-197-llm-api-capability-lanes.md#lane-selection) defines
which lanes are implemented and the request/stream compatibility contract. This
clarification does not declare the Messages or Interactions adapters implemented.

### 4. Error budgets and SLOs

Every public service-key gets a service-level objective. Reliability **declares**
`maistro_slo_remaining_budget_seconds` per `(service_key, slo)` to the ADR-037 observability
substrate (ADR-037 owns the naming/registry contract; reliability owns the metric's meaning).
The service-key label is an opaque fixed-width digest; the credential itself is never exposed
in metric samples.
When budget burn rate exceeds 2x sustained over 1h, the orchestrator throttles non-critical work (low-priority tasks defer; the router scoring formula — ADR-007 — already accepts a scarcity input).

SLO numbers per product land in product ROADMAPs, not in this ADR.

### 5. Healthchecks

Three levels per service:

- **Liveness** (`/health/live`) — process is up. Cheap.
- **Readiness** (`/health/ready`) — ready to accept traffic. Verifies upstream deps reachable, cache warm, migrations applied.
- **Startup** (`/health/startup`) — initial bootstrap done. K8s uses this to delay liveness probes during slow boot.

**maistro-server implementation (2026-08-31):** the FastAPI lifespan records
application-local startup state before initialization, marks it complete only after
configuration, database/run-spine/container wiring, role-specific setup, and task-runner
startup finish, and records initialization failure without exposing the exception. The startup
endpoint reads only that in-process state; ongoing dependency probes remain the responsibility of
readiness.

K8s probes hit these directly; `Project_mAIstro` runs them via systemd or Docker healthcheck.

### Verification (per ADR-032)

Reliability primitives are verifiable contracts:

- **Circuit-breaker state transitions** — Hypothesis property tests over the state machine
- **Retry policies** — unit tests for exponential timing and max-attempts
- **Fallback chains** — integration tests
- **Healthchecks** — smoke tests; readiness must reflect dep state within 5s
- **SLO calculations** — property tests on burn-rate math

## Consequences

- Every engine module that calls an upstream applies the declared retry and circuit-breaker policy. Retry wrappers remain subject to replay eligibility and canonical effect evidence; they must not blindly repeat an UNKNOWN model effect. PRs that bypass these controls are blocked at review.
- Engine grows a `reliability/` module (or extends `quota/`) with the primitives. Products inherit via Copier.
- SLO definitions per service-key become a v1.0 requirement for all three products. ROADMAPs name initial numbers; they are tightened in monthly iterations.
- Compliance mappings (stronghold's COMPLIANCE.md) anchor to these primitives — OWASP Agentic Top 10 "Resource Overload" and "Cascading Failures" map directly to circuit breakers and error budgets.

## Out of scope

- Specific SLO numbers per product — per-product ROADMAP.
- Disaster-recovery / backup-restore — separate engine ADR.
- Chaos-engineering harness — separate engine ADR.
- Multi-region failover — stronghold-only concern, separate ADR there.
