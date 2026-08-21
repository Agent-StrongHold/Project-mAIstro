---
id: SPEC-263
title: "Graph optimizer prompt rendering contracts"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-177
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

# SPEC-263: Graph Optimizer Prompt Rendering Contracts

## Finding addressed

The deep dive found `GraphOptimizer._propose_prompt` to be cohesive but complex. The risk is prompt drift: required sections can disappear without type, lint, or integration failures.

## Problem

Prompt rendering is deterministic enough to test directly, but today it is coupled to the LLM call path. End-to-end optimizer tests can miss missing sections, wrong rank suffixes, omitted failure examples, or malformed upstream/downstream context.

## Design

1. Extract pure render helpers for node context, performance signal, failure examples, and rewrite instructions.
2. Keep `_propose_prompt` responsible for orchestration and the LLM call, not string assembly details.
3. Define required prompt sections as contractual:
   - pipeline objective;
   - topology;
   - node role;
   - upstream input;
   - required output;
   - downstream consumer;
   - current prompt;
   - performance signal;
   - failure patterns;
   - rewrite instructions;
   - return-format instruction.
4. Add exact-substring or snapshot tests for deterministic prompt rendering.
5. Mock the LLM call in unit tests and assert the rendered message payload.

## Acceptance criteria

- [ ] Prompt rendering helpers are pure and unit tested.
- [ ] Tests assert every required prompt section is present.
- [ ] Rank suffix and missing-metric fallback behavior are tested.
- [ ] Failure examples render deterministically and preserve ordering.
- [ ] `_propose_prompt` tests mock the LLM and assert stripped returned text.
