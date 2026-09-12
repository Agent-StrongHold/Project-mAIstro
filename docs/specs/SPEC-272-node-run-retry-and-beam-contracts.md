---
id: SPEC-272
title: "NodeRun retry, timeout, parse, and beam execution contracts"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-28
substrate:
  - maistro-engine#SPEC-177
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-265
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

# SPEC-272: NodeRun Retry and Beam Contracts

> **Retirement note (#1154):** The pre-durable `NodeRun` retry/beam implementation
> and its direct execution tests were retired. Current physical work uses the
> durable Attempt execution seam; the contract below remains historical design
> provenance, not a supported standalone executor.

## Finding addressed

The retired pre-durable `NodeRun._execute_single` and `NodeRun._execute_beam` combined retry
limits, circuit/budget checks, cancellation, LLM timeout handling, parser failures, candidate
scoring, and final accounting. The exact tests and terminal-state assertions are retained here
as provenance; new execution work belongs to the durable Attempt seam.

## Design

1. Define a state table for single-node execution: ready, budget exhausted, circuit open, cancelled, timeout, parse failure, retryable provider failure, terminal success, and terminal failure.
2. Define retry accounting rules for parse failures versus provider exceptions.
3. Define beam behavior for all-success, all-exception, mixed scored/error candidates, empty beam width, and scorer failure.
4. Require exact assertions on final run status, attempt count, selected candidate, error payload, and emitted events.
5. Use deterministic fake LLM, parser, scorer, clock, and budget/circuit fixtures.

## Acceptance criteria

- [x] Single execution tests cover success, timeout, parse failure, provider exception, cancellation, circuit-open, and budget-exhausted paths.
- [x] Retry count and final error message are asserted exactly for each failure family.
- [x] Beam tests cover all-success, all-parse-fail, and mixed parse-failure/success paths.
- [x] Beam tests cover all-provider-error and scorer failure; an empty beam candidate list is not reachable through public `execute` because `beam_width <= 1` uses the single path.
- [x] No graph execution test depends on a real LLM provider or wall-clock sleep.
- [x] Any intentional centralized complexity is linked to this spec with a reason.
