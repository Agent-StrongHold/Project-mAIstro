---
id: SPEC-228
title: "Observability baseline: logging, metrics, tracing scaffolding (partial vs. ADR-037)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-037
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests:
  - packages/maistro-core/tests/test_metrics.py
  - packages/maistro-core/tests/events/test_events.py
ac-modules:
  AC-1: maistro.observability.logging
  AC-2: maistro.observability.metrics
  AC-3: maistro.observability.tracing
  AC-4: maistro.events.bus
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-228: Observability baseline (partial implementation)

## Context

ADR-037 defines a four-primitive observability taxonomy (traces, metrics, logs, events)
with specific required span names, `maistro_*`-namespaced Prometheus metrics, and
dot-namespaced event topics. `maistro-core/observability/` and `maistro-core/events/`
predate the ADR and provide the four scaffolding *categories*, but use different names
and narrower scope than the ADR's contract. This SPEC documents what exists today,
honestly, without claiming the ADR is fully realized.

## Goals

- Document the actual logging/metrics/tracing/events modules as implemented.
- Enumerate, explicitly, which of ADR-037's required spans/metrics/event topics are
  implemented and which are not, so the gap is traceable rather than assumed closed.

## Non-goals

- Closing the gap (adding the missing spans/metrics/events) — that is future work,
  tracked via the Open Questions / a follow-up SPEC, not this documentation pass.
- Backend selection (Langfuse vs. Arize Phoenix) — per-product Copier knob, out of scope.

## Decision

Implemented today, in `packages/maistro-core/src/maistro/observability/`:

- `logging.py` — `configure_logging()`; structlog JSON/console setup; binds
  `request_id` via contextvars. Does **not** bind `trace_id`/`agent_id` as ADR-037
  requires ("Always carry `trace_id` and `agent_id` when available").
- `metrics.py` — hand-rolled `MetricsRegistry` with its own metric names
  (`http_requests_total`, `llm_requests_total`, `circuit_breaker_state`,
  `tasks_submitted_total`, etc.). None are namespaced `maistro_*` per the ADR's
  naming convention.
- `tracing.py` — a single generic `trace_agent(name)` decorator; OTEL span if available,
  else no-op. Not wired to any of the ADR's mandated span names.
- `middleware.py` — `RequestIDMiddleware`, binds only `request_id` to structlog context.

Events: `packages/maistro-core/src/maistro/events/bus.py` — an in-memory `EventBus`
bounded to 1000 events, with a free-text, ungoverned `event_type` scheme (e.g.
`"agent_fitness"`, `"warden_block"`). This serves a cross-service trigger-bus purpose,
not ADR-037's domain-event taxonomy, and does not persist indefinitely as the ADR
requires for audit value.

### Gap matrix vs. ADR-037

| Required (ADR-037) | Status |
|---|---|
| `maistro_llm_tokens_total`, `maistro_llm_cost_usd_total`, `maistro_request_duration_seconds`, `maistro_security_block_total`, `maistro_quota_remaining_ratio`, `maistro_circuit_state` | Not implemented — no `maistro_*` metrics exist; closest analog is unprefixed `circuit_breaker_state` |
| Spans: `conduit.invoke`, `orchestrator.plan/execute`, `router.select`, `classifier.classify`, `agent.act/delegate`, `tool.call`, `mcp.call`, `memory.read/write/consolidate`, `security.gate`, `quota.check`, `policy.decide` | Not implemented — `trace_agent()` decorator exists but no call site uses these names |
| Event topics: `agent.lifecycle`, `task.lifecycle`, `security.violation`, `policy.decision`, `memory.consolidation`, `quota.exhausted` | Not implemented — `EventBus` uses an unrelated free-text scheme |
| structlog with `trace_id`/`agent_id` propagation | Partial — only `request_id` is bound |
| Indefinite event persistence | Not implemented — in-memory, 1000-event cap |
| Sampling/retention config | Not found |

## Acceptance criteria

The first four record what the scaffolding actually does. AC-5 through AC-10 are
the gap against ADR-037: they carry no `ac-modules` entry because there is no
module to point at yet, so the ladder reports them as `declared` — the honest
reading of "named in an ADR, not built".

```gherkin
Feature: Observability baseline scaffolding

  @AC-1
  Scenario: Log context is request-scoped
    Given logging configured by configure_logging
    When two concurrent requests each bind their own request_id
    Then each request's records carry only its own request_id
    And clearing the context removes the key from later records

  @AC-2
  Scenario: The metrics registry shares instruments by name
    Given a metrics registry
    When the same metric name is requested twice
    Then the same instrument is returned both times
    And counts recorded through the first handle are still collected
    And counters, gauges, and histograms all behave this way

  @AC-3
  Scenario: The tracing decorator degrades without OTEL
    Given OpenTelemetry is not installed
    When a decorated function is called
    Then the function runs and its result is returned
    And an exception raised inside it propagates rather than being swallowed

  @AC-4
  Scenario: The event bus delivers to every subscriber
    Given several subscribers to one topic, one of which raises
    When an event is published to that topic
    Then the remaining subscribers still receive it

  @AC-5
  Scenario: The ADR-037 metric names are emitted
    Given a running engine
    When metrics are collected
    Then the 6 maistro_*-namespaced metrics ADR-037 names are present

  @AC-6
  Scenario: The ADR-037 spans are instrumented
    Given a running engine
    When a request traverses the named call sites
    Then the ~14 spans ADR-037 requires are recorded under their given names

  @AC-7
  Scenario: The ADR-037 event topics are emitted
    Given a running engine
    When the corresponding actions occur
    Then the 6 dot-namespaced topics ADR-037 names are published

  @AC-8
  Scenario: Trace and agent identity reach the logs
    Given a request handled by a named agent within a trace
    When its log records are examined
    Then each carries both trace_id and agent_id

  @AC-9
  Scenario: Events persist indefinitely
    Given events written some time ago
    When the audit period has elapsed
    Then those events are still readable

  @AC-10
  Scenario: Sampling and retention are configured
    Given a deployed engine
    When its observability configuration is read
    Then a sampling rate and a retention period are set explicitly
```

## Testing

- `packages/maistro-core/tests/test_metrics.py` — tests the local registry's own
  (non-ADR-037) metric names.
- `packages/maistro-core/tests/events/test_events.py` (28 tests) — covers the
  trigger/bus mechanism, not the ADR-037 taxonomy.
- No test in the repo references any ADR-037 metric, span, or event name.

## Open questions

- Should the existing `metrics.py`/`events/bus.py` be extended in place to add the
  ADR-037 names alongside the existing ones, or should ADR-037 compliance be a
  separate adapter layer?
- Who owns wiring the ~14 required spans across `conduit`, `orchestrator`, `router`,
  `classifier`, `agents`, `tools`, `memory`, `security`, `quota` — likely one PR per
  subsystem rather than one big PR, per ADR-037's own "same PR as the public API"
  consequence.
- Should this SPEC be split into per-primitive SPECs (traces, metrics, events) once
  work starts, so each can progress through the lifecycle states independently?

## References

- `packages/maistro-core/src/maistro/observability/logging.py`
- `packages/maistro-core/src/maistro/observability/metrics.py`
- `packages/maistro-core/src/maistro/observability/tracing.py`
- `packages/maistro-core/src/maistro/observability/middleware.py`
- `packages/maistro-core/src/maistro/events/bus.py`
- `packages/maistro-core/tests/test_metrics.py`
- `packages/maistro-core/tests/events/test_events.py`
