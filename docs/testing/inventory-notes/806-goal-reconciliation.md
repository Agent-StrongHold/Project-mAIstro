---
inventory-delta:
  packages/maistro-core/tests: +72
---
# 806-goal-reconciliation

Seventy-two new tests, all additions, no removals or compensating changes:

- `tests/goals/test_goal_reconciliation.py` (64 node IDs): the M3 #806
  acceptance matrix for durable, event-driven, fenced, restart-safe Goal
  reconciliation — concurrent-process claim exclusivity (in-memory twin and
  a two-connection SQLite stand-in for two processes), stale-holder fencing
  after takeover/expiry, idempotent duplicate-event and duplicate-decision
  delivery, crash convergence after/before artifact creation, the five
  canonical wake triggers, bounded safety-sweep repair, blocked/waiting
  Goals consuming no decisions until a relevant state change, durable
  budget/deadline/cancel admission fences, the `complete=True` Goal-level
  stop condition settling the Goal (terminal postures refuse later claims,
  decisions, and admissions across restarts), control-metadata
  (non-lifecycle) guarantees, and failover lineage/no-double-execution
  proofs. Every mechanics test is parametrized over the in-memory and
  SQLite store twins.
- `tests/goals/test_goal_container_wiring.py` (8 node IDs): the Container
  composition — backend selection for the control-plane store (SQLite twin
  on the sqlite backend, in-memory fallback with the loud #122-style
  PostgreSQL warning naming #1572), the policy-free `sweep_goal_leases`
  tick reclaiming only lapsed claims, `reconcile_goals` deciding nothing
  without a #805-composed policy, and the bounded tick repairing a missed
  wake idempotently once a policy is composed.

While wiring the Container tick, a real AC-6 hole in the mechanics was
found and closed: a wake recorded on a Goal that had never been reconciled
(READY, no `awake_after`) was invisible to the bounded sweep, so a process
dying between recording the fact and the first reconcile pass lost the
notification until a new event arrived. `record_wake` now marks the Goal
due when the wake is relevant — unblocking, or the Goal is not in a
sleeping posture — in both store twins; non-unblocking wakes never shorten
a sleeping Goal's night (AC-7 preserved, asserted). Two new mechanics node
IDs cover the repair and one extends the non-unblocking skip with the
sweep-side assertion.

Verified numbers at this branch: `packages/maistro-core/tests` collects
11643 (11571 before the goals package; 11571 + 72 = 11643); a full run is
10894 passed, 737 skipped, 1 xfailed. The vulture-baseline check fails at
this HEAD independently of this change (hive-conductor DAG identities,
untouched files from the initial release); the reachability, wiring-reads,
execution-lifecycles, durable-table-inventory, owned-store-access and
cross-package-imports gates pass.

## 2026-10-18 develop-sync relocation (this note's delta unchanged: +72)

Develop merged #1938 (issue #1572, the canonical durable Goal store) as
`maistro.goals` — the same package path this mechanics package originally
occupied, because #1572's PR was closed unmerged when this work was written.
The develop sync therefore resolves by relocation, not by union: the
canonical store stays verbatim at `maistro.goals`, and the #806 control-loop
mechanics move to `maistro.goals.reconciliation` (`model.py`, `store.py`,
`reconciler.py`, `wiring.py`); the Container wiring (`goal_store` and
`goal_reconciliation_store`) now composes both seams. The durable-table
ledger carries both row sets — #1572's `canonical_goals`/
`canonical_goal_revisions`/`canonical_goal_transitions` and this work's
control-plane `goals`/`goal_claims`/`goal_wakes`/`goal_admissions` (all
four `owner_module` paths updated to the relocation).

Re-verified after the merge: `packages/maistro-core/tests` collects 16432;
full run 15362 passed, 1067 skipped, 3 xfailed, 0 failed. The 72 mechanics
tests pass at `tests/goals/test_goal_reconciliation.py` +
`test_goal_container_wiring.py` under the relocated import paths, and
develop's 71 canonical-store tests pass in the same directory. Gates green:
check-suite-inventory (17 suites, after `uv sync --locked --extra dev`
pulled the new `reference-greeter`/`maistro-ext-harness` workspace
members), check-durable-table-inventory (116 tables),
check-execution-lifecycles (19 classified), check-reachability (169
unreachable), check-wiring-reads, check-owned-store-access,
check-cross-package-imports; ruff check/format clean repo-wide; mypy 904
files clean. Residual for the #805/#804 activation round: the mechanics
store still persists its own control-plane Goal row rather than composing
on #1572's Goal record — documented in the package docstrings, not silently
assumed away.
