---
id: SPEC-224
title: "Test harness: create_test_environment factory and HarnessEnvironment"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate:
  - maistro-engine#ADR-065
implements:
  - maistro-engine#ADR-065
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/testing/test_harness.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-224: Test harness: create_test_environment factory and HarnessEnvironment

## Context

Every test exercising the full agent pipeline (classifier → router →
graph → agent) had to hand-wire a `Container`, `RouterEngine`,
`ClassifierEngine`, `Warden`/`Sentinel`, and a `FauxProvider` from scratch,
duplicating the same dozen-line setup across test files. ADR-065 decided
to ship a single factory that assembles a ready-to-use, fully-wired test
environment around the pre-existing `FauxProvider`.

## Goals

- `create_test_environment(...)`: one call wires `Container`, `Warden`,
  `Sentinel`, `Gate`, `RouterEngine`, `ClassifierEngine`,
  `InMemoryLearningStore`, `InMemoryOutcomeStore`, `InMemoryQuotaTracker`,
  `InMemorySessionStore`, and a `GraphRun`, defaulting to a 3-node
  planner/coder/reviewer graph when no `graph_config` is given.
- `HarnessEnvironment`: a dataclass exposing `send_prompt`, `get_events`,
  `get_last_response`, `assert_event_type`, `reset`, and `run_graph`
  convenience methods over the wired components.

## Non-goals

- `FauxProvider` itself (`maistro.testing.faux_provider`) — pre-existing,
  not introduced by this spec.
- Real-provider integration testing — the harness only wires fakes/in-memory
  stores.

## Decision

`packages/maistro-core/src/maistro/testing/harness.py`:

```python
@dataclass
class HarnessEnvironment:
    container: Container
    classifier: ClassifierEngine
    router: RouterEngine
    provider: FauxProvider
    graph_run: GraphRun
    events: list[GraphEvent] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)

    async def send_prompt(self, prompt: str, **kwargs) -> dict[str, Any]: ...
    def get_events(self, event_type: str | None = None) -> list[GraphEvent]: ...
    def get_last_response(self) -> dict[str, Any] | None: ...
    def assert_event_type(self, event_type: str, count: int = 1) -> list[GraphEvent]: ...
    def reset(self) -> None: ...
    async def run_graph(self, **kwargs) -> HyperagentOutput: ...


def create_test_environment(
    *, provider=None, config=None, agents=None, graph_config=None, event_filter=None,
) -> HarnessEnvironment: ...
```

Note: the implemented class is named `HarnessEnvironment`, not
`TestEnvironment` as sketched in ADR-065's interface section —
`TestEnvironment` would collide with pytest's test-discovery naming
convention (`Test*` classes are collected as test cases), so the
implementation diverged from the ADR's literal name.

`create_test_environment` defaults `provider` to a fresh `FauxProvider()`
and `config` to `AgentConfig(router_api_key="test-key")` when omitted. If
`agents` is given, each is registered into `container.agents` and the
`IntentRegistry`. If `graph_config` is omitted, it defaults to a linear
`PLANNER → CODER → REVIEWER` graph. `HarnessEnvironment.reset()` clears
captured events/responses and resets the underlying `FauxProvider`.
`run_graph()` builds a fresh `GraphRun` per call from the harness's
stored `_graph_config`, re-attaching the event-capture callback, so
repeated `run_graph()` calls don't accumulate state across runs.

## Acceptance criteria

- [x] `create_test_environment()` with no arguments returns a fully
      wired `HarnessEnvironment` with sensible defaults
- [x] `agents` argument registers agents into both `container.agents` and
      the `IntentRegistry`
- [x] `graph_config` defaults to a 3-node planner/coder/reviewer graph
      when omitted
- [x] `HarnessEnvironment.send_prompt` records responses for later
      `get_last_response()`/assertion
- [x] `assert_event_type` raises `AssertionError` with actual vs.
      expected counts on mismatch
- [x] `reset()` clears events, responses, and the underlying
      `FauxProvider`'s state

## Testing

Covered by `packages/maistro-core/tests/testing/test_harness.py`.

## Open questions

- None — design is implemented and stable as of this writing, modulo the
  intentional `HarnessEnvironment` vs. `TestEnvironment` naming deviation
  noted above.

## References

- [ADR-065: Test harness](../adr/ADR-065-test-harness.md)
- `packages/maistro-core/src/maistro/testing/harness.py`
- `packages/maistro-core/src/maistro/testing/faux_provider.py`
