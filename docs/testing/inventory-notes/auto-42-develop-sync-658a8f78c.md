---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-42 develop sync (658a8f78c, #55): durable-approval test union

Measured arithmetic after resolving the develop #55 sync conflicts:
`check-suite-inventory.py` reports maistro-core expected 13,675, collected
13,676 — net **+1**.

What the resolution did to test counts:

- `packages/maistro-core/tests/capabilities/test_durable_approval.py` was the
  one conflicted test file. Both sides had replaced the same region with
  different tests: this branch carried
  `test_sqlite_find_effect_resolves_by_explicit_effect_scope` and
  `test_sqlite_ensure_schema_upgrades_a_legacy_table_without_effect_scope`
  (the `effect_scope` claim design); develop #55 carried
  `test_sqlite_concurrent_creation_reconciles_one_logical_approval`
  (develop's two blank-actor refusal tests auto-merged outside the conflict
  region). The resolution keeps the union — every test from both sides
  survives, none removed — which is +2 collected cases against develop's
  ledger arithmetic for that file.
- `packages/maistro-core/tests/graph/nodes/test_agent_spawn_harness.py` was
  adjusted only in the legacy-row setup of the (auto-merged) pre-#1319 replay
  test: `logical_effect=True` became `effect_scope=<legacy key>` to match the
  merged production API. No test added or removed.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`
  conflict resolved to this branch's reconciled shape (single linear head
  `043_invocation_quota_door`, superseded standalone `043`/`045` revisions
  stay gone); the previously failing
  `test_effect_index_migration_follows_the_chain_tip` and the errored
  `test_upgrade_and_downgrade_swap_the_index_shape` both pass. Same two
  tests, no count change.

The remaining −1 against develop's recorded expectation comes from the
auto-merge arithmetic elsewhere in maistro-core (both sides' notes are now
counted together against one merged tree); no test file lost a case in this
resolution — the durable-approval union above is the only test-content
change this merge made by hand.

Validation for the changed suites:

```sh
uv run pytest packages/maistro-core/tests -q            # 12742 passed
uv run pytest tests/ --ignore=tests/tools/registry -q   # 4519 passed
uv run python scripts/check-suite-inventory.py          # ok after this note
```
