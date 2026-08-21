---
id: SPEC-266
title: "Tool guardrail loop-policy table and threshold tests"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-252
  - maistro-engine#SPEC-253
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-266: Tool Guardrail Policy Table

## Finding addressed

`ToolGuardrail._evaluate` encodes exact-repeat, same-tool-failure, and idempotent-no-progress policies in branch order. Boundary behavior needs table-driven tests.

## Design

1. Define a policy table for each loop pattern, warn threshold, and block threshold.
2. Document precedence when multiple patterns match the same call.
3. Split pattern detection from action selection if needed.
4. Add exact tests for one-below-warn, warn, one-below-block, and block thresholds.
5. Add reset/history tests proving stale calls do not leak across sessions.

## Acceptance criteria

- [ ] Every guardrail threshold has boundary tests.
- [ ] Pattern precedence is documented and tested.
- [ ] Same-tool failures and idempotent no-progress cannot be masked accidentally unless precedence says so.
- [ ] Reset clears all history relevant to future decisions.
