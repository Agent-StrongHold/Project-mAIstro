---
id: ADR-065
title: Test harness with full wiring factory
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-20
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
ac-modules:
  AC-1: maistro.testing.harness
  AC-2: maistro.testing.harness
  AC-3: maistro.testing.harness
  AC-4: maistro.testing.harness
  AC-5: maistro.testing.harness
  AC-6: maistro.testing.harness
  AC-7: maistro.testing.harness
  AC-8: maistro.testing.harness
  AC-9: maistro.testing.harness
  AC-10: maistro.testing.harness
  AC-11: maistro.testing.harness
  AC-12: maistro.testing.harness
  AC-13: maistro.testing.harness
  AC-14: maistro.testing.harness
  AC-15: maistro.testing.harness
  AC-17: maistro.testing.harness
  AC-18: maistro.testing.harness
  AC-19: maistro.testing.harness
  AC-20: maistro.testing.harness
  AC-21: maistro.testing.harness
  AC-22: maistro.testing.harness
  AC-23: maistro.testing.harness
  AC-24: maistro.testing.harness
  AC-25: maistro.testing.harness
  AC-26: maistro.testing.harness
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-20
---

# ADR-065: Test harness with full wiring factory

**Status:** Proposed
**Date:** 2026-05-20
**Impacts:** IMP-033

---

## Context

Integration tests across maistro-core packages use ad-hoc setup. Some tests manually construct `Container` instances, some mock individual subsystems, some skip coverage because wiring is too complex. This leads to inconsistent test quality and gaps in coverage for the full pipeline: classify → route → agent → response.

The existing `FauxProvider` (`maistro.testing.faux_provider`) already implements the `LLMClient` protocol and doubles as a callable `llm_call` for `GraphRun`. It provides seeded responses, call logging, and streaming support — all in-memory, no network. But no facility wires FauxProvider into a complete `Container` with `ClassifierEngine`, `RouterEngine`, `GraphRun`, event capture, and assertion helpers.

What's needed is a single factory function that returns a fully wired `TestEnvironment` — every component real, every store in-memory, no databases, no network — so that tests can exercise the entire pipeline with one import.

The key constraint is composability: tests must be able to swap individual components (custom agent, seeded FauxProvider, override config) without reimplementing the full wiring.

---

## Decision

### 1. Introduce `maistro.testing.harness` module

New file at `packages/maistro-core/src/maistro/testing/harness.py`. It depends only on existing public APIs: `Container`, `ClassifierEngine`, `RouterEngine`, `GraphRun`, `FauxProvider`, in-memory stores, and `GraphEvent`.

### 2. `TestEnvironment` dataclass

`TestEnvironment` is a frozen-capable dataclass holding:

| Field | Type | Purpose |
|-------|------|---------|
| `container` | `Container` | Real DI container with in-memory stores |
| `classifier` | `ClassifierEngine` | Wired into container's conduit pipeline |
| `router` | `RouterEngine` | Wired into container |
| `provider` | `FauxProvider` | LLM backend, seeded by test |
| `graph_run` | `GraphRun` | DAG executor wired to FauxProvider |
| `events` | `list[GraphEvent]` | Captured event stream |
| `responses` | `list[dict[str, Any]]` | Captured pipeline responses |

The `events` list is populated by an event callback registered on `GraphRun.event_callbacks`. Every `graph_started`, `node_started`, `node_completed`, `node_failed`, `graph_completed`, `graph_failed`, and `cycle_started` event is appended.

### 3. Factory function: `create_test_environment`

```python
def create_test_environment(
    *,
    provider: FauxProvider | None = None,
    config: AgentConfig | None = None,
    agents: dict[str, Agent] | None = None,
    graph_config: GraphConfig | None = None,
    event_filter: set[str] | None = None,
) -> TestEnvironment: ...
```

- `provider` defaults to a fresh `FauxProvider()` with the default plan response
- `config` defaults to a minimal `AgentConfig` with `router_api_key` set
- `agents` are registered in the container after construction
- `graph_config` is applied to the `GraphRun`
- `event_filter` — if provided, only events whose `type` is in the set are captured; defaults to capturing all events
- Returns a fully wired `TestEnvironment`

