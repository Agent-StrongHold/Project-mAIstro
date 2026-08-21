---
id: SPEC-262
title: "Memory scope policy truth table and helper ownership"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-242
  - maistro-engine#SPEC-249
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-262: Memory Scope Policy Truth Table

## Finding addressed

The deep dive found `matches_scope` to be compact but branch-heavy policy logic. Vulture reported `build_scope_filter` and `matches_scope` as unused, so the helpers need explicit supported-API ownership or removal.

## Problem

Scope matching governs which memories are visible across global, organization, team, user, and agent scopes. Comments help, but policy logic needs executable truth tables because cross-scope regressions are easy to miss with example-only tests.

## Design

1. Define a truth table for every supported stored scope and query scope combination.
2. Include same-org, cross-org, same-team, cross-team, same-user, cross-user, same-agent, cross-agent, and unknown-scope cases.
3. Add parametrized tests where each row includes stored scope, stored ids, filter set, expected result, and reason.
4. Refactor `matches_scope` only after the truth table exists.
5. Extract per-scope predicate helpers if doing so improves readability without changing behavior.
6. Decide whether `build_scope_filter` and `matches_scope` are public utility surface; if yes, test imports and allowlist vulture as needed.

## Acceptance criteria

- [ ] Truth-table tests cover global/org/team/user/agent positive and negative cases.
- [ ] Cross-org and cross-team non-matches are explicit test rows.
- [ ] Unknown scope never matches.
- [ ] Refactor, if any, preserves truth-table results.
- [ ] Vulture classification for scope helpers is documented as supported API or dead code.
