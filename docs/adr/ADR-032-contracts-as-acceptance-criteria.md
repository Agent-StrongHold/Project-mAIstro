---
id: ADR-032
title: Contracts as Acceptance Criteria
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate: [maistro-engine#ADR-031]
implements: []
related:
  - maistro-engine#ADR-008
  - maistro-engine#ADR-030
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-032: Contracts as Acceptance Criteria

## Context

ADRs and specs need acceptance criteria that are testable, not aspirational. Today the engine ADR template uses a free-form checklist. `stronghold` ships a `Spec` type with invariants and Hypothesis property tests. `Project_mAIstro` specs vary in rigor. We need one convention that all four repos can adopt.

## Decision

Acceptance criteria are **layered contracts** — three kinds, picked per AC according to what is being asserted.

### 1. Boundary contracts (Pydantic / JSON Schema)

Every public type, FastAPI route input/output, and serialised message has a Pydantic model or JSON Schema. The contract test asserts:

- Valid inputs validate
- Invalid inputs raise `ValidationError`
- Schema is stable across non-major versions (additive changes only on minor; removals require a major bump)

Boundary contracts are the cheapest to write and run. Default to using one wherever a public surface exists.

### 2. Behavioral contracts (Hoare-style + Hypothesis)

Every accepted ADR/spec with behavioral acceptance criteria specifies:

- **Pre-conditions** — what must be true on entry
- **Post-conditions** — what must be true on exit
- **Invariants** — what must remain true throughout

These are encoded as Hypothesis property tests using `stronghold`'s existing `Spec` type pattern. Schematic example:

```python
@spec(
    pre=lambda x: x > 0,
    post=lambda x, result: result >= x,
    invariant=lambda state: state.tenant_id is not None,
)
def some_operation(x: int, *, state: TenantState) -> int:
    ...
```

Behavioral contracts catch bugs that boundary contracts cannot — they assert what the system *does*, not just what shape its inputs and outputs take.

### 3. Cross-service contracts (Pact-style)

Inter-service / A2A / MCP edges define **consumer-driven contracts**. The consumer publishes the contract it expects from the provider. The provider's CI runs against all consumer contracts. Failure means a breaking change to a downstream consumer.

Cross-service contracts are mandatory on every A2A boundary and every MCP server we publish.

### 4. Test classification (two-axis)

Every test names both axes via `pytest.mark`:

```python
@pytest.mark.contract("boundary")  # boundary | behavioral | cross-service
@pytest.mark.scope("unit")         # unit | property | integration | e2e
def test_x(): ...
```

Front-matter `contracts:` and `tests:` fields list which contract kinds an ADR/spec covers and the test paths that prove them. The registry CI cross-checks that an ADR claiming `contracts: [behavioral]` has at least one `pytest.mark.contract("behavioral")` test in its `tests:` list.

### 5. Quality bar — mutation testing

Line coverage is reported but is not the bar. The bar is **mutation testing kill rate** (`mutmut`):

| Contract kind | Kill rate at v1.0 |
|---|---|
| boundary | ≥ 95% (schemas should be tight) |
| behavioral | ≥ 80% (property tests catch most; some equivalent mutants are unavoidable) |
| cross-service | ≥ 75% (inter-service mutants are harder; some require integration env) |

Mutation testing is slow. CI runs mutation tests **nightly** plus on `main` merges, not on every PR. PR CI runs the underlying test suites; mutation gates land at merge time.

Targets ramp from current baseline in monthly steps. Each repo's ROADMAP names its starting kill rate and ramp.

### 6. Substrate

`stronghold`'s existing `Spec` type and `mutmut` configuration are the implementation reference. The engine adopts them; the three products inherit via Copier templates (ADR-033).

## Consequences

- Specs with behavioral AC must commit to pre/post/invariant before being marked `Accepted`. This is a higher bar than the current free-form checklist.
- The `pytest.mark.contract` / `pytest.mark.scope` axes give the registry CI enough information to flag specs whose `contracts:` field doesn't match the marks on their tests.
- Mutation testing as the bar surfaces test-quality problems that line coverage hides. The cost is CI runtime; the benefit is detectable test rot.

## Out of scope

- Specific Pact tooling choice (`pact-python` vs hand-rolled) — separate engine ADR.
- Per-repo coverage targets and ramp schedules — left to per-product ROADMAPs.
- Mutation-testing exclusion lists (equivalent mutants, unavoidable survivors) — per-repo configuration.