The factory creates in-memory stores (`InMemoryLearningStore`, `InMemoryOutcomeStore`, `InMemorySessionStore`, `InMemoryQuotaTracker`), a `Warden`, `Gate`, `Sentinel`, `ContextBuilder`, `IntentRegistry`, and wires them into a `Container` — mirroring `create_container()` but without the `ROUTER_API_KEY` guard and with FauxProvider injected as the LLM backend.

### 4. Helper methods on `TestEnvironment`

| Method | Signature | Purpose |
|--------|-----------|---------|
| `send_prompt` | `async (prompt: str, **kwargs) -> dict[str, Any]` | Sends a user message through the full pipeline (container.route_request) and captures the response |
| `get_events` | `(event_type: str \| None = None) -> list[GraphEvent]` | Returns captured events, optionally filtered by type |
| `get_last_response` | `() -> dict[str, Any] \| None` | Returns the most recent pipeline response |
| `assert_event_type` | `(event_type: str, count: int = 1) -> list[GraphEvent]` | Raises `AssertionError` if captured events of the given type don't match count; returns matching events |
| `reset` | `() -> None` | Clears events, responses, and resets FauxProvider call log and index |
| `run_graph` | `async (**kwargs) -> HyperagentOutput` | Executes the GraphRun with FauxProvider as `llm_call` and captures resulting events |

### 5. Event capture via callback

The factory registers an async callback on `GraphRun.event_callbacks`:

```python
async def _capture(event: GraphEvent) -> None:
    if event_filter is None or event.type in event_filter:
        env.events.append(event)
```

This is the same mechanism production code uses for observability (Langfuse, logging). The harness does not monkey-patch or intercept — it uses the public event callback API.

### 6. No databases, no network

All stores are in-memory implementations from `maistro.persistence` (or `maistro.sessions`, `maistro.quota`, `maistro.memory`). `FauxProvider` never opens a socket. The harness module does not import `asyncpg`, `sqlalchemy`, `httpx`, or any I/O library. Violating this constraint (e.g., accidentally importing a PostgreSQL store) is a test-time error, not a silent degradation.

### 7. Composability via optional overrides

Every component can be replaced:

- Custom `FauxProvider` with seeded responses: `create_test_environment(provider=FauxProvider().seed(...))`
- Custom `AgentConfig` with specific model routing: `create_test_environment(config=AgentConfig(...))`
- Custom agents: `create_test_environment(agents={"planner": my_agent})`
- Custom `GraphConfig` with specific node topology: `create_test_environment(graph_config=GraphConfig(...))`

Tests that need a partially-customized environment pass only the overrides they care about; the factory supplies defaults for everything else.

---

## Consequences

### Positive

- **One-import integration tests.** `from maistro.testing import create_test_environment` gives a fully wired stack.
- **Real pipeline, zero I/O.** Every subsystem is the production implementation backed by in-memory stores. Tests catch real integration bugs that mocking would miss.
- **Event-based assertions.** Tests assert on the event stream (typed `GraphEvent` objects) rather than poking at internal state.
- **Composable.** Each test customizes exactly what it needs; shared setup lives in the factory.
- **Deterministic.** FauxProvider responses are seeded; no flaky network calls.
- **Parallel-safe.** Each `create_test_environment()` call produces an independent environment with its own stores. Multiple environments coexist in the same process.

### Negative

- **Another abstraction layer.** Tests that only need a single subsystem (e.g., `ClassifierEngine` unit test) still benefit from direct construction. The harness is opt-in, not mandatory.
- **In-memory store divergence.** If in-memory stores drift from PostgreSQL store behavior, harness tests may pass while production fails. Mitigated by the formal conformance tests in `formal/` that verify store protocol compliance.
- **Event callback overhead.** The capture callback adds a list append per event. Negligible for tests but worth noting.

### Risks

- **Coupling to Container internals.** If the Container dataclass shape changes significantly, the factory needs updating. Mitigated by the factory being the single wiring point — update once, all tests benefit.

---

## Gherkin acceptance criteria

