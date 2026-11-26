---
inventory-delta:
  packages/maistro-core/tests: +6
---
# 1621 post-terminal child carve-out inventory delta

Repair round for the CI `test` job failure at head 8357e263: the terminal-parent
child guard (#1621) refused the shipped post-hoc flows —
`governed_model.mint_operation_identity` minting judge/settle operations
beneath a COMPLETED requesting Run, and goal-retry lineage beneath a FAILED
Run (6 hive-conductor backend tests red in CI; `benchmark_eval` even swallowed
the refusal into a silent score 0). The repair widens the carve-out exactly
one step, mirroring the fork fact's shape: a child whose own provenance
carries the identity-bound `POST_TERMINAL_CHILD_PROVENANCE` fact naming the
very parent is accepted; everything else stays refused.

Two spine-conformance pins record the widened contract on every backend
(memory/sqlite/postgres via the spine fixture):

- `test_a_post_terminal_child_is_accepted_under_a_terminal_parent`
- `test_a_post_terminal_fact_naming_another_parent_is_refused_under_a_terminal_parent`

+2 tests × 3 backends = +6 node IDs in `packages/maistro-core/tests`.
