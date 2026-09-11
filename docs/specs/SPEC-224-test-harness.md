---
id: SPEC-224
title: "Test harness: create_test_environment factory and HarnessEnvironment"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-065
implements:
  - maistro-engine#ADR-065
related:
  - maistro-engine#1154
supersedes: []
superseded-by: []
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

## Scope

`create_test_environment()` assembles an in-memory `Container`, classifier,
router, security boundary, and `FauxProvider` for package tests. The harness is
a prompt/provider test fixture; it is not a Graph execution authority.

The pre-durable GraphRun convenience path was retired by #1154. Physical Graph
work in tests must use `maistro.graph.durable_runs.run_durable_graph` with a
canonical Run store, and Graph traversal behavior is covered by the durable
Graph test suites.

## Interface

`HarnessEnvironment` exposes only provider and container helpers:

```python
@dataclass
class HarnessEnvironment:
    container: Container
    classifier: ClassifierEngine
    router: RouterEngine
    provider: FauxProvider
    responses: list[dict[str, Any]]

    async def send_prompt(self, prompt: str, **kwargs) -> dict[str, Any]: ...
    def get_last_response(self) -> dict[str, Any] | None: ...
    def reset(self) -> None: ...
```

`create_test_environment(...)` accepts optional `provider`, `config`, and
`agents` arguments. It uses in-memory stores and registers supplied agents in
the container and intent registry.

## Testing

Covered by `packages/maistro-core/tests/testing/test_harness.py`. Canonical
Graph lifecycle and traversal coverage belongs under
`packages/maistro-core/tests/graph/durable_runs/`.
