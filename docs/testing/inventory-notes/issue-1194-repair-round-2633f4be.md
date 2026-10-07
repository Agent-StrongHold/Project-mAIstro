# issue-1194-repair-round (head 2633f4be)

Focused repair/validation round against the prior verifier findings. No new
test node IDs: one existing test's chain-tip invariant was updated in place.

## Chain-tip invariant updated (tests/migrations)

`test_effect_index_migration_follows_the_chain_tip` pinned the Alembic head at
`043` — written before this branch's tip commit `2633f4be` added revision
`045` (`down_revision = "043"`, the Run-scoped logical-effect admission
index). The suite failed with expected `['043']`, actual `['045']`. The test's
own comment already recorded the invariant as "one linear head with the
revisions it superseded on its ancestor path, not any fixed parent"; the
assertion now follows the same invariant at the new tip: `get_heads() ==
["045"]`, and the base→045 walk contains `039_quota_usage_event_identity`,
`044`, and `043`. Strictness is unchanged — any future branching of the chain
still fails.

## Prior verifier findings re-examined

- Vulture exact-debt-ledger gate: re-run at this head,
  `check-vulture-baseline.py packages/*/src --min-confidence 60` exits 0
  (1403 reviewed identities → 1403 findings, unclassified 0, never_allowlist
  0). The earlier exit-1 was already repaired by the banked ledger commits; no
  ledger amendment was needed this round.
- Orphaned-Attempt recovery (`_reconcile_orphaned_attempts`) re-dispatch:
  observed behavior is non-duplicative (reproduction showed `calls == 1`
  across `['cancelled', 'completed']` attempts). The path is process-loss
  recovery in the Attempt firewall — the committed AttemptResult is the
  commit point — not a retry-policy decision; failure retries are governed by
  `ReplaySemantics` in `_may_revisit_after`
  (`test_non_retryable_contract_overrides_a_graph_retry_budget`,
  `test_production_remote_work_kind_is_not_retried_under_a_retry_budget`),
  and external effects reconcile by stable identity through the Invocation
  ledger (`UnsafeEffectRetry` for CREATED/RUNNING/UNKNOWN history) and the
  delegate reservation
  (`test_a_crashed_replicas_partial_child_is_completed_and_answerable`).

## Validation evidence at this head

- `uv run ruff check .` / `ruff format --check .`: clean (2606 files).
- `uv run pytest packages/maistro-core/tests/graph -x -q`: 1477 passed,
  97 skipped.
- `uv run pytest packages/maistro-core/tests/capabilities tests/migrations
  -x -q`: 369 passed, 79 skipped.
- `uv run pytest packages/maistro-core/tests/runs
  packages/maistro-core/tests/orchestrator -x -q`: 1154 passed, 226 skipped.
- `uv run python scripts/check-suite-inventory.py`: ok, 14 suites match.
