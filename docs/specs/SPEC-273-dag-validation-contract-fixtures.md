---
id: SPEC-273
title: "DAG validation graph-shape and schema compatibility fixtures"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-28
substrate:
  - maistro-engine#SPEC-177
  - maistro-engine#SPEC-205
related: []
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-273: DAG Validation Contract Fixtures

## Finding addressed

The DAG validator contains non-trivial cycle detection and schema-compatibility logic. Fixture-backed tests now assert exact findings for the borderline graph shapes identified in the third-pass review.

## Design

1. Add minimal graph fixtures for acyclic chain, self-cycle, multi-node cycle, disconnected node, unknown node kind, missing edge endpoint, schema mismatch, missing output schema, and static input fallthrough.
2. Assert exact finding severity, code, node id, edge id, and message substring for each invalid fixture.
3. Keep fixture graphs small enough that the intended violation is the only failure.
4. Add one integration fixture that combines multiple failures to verify stable ordering and no duplicate findings.
5. Document whether the validator reports the first cycle only or all cycles.

## Acceptance criteria

- [x] Cycle fixtures distinguish self-cycle and multi-node cycle behavior.
- [x] Schema fixtures assert exact source/target field compatibility findings.
- [x] Static input fallthrough has a positive fixture and a negative fixture.
- [x] Unknown node kind and missing endpoint failures have stable finding codes.
- [x] Validator behavior for multiple simultaneous failures is documented and tested.
