---
id: SPEC-083026-20b2
title: "The canonical execution ids reach every log line, span and event"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
  - status: AC Defined
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-081226-7248
implements:
  - maistro-engine#ADR-083026-1cb1
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/observability/test_execution_correlation.py
  - packages/maistro-core/tests/observability/test_middleware.py
  - packages/maistro-core/tests/runs/test_execution_is_correlated.py
ac-modules:
  AC-1: maistro.observability.correlation
  AC-2: maistro.observability.correlation
  AC-3: maistro.observability.correlation
  AC-4: maistro.runs.service
  AC-5: maistro.runs.execution
  AC-6: maistro.observability.tracing
  AC-7: maistro.events.envelope
  AC-8: maistro.observability.middleware
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-20b2: The canonical execution ids reach every log line, span and event

## Context

ADR-083026-1cb1 records the decision: correlation is ambient, carried on a
`ContextVar` and bound by the seams that already hold the ids. This spec states
what that has to do to count as done.

The starting state, verified on `develop` at `f1e4993`: `request_id` bound into
structlog's contextvars by `RequestIDMiddleware` was the only correlated field
anywhere, and only for HTTP-borne work. `ContextVar` appeared in no file under
`packages/*/src`. `trace_agent`'s one production span set
`maistro.output_preview` and no id. `retry_node` receives only a `node_run_id`
and resolved no Run.

## Goals

- `maistro.observability.correlation` holds an `ExecutionContext` carrying
  `workspace_id`, `project_id`, `run_id`, `node_run_id`, `attempt_id`,
  `invocation_id`, `session_id` and `request_id`, plus
  `bind_execution_context`, `current_execution_context` and a structlog
  processor.
- The processor is installed by `configure_logging`, after `merge_contextvars`
  and merging with `setdefault`.
- `RequestIDMiddleware` binds through the context rather than into structlog
  directly.
- `RunExecutionService.execute_node` binds the Run; `retry_node` resolves it
  from the NodeRun.
- `AttemptExecutionService.execute` binds the NodeRun, and the Attempt once it
  is `RUNNING`.
- `trace_agent` writes the set ids as span attributes.
- `EventEnvelope.correlated`, applied by both `append` implementations, fills
  blank correlation fields and never overwrites a set one.
- An AST guard fails if production source calls
  `structlog.contextvars.bind_contextvars` or `clear_contextvars`.

## Non-goals

- The OTLP exporter stack. Spans are still no-ops with no TracerProvider
  configured; this spec changes what a span *says*, not whether one is exported.
- Attaching provider/model/token/cost metadata to the correct Invocation or
  Attempt — #56's single governed egress, and a separate sub-issue of #63.
- The doc-audit bullet of #63 ("docs do not claim telemetry that is not
  actually emitted").
- Reading the context to decide behaviour. It is descriptive only: a missing
  binding degrades a log line and never changes an outcome.

## Acceptance Criteria

```gherkin
Feature: The canonical execution ids reach every log line, span and event

  @AC-1
  Scenario: An inner binding keeps what the outer one said
    Given a context bound with a Run and a Workspace
    When an inner scope binds only a NodeRun
    Then all three ids are readable inside it
    And an inner binding of the same id overrides it for that scope only

  @AC-2
  Scenario: A blank id never erases an inherited one
    Given a context bound with a Run
    When an inner scope binds an empty or absent Run
    Then the inherited Run still stands
    And an id that was never set is absent rather than reported as empty

  @AC-3
  Scenario: A binding does not outlive its scope
    Given work that binds a Run and then returns or raises
    When the context is read afterwards
    Then it is empty
    And a task started before the binding never acquires it

  @AC-4
  Scenario: A retry names the same Run as the try before it
    Given a NodeRun whose first Attempt failed
    When the node is retried through the canonical service
    Then both tries report the same Run and NodeRun
    And they report different Attempts

  @AC-5
  Scenario: An executor runs under its own ids
    Given a node executed through the canonical Run service
    When the executor reads the ambient context
    Then it names the Run, the NodeRun and the Attempt it is running as
    And no Attempt is named before one is running

  @AC-6
  Scenario: A span names the execution it traced
    Given a traced agent call inside a bound execution
    When the span is inspected
    Then it carries the ids that are set as attributes
    And an id that is not set is not written as an empty attribute

  @AC-7
  Scenario: An event a producer left blank is correlated anyway
    Given an execution context naming a Run and a NodeRun
    When an event with blank correlation fields is appended
    Then the stored event carries those ids and a correlation id
    And an id the producer set is kept unchanged
    And an envelope declaring an alternate stream scope keeps it

  @AC-8
  Scenario: A request handler runs under the request it is serving
    Given a request carrying an X-Request-ID header
    When the handler reads the ambient context
    Then it names that request
    And a binding made outside the request survives it
```