```gherkin
Feature: Test harness with full wiring factory
  As a developer writing integration tests for maistro-core
  I want a factory that returns a fully wired test environment
  So that I can exercise the complete pipeline without mocks, databases, or network access

  Background:
    Given the maistro.testing.harness module is importable
    And FauxProvider is available from maistro.testing

  # --- Scenario 1: Factory creates fully wired environment ---

  @AC-1
  Scenario: Factory returns a TestEnvironment with all components
    When create_test_environment is called with no arguments
    Then the returned TestEnvironment has a non-null container
    And the container is a real Container instance with in-memory stores
    And the TestEnvironment has a ClassifierEngine wired into the container
    And the TestEnvironment has a RouterEngine wired into the container
    And the TestEnvironment has a FauxProvider instance
    And the TestEnvironment has a GraphRun instance
    And the events list is empty
    And the responses list is empty

  @AC-2
  Scenario: Factory-created container has all in-memory stores
    When create_test_environment is called with no arguments
    Then the container.learning_store is an InMemoryLearningStore
    And the container.outcome_store is an InMemoryOutcomeStore
    And the container.session_store is an InMemorySessionStore
    And the container.quota_tracker is an InMemoryQuotaTracker
    And the container has a Warden instance
    And the container has a Gate instance
    And the container has a Sentinel instance

  @AC-3
  Scenario: Factory uses default AgentConfig when none provided
    When create_test_environment is called with no arguments
    Then the container.config has a router_api_key set
    And the container.agents dict is empty

  # --- Scenario 2: send_prompt exercises full pipeline ---

  @AC-4
  Scenario: send_prompt routes through classify-route-respond pipeline
    Given a TestEnvironment from create_test_environment
    And the FauxProvider is seeded with a plan response
    When send_prompt is called with "write a hello world function"
    Then the FauxProvider.call_count is at least 1
    And the responses list has exactly 1 entry
    And the returned dict has a "choices" key

  @AC-5
  Scenario: send_prompt captures the response for later assertion
    Given a TestEnvironment from create_test_environment
    And the FauxProvider is seeded with a response containing "test output"
    When send_prompt is called with "generate something"
    Then get_last_response returns a dict with "choices"
    And the first choice message content contains text

  @AC-6
  Scenario: Multiple send_prompt calls accumulate responses
    Given a TestEnvironment from create_test_environment
    And the FauxProvider is seeded with 3 responses
    When send_prompt is called with "prompt one"
    And send_prompt is called with "prompt two"
    And send_prompt is called with "prompt three"
    Then the responses list has exactly 3 entries
    And get_last_response returns the third response

  # --- Scenario 3: Events are captured for assertions ---

  @AC-7
  Scenario: GraphRun events are captured when run_graph is used
    Given a TestEnvironment from create_test_environment
    And the FauxProvider is seeded with plan, code, and review responses
    When run_graph is called with a task description
    Then the events list is not empty
    And the events list contains a graph_started event
    And the events list contains a graph_completed event
    And each event has a run_id matching the GraphRun

  @AC-8
  Scenario: Node-level events are captured in order
    Given a TestEnvironment from create_test_environment
    And the FauxProvider is seeded with responses for planner, coder, and reviewer
    When run_graph is called with a task description
    Then the events list contains node_started events for each role
    And the events list contains node_completed events for each role
    And node_started for planner precedes node_completed for planner
    And node_started for coder precedes node_started for reviewer

  @AC-9
  Scenario: get_events filters by event type
    Given a TestEnvironment with 5 captured events of mixed types
    When get_events is called with event_type "node_completed"
    Then only events with type "node_completed" are returned
    And the original events list is unmodified

  @AC-10
  Scenario: assert_event_type raises on count mismatch
    Given a TestEnvironment with 2 node_completed events
    When assert_event_type is called with type "node_completed" and count 3
    Then an AssertionError is raised
    And the error message includes the expected and actual count

  # --- Scenario 4: Custom components can be injected ---

  @AC-11
  Scenario: Custom FauxProvider with seeded responses is used
    Given a FauxProvider seeded with 2 specific responses
    When create_test_environment is called with that provider
    Then the TestEnvironment.provider is the same seeded FauxProvider instance
    And send_prompt uses the seeded responses in order

  @AC-12
  Scenario: Custom AgentConfig overrides defaults
    Given an AgentConfig with a specific model routing table
    When create_test_environment is called with that config
    Then the container.config matches the provided AgentConfig
    And the RouterEngine uses models from the custom config

  @AC-13
  Scenario: Custom agents are registered in the container
    Given a dict of 2 custom agent instances
    When create_test_environment is called with those agents
    Then the container.agents dict contains the custom agents by name
    And the intent registry includes the custom agent names

  @AC-14
  Scenario: Custom GraphConfig controls node topology
    Given a GraphConfig with nodes [PLANNER, CODER] and no reviewer
    When create_test_environment is called with that graph_config
    Then the GraphRun.config has exactly 2 nodes
    And run_graph executes only planner and coder roles

  # --- Scenario 5: No network access required ---

  @AC-15
  Scenario: Harness does not import network libraries
    Given the maistro.testing.harness module
    Then it does not import httpx or aiohttp or requests
    And it does not import asyncpg or sqlalchemy
    And FauxProvider.complete does not open any socket

  @AC-16
  Scenario: Tests run without any external service running
    Given no database server is running
    And no LLM API endpoint is reachable
    When create_test_environment is called
    Then it returns a valid TestEnvironment
    And send_prompt completes without connection errors

  # --- Scenario 6: No database required ---

  @AC-17
  Scenario: All stores are in-memory implementations
    When create_test_environment is called
    Then no database connection is created
    And container.learning_store is not a PostgreSQL store
    And container.outcome_store is not a PostgreSQL store
    And container.session_store is not a PostgreSQL store

  @AC-18
  Scenario: Data persists only for the lifetime of the environment
    Given a TestEnvironment from create_test_environment
    When send_prompt is called with "remember this"
    And a second TestEnvironment is created via create_test_environment
    Then the second environment has no sessions from the first
    And the second environment has no learnings from the first

  # --- Scenario 7: Multiple environments can coexist ---

  @AC-19
  Scenario: Two environments are fully independent
    Given a TestEnvironment env_a from create_test_environment
    And a TestEnvironment env_b from create_test_environment
    When env_a.provider is seeded with response A
    And env_b.provider is seeded with response B
    Then env_a.send_prompt returns content from response A
    And env_b.send_prompt returns content from response B
    And env_a.events and env_b.events are separate lists

  @AC-20
  Scenario: Concurrent environments do not share state
    Given 5 TestEnvironments created concurrently
    When each environment's send_prompt is called with a unique prompt
    Then each environment's responses list has exactly 1 entry
    And each environment's FauxProvider.call_count is independent

  # --- Scenario 8: Environment cleanup and reset ---

  @AC-21
  Scenario: reset clears captured events and responses
    Given a TestEnvironment with 3 captured events and 1 response
    When reset is called on the environment
    Then the events list is empty
    And the responses list is empty
    And the FauxProvider call_log is empty
    And the FauxProvider response index is reset to 0

  @AC-22
  Scenario: reset allows reuse without reconstruction
    Given a TestEnvironment from create_test_environment
    And send_prompt is called with "first prompt"
    And reset is called
    And the FauxProvider is re-seeded with a new response
    When send_prompt is called with "second prompt"
    Then the responses list has exactly 1 entry from the second prompt
    And the events list contains only events from the second prompt

  @AC-23
  Scenario: reset does not clear registered agents
    Given a TestEnvironment with 2 custom agents registered
    When reset is called
    Then the container.agents dict still contains the 2 custom agents
    And the intent registry still maps to those agents

  # --- Additional coverage scenarios ---

  @AC-24
  Scenario: Event filter limits captured event types
    Given create_test_environment is called with event_filter {"node_completed", "graph_completed"}
    And the FauxProvider is seeded for a full graph run
    When run_graph is called
    Then get_events returns only events of type "node_completed" or "graph_completed"
    And get_events("node_started") returns an empty list

  @AC-25
  Scenario: FauxProvider error propagates as graph_failed event
    Given a TestEnvironment with a FauxProvider seeded with an error response
    When run_graph is called
    Then the events list contains a graph_failed event
    And the GraphRun.phase is FAILED

  @AC-26
  Scenario: run_graph returns HyperagentOutput
    Given a TestEnvironment with seeded plan, code, and review responses
    When run_graph is called with task "implement hello world"
    Then the returned HyperagentOutput has a non-empty result
    And the GraphRun.phase is COMPLETED
    And the GraphRun.total_tokens is greater than 0
```
