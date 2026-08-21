---
id: ADR-XXX
title: <human-readable title>
repo: maistro-engine
kind: adr
status: Proposed
created: YYYY-MM-DD
# accepted: YYYY-MM-DD       # add when status >= Accepted
# implemented: YYYY-MM-DD    # add when status == Implemented
substrate: []     # engine ADRs/specs this rests on, e.g. maistro-engine#ADR-031
implements: []    # product specs this implements, e.g. Project_mAIstro#SPEC-139
related: []       # see-also
supersedes: []    # ADRs/specs replaced by this one
blocks: []        # ADRs/specs that cannot proceed until this is accepted
blocked-by: []    # ADRs/specs that must accept first
contracts: []     # boundary | behavioral | cross-service
tests: []         # path/to/test_file.py::test_func
layer: Foundation # Foundation | Orchestration | Agents | Tools | Memory | Observability | Reliability | Governance | UserClient
owners:
  - '@github-handle'
history:
  - status: Proposed
    date: YYYY-MM-DD
---

# ADR-XXX: <Title>

## Context

Why this decision is being made. What gap it fills. What currently exists that relates.

## Decision

What we're deciding. State it clearly.

### Sub-decision (if needed)

Detail.

## Interface (if applicable)

Public types, classes, functions, FastAPI routes (if any), error semantics.

```python
# Example type signatures
```

## Acceptance criteria

Layered contracts per [`engine#ADR-032`](ADR-032-contracts-as-acceptance-criteria.md):

- **Boundary contracts** (Pydantic / JSON Schema): list the public types validated.
- **Behavioral contracts** (Hoare-style + Hypothesis property tests): list the pre/post/invariants.
- **Cross-service contracts** (Pact-style): list the A2A / MCP edges that need consumer-driven contracts.

Front-matter `tests:` enumerates the test paths that prove these.

## Test plan

| Test | Type | Covers |
|---|---|---|
| `tests/<path>::<func>` | `boundary | unit` / `behavioral | property` / `cross-service | integration` | what it asserts |

## Dependencies

- ADR-YYY must be accepted first because …

## Out of scope

List of things deliberately not addressed by this ADR.

## Source references

Where applicable, point at code or external docs that informed the decision.

## Inspirations

If any external work shaped the design (and isn't already in `INSPIRATIONS.md`), note it here too. Per [`engine#ADR-039`](ADR-039-external-library-adoption-policy.md) §5: append-only, no completeness obligation.

## Links

- PR: #
- Issue: #
- Follow-up ADRs: ADR-XXX
