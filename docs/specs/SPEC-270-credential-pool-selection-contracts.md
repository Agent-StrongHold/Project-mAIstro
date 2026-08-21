---
id: SPEC-270
title: "Credential pool selection and exhaustion diagnostics contracts"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-222
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-270: Credential Pool Selection Contracts

## Finding addressed

`CredentialPool.select` combines availability filtering, exhaustion diagnostics, and strategy dispatch. The error payload and strategy behavior need separate truth-table tests.

## Design

1. Extract exhaustion diagnostics into a pure helper.
2. Test all-blocked, all-cooling, mixed blocked/cooling, and empty-pool cases.
3. Test `soonest_available_at` selection with multiple cooldowns.
4. Test strategy dispatch separately for fill-first, round-robin, and weighted/random behavior.
5. Keep public `PoolExhaustedError` payload stable for callers.

## Acceptance criteria

- [ ] Exhaustion diagnostics have exact field assertions.
- [ ] Strategy selection tests do not depend on exhaustion diagnostics.
- [ ] Empty pool and all-unavailable pool behavior are distinct if the API exposes that distinction.
- [ ] Public error payload remains backward compatible or migration is documented.
