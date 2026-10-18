---
inventory-delta:
  packages/maistro-core/tests: +6
---
# m2-1175-per-scope-throttle

`packages/maistro-core/tests/runs/test_retention_policy.py` gains seven tests and
renames one, for a net +6 node IDs.

The renamed test is `test_a_failed_sweep_withdraws_the_standing_backlog_report`,
now `test_a_failed_sweep_leaves_its_scopes_backlog_standing`. Its assertion flips
on purpose. `maistro_retention_backlog_remaining{mode}` now counts backlogged
scopes in a process-wide ledger. A failed sweep commits nothing, so it neither
drains a scope's backlog nor erases the backlog another sweep observed.

New tests:

- `test_a_busy_workspace_does_not_starve_a_quiet_one`: a real two-Workspace
  `InMemoryRunStore` regression. Sweeping B right after A now purges B's Run
  (before this change it returned 0). A's backlog survives B draining, and A
  stays throttled inside its own interval.
- `test_backlogged_scopes_are_counted_per_mode`: the gauge counts scopes, with
  workspace and global scopes counted apart.
- `test_a_failed_sweep_does_not_clear_another_scopes_backlog`
- `test_an_unscoped_refusal_leaves_the_backlog_alone`
- `test_the_throttle_forgets_the_least_recently_swept_scope`: checks the LRU
  bound on the per-scope throttle.
- `test_the_throttle_bound_must_be_positive`
