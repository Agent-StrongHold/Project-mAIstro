---
inventory-delta:
  packages/maistro-core/tests: 0
  tests/: 0
---

# auto-42 — develop sync of 55be1459 concluded; salvage validated and committed

The previous L42 round died on a provider timeout mid-merge: the origin/develop
sync (`55be1459b`) had all conflict resolutions staged but the merge was never
concluded, and a coherent follow-up repair sat unstaged on top of the index.
This round preserved both (unstaged diff backed up to the job directory before
any git action), concluded the merge, and validated the result.

## Git reconciliation performed

- `ed2afc509` — concluded the preserved merge of `origin/develop` (`55be1459b`,
  carrying #1319's independent #1194 implementation and #1449's durable
  elevation grants). Resolution rationale is recorded in
  [auto-42-develop-sync-55be1459-reconciliation.md](auto-42-develop-sync-55be1459-reconciliation.md).
- `4f891dc10` — second sync of the post-rebuild develop tip `a3f6b3c8` (which
  contains `55be1459b`; tree delta was one docs/research file).
- Committed the salvaged follow-up repair: removal of develop's dropped
  `replay_effect_key` metadata mechanism from `_WorkItemNode`, extraction of
  `_node_replay_semantics`/`_node_logical_effect_key` in the attempt executor,
  conflict-marker cleanup in `issue-1194-replay-contract.md`, explicit
  `effect_key` in the `_may_revisit_after` gap tests, and the matching
  suite-inventory / vulture / shipped-surface ledgers.

## Validation evidence (this tree, salvage included)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — 2614 files formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0, 1402/1402 identities banked (the five `invocation_store` retain-entries removed by the salvage are covered by the interface-use evidence, not re-listed).
- `scripts/check-suite-inventory.py`, `check-shipped-surface-truth.py`, `check-radon-baseline.py`, `check-durable-table-inventory.py` — all exit 0.
- `uv run pytest packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/graph/nodes -q` — 881 passed, 39 skipped.
- `uv run pytest packages/maistro-core/tests/{runs,capabilities,security,persistence,quota} -q` — 3350 passed, 425 skipped.
- `uv run pytest packages/maistro-server/tests/api/test_{a2a_api,health,main,strike_tracker_health}.py -q` — 50 passed.
- `uv run pytest packages/maistro-core/tests/a2a -q` — 124 passed.
- `uv run pytest tests/migrations -q` against a dedicated throwaway database on the lane's PostgreSQL 18 (`postgresql://…@127.0.0.1:55440/auto42_mig_verify`, dropped afterwards) — 98 passed in 610s, including the rewritten chain-reapplication test asserting the scope-keyed claim index, the guarded `elevation_grants` table, and the adopted Invocation row surviving with its `effect_scope`.
- `uv run mypy` over the six documented package src trees — Success, 727 files.

## Ledger amendment disclosure

`quality/vulture-baseline.json` lost five `invocation_store` retain-entries in
this round's salvage; the CI-repair lane brief for the exact-debt-ledger
explicitly authorizes removing identities the fix eliminated. The suite
inventory baseline was regenerated to the post-merge test set, which is what
`check-suite-inventory.py` verifies against.
