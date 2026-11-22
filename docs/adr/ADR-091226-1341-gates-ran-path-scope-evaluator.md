---
id: ADR-091226-1341
title: "Gates Ran evaluates path-scoped evidence from measured changed files"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-12
accepted: 2026-09-12
substrate:
  - maistro-engine#ADR-082526-9fa2
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_check_gates_ran.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-12
    reason: "The Gates Ran publisher needs an explicit decision for legitimate path-scoped skips."
  - status: Accepted
    date: 2026-09-12
    reason: "Measured changed-file scope and fail-closed ambiguity handling preserve execution evidence."
---

# ADR-091226-1341: Gates Ran evaluates path-scoped evidence from measured changed files

## Context

The Gates Ran publisher consumes the required-check contract for pull-request
candidates. Several required checks are intentionally path-scoped: a narrow
dependencies, documentation, or workflow change can legitimately skip a
specialized leg. Previously, the publisher treated those skips as missing
execution unless the event was a merge group, so it rejected candidates for
evidence their changed files could not produce.

The opposite failure is unsafe: a publisher must not infer scope from a missing,
malformed, or ambiguous changed-file payload. A skipped check that is in scope
is still non-execution evidence, and a check that ran and failed remains a
failure for the quality gate rather than becoming an excuse through scope.

## Decision

For pull-request candidates, Gates Ran measures the candidate's changed files
through the bounded paginated API envelope and passes that measured file set to
the reviewed `scripts/ci_merge_group_scope.py` classifier. The classifier
returns the affected specialized legs. Only a `skipped` result for a check
whose leg is proven outside that scope is removed from the required execution
set.

Scope is fail-closed. Missing, invalid, unmeasured, or unloadable scope
information produces `PENDING`; it never produces a vacuous green result. A
skipped check whose leg is in scope remains a hard non-execution finding, while
completed checks remain execution evidence regardless of their conclusion. The
DevSkim advisory registration is separate and is not made a required
path-scoped leg by this decision.

## Consequences

The nine specialized check names retain their individual semantics:
`postgres (pg17)`, `postgres (pg18)`, `object storage (MinIO)`,
`durable-events`, `strike-ladder`, `hive-conductor-e2e`,
`hive-conductor-e2e-ui`, `wheel-imports`, and `docker-build` may be excused only
when the classifier proves their corresponding paths unreachable. All other
required checks remain required. A full-code candidate continues to require all
27 checks; a narrow candidate can pass with only its applicable checks executed.

Ambiguous scope now waits for evidence instead of silently passing, and an
in-scope skip still blocks the publisher. The companion
[SPEC-091226-1341](../specs/SPEC-091226-1341-gates-ran-path-scope-evaluator.md)
records the three regression contracts exercised by the existing Gates Ran
tests.
