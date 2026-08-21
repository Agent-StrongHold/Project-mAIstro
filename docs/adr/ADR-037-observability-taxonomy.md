---
id: ADR-037
title: Observability Taxonomy
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-030
  - maistro-engine#ADR-038
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Observability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-037: Observability Taxonomy

## Context

The inventory (`docs/INVENTORY-ADRS-SPECS.md`) flagged Monitoring & Observability as the thinnest layer overall. Engine has an `observability/` module with logging/metrics/tracing scaffolding but no ADR defining the taxonomy. `Project_mAIstro` specs cover infrastructure (`SPEC-045 langfuse-setup`, `SPEC-101 traefik-dashboard`, `SPEC-102 pwa-dashboard`) but not *what* to emit. `stronghold` uses OTEL → Arize Phoenix; the choice is undocumented at the ADR level. Without a taxonomy, every team picks differently and the four-repo system gets four observability shapes.

## Decision

Four primitives, all required:

| Primitive | Tool | What goes here |
|---|---|---|
| **Traces** | OpenTelemetry (OTLP) → Arize Phoenix or Langfuse | Causal chains across agents, tools, LLM calls. Every conduit invocation is a trace. |
| **Metrics** | Prometheus via OTEL | Counters, gauges, histograms. Per-service-key cost, latency, tokens, queue depth, cache hit rate. |
| **Logs** | structlog with context propagation | Failure detail and debug output. Always carry `trace_id` and `agent_id` when available. |
| **Events** | Engine `events.py` bus | Domain events (agent created, task completed, policy violated). Distinct from logs — events are the source of truth for state changes; logs are diagnostic narrative. |

The distinction between logs and events is intentional: a state change is **always** an event (and may also be logged for human readers); a debug message is **only** a log. Event topics are versioned; log shapes are not.

### Required spans

Every public engine entry point creates a span. Engine code that adds a public function adds the span in the same PR. Required at v1.0:

- `conduit.invoke`, `orchestrator.plan`, `orchestrator.execute`
- `router.select`, `classifier.classify`
- `agent.act`, `agent.delegate` (A2A)
- `tool.call`, `mcp.call`
- `memory.read`, `memory.write`, `memory.consolidate`
- `security.gate`, `quota.check`, `policy.decide`

### Required metrics

> **Ownership model (metrics & events).** ADR-037 owns the observability **substrate** — the
> naming convention (`maistro_*` metrics; dot-namespaced `<domain>.<entity>` event topics, see
> below), the emission primitives, and this registry contract. It does **not** enumerate every
> metric. Downstream ADRs **declare** their own metrics/events *conforming to this contract*:
> ADR-038 (`maistro_circuit_state`, `maistro_slo_remaining_budget_seconds`, `circuit.state_change`),
> ADR-050 (`maistro_tool_reversibility_count`, `tool.compensator_invoked`), ADR-051
> (`approval.gate.*`), ADR-054 (`maistro_sandbox_provision_duration_seconds`). The list below is
> the engine-core **baseline**, not the exhaustive inventory.

Engine ships these out of the box; products inherit via the Copier templates (ADR-033):

- `maistro_llm_tokens_total` — counter; labels: `model`, `service_key`, `direction=in|out`
- `maistro_llm_cost_usd_total` — counter; labels: `model`, `service_key`
- `maistro_request_duration_seconds` — histogram; labels: `route`, `outcome`
- `maistro_security_block_total` — counter; labels: `gate`, `reason`
- `maistro_quota_remaining_ratio` — gauge; labels: `service_key`, `period`
- `maistro_circuit_state` — gauge (0=closed, 1=half-open, 2=open); labels: `dependency`

### Required event topics

Domain events the engine emits. Products may add their own; they may not redefine these:

- `agent.lifecycle` — `created | started | idled | retired`
- `task.lifecycle` — `queued | started | completed | failed | cancelled`
- `security.violation` — with `gate`, `reason`, `sanitised_payload`
- `policy.decision` — with `policy_id`, `decision`, `inputs_hash`
- `memory.consolidation` — with `before`, `after`, `actor`
- `quota.exhausted` — with `service_key`, `period`

### Sampling / retention

Defaults; per-product overrides allowed via ADR-033 template knobs:

- Traces: 100% in dev; 10% sampled in prod (configurable per service-key, with always-sample on error)
- Metrics: 30-day retention
- Logs: 7-day retention
- Events: persisted indefinitely (audit value; required for compliance)

### Backend choice per product

- `Project_mAIstro` defaults to Langfuse (already specced in `Project_mAIstro#SPEC-045`)
- `AgentTuring` defaults to Langfuse for behavioral inspection
- `stronghold` defaults to Arize Phoenix (already in use)

Backend choice is a per-product Copier knob; engine code only knows the OTLP wire format.

## Consequences

- Every new engine module must register its spans/metrics/events at the entry point in the same PR. PRs that add public APIs without observability primitives are blocked at review.
- Products inherit the engine's primitives via Copier templates; per-product additions are spec'd separately.
- The split between events and logs forces explicit decisions about what's auditable. Compliance mapping for stronghold (OWASP Agentic Top 10, NIST AI RMF, EU AI Act) anchors directly to event topics.
- Engine grows a small surface (“register this span / metric / event”) that all four primitives share, so adding observability is one decision per call site, not four.

## Out of scope

- SLO and error-budget definitions — ADR-038 (reliability).
- Specific dashboard layouts — per-product.
- Alerting rules and oncall rotation — per-product SRE concern.
- Trace export to long-term storage (S3 / blob) — separate engine ADR.
