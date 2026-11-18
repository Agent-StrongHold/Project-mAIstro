# L337 repair round 6 — handoff (2026-10-24)

Head entering: `4413d069f` (round 5). Head leaving: the develop-sync merge of
`3825fb9b5` plus this handoff commit.

## Entering state ("worker left uncommitted work" block re-checked)

`git status` at `4413d069f` was clean except the untracked `.cache/` directory:
1.6 GB of `trivy` scan cache left by the round-3 worker, tooling data only.
Every actual round-3 fix was already committed (`aef3245a0`); there is no
uncommitted source work to salvage. Block remains resolved.

## Develop sync (the substantive change this round)

`origin/develop` had advanced two commits past the round-4 merge point
(`f956a8142` → `3825fb9b5`, the new assigned base):

- `3825fb9b5` Workspace chat continuity: durable sessions + Chat UI (#2290) —
  touches hive backend routes/services/tests and
  `packages/hive-conductor/frontend/src/api/types.gen.ts`.
- `ef36142ef` [M1 closeout] Build and scan every shipped Docker image (#2307).

Merged cleanly with the `ort` strategy (no conflicts). Three files overlapped
with this branch's round-3 repairs; all reconciled trivially:

- `.github/workflows/security.yml` and `packages/hive-conductor/Dockerfile`:
  both sides carried the byte-identical `setuptools==84.2.1` pin from the twin
  split-resolution fixes — auto-resolved.
- `packages/hive-conductor/frontend/src/api/types.gen.ts`: this branch's
  `/v1/dag-metrics/retention` types and develop's chat `workspace_id` types
  live in disjoint regions — auto-merged, then proven by regenerating.

The only lock delta is beartype marker cleanup collapsing the round-2/3 fork
(`0.22.9 ; <3.15` removed, `0.23.1` now resolves everywhere) — develop's own
merge-queue-green content.

## Named gate failure re-proven at the merged head

The merge-queue evaluation's red `test` job (at round-2 head `976ad2f6`) had
exactly one exiting-1 step: the OpenAPI types-drift gate (round 3 read the
full log; the 14 `Event loop is closed` annotations were
`PytestUnhandledThreadExceptionWarning`s inside suites that passed). At the
merged head, with ci.yml's exact commands:

```
uv run python scripts/dump-hive-openapi.py
npm --prefix packages/hive-conductor/frontend run gen:api
git diff --exit-code -- packages/hive-conductor/frontend/src/api/types.gen.ts
```

→ **exit 0**, working tree clean. The develop merge re-combined both sides'
type additions correctly.

## Full battery re-run at the merged head (fresh, not inherited)

- `uv sync --locked --extra dev --extra bootstrap` → ok (beartype 0.23.1).
- `uv run ruff check .` → all checks passed; `ruff format --check .` → 3487
  files already formatted.
- `pytest packages/maistro-server/tests packages/maistro-turing/tests
  packages/maistro-turing/backend/tests packages/maistro-design/tests
  packages/maistro-ext-harness/tests packages/maistro-ext-sdk/tests -q`
  → **2076 passed / 9 skipped**.
- `pytest tests/ --ignore=tests/tools/registry -q` → **5646 passed /
  143 skipped** (the previously warning-noisy suites included, still passing).
- `pytest packages/hive-conductor/backend/tests -q` → **3978 passed /
  25 skipped**.
- Durability + acceptance selection: `test_durable_node_metrics.py`,
  `test_feedback_route.py`, `test_goal_inspection.py`, `test_node_metrics.py`
  → **113 passed**; explicit named tests (restart/replica
  `test_metrics_survive_restart_and_refresh_an_existing_replica`,
  `test_workspace_scoped_reads_are_fail_closed`,
  `test_metrics_retention_evicts_the_oldest_durable_row`,
  `test_thumbs_read_through_the_protocol.py`,
  `test_dag_run_canonical_lifecycle.py`) → **28 passed**.
- Hive frontend `npm run lint` (0 errors) and `npm run build` → ok.
- `python scripts/check-suite-inventory.py` (CI's exact full invocation) →
  **21/21 suites match, 34183 unique identities, 0 duplicates** (develop's 12
  new chat tests absorbed by develop's own baseline bump).
- Vulture ledger with CI's exact args → **1302 reviewed == 1302 findings**,
  base correctly read from the new merge base `3825fb9b`.
- `check-image-inventory.py` and `check-image-pins.py` → ok; pypdf remains
  6.21.2 (CVE-fixed) in the merged `uv.lock`.

## Issue #337 acceptance criteria at the merged head

The merge touched none of the durability code (`git diff HEAD^2..HEAD` is
empty for every durability file), so round 5's citations carry over; spot-
checked at this head:

1. Durable owners wired: `foundation.py:131-149` (`configure_dag_run_store`,
   `configure_metrics_store`, `configure_profiles(PersistedProfileRecordStore)`)
   inside `_init_state`; feedback outcome store bound in production by
   `engine.py:301` (`_wire_outcome_store`, unwind at :304).
2. Canonical identity correlation + 409 for projection-only runs:
   `routes/feedback.py:132-133`.
3. Restart/replica equality: the named durable tests above (28 passed).
4. No unused setter: `set_outcome_store`'s production caller pinned by
   `test_thumbs_read_through_the_protocol.py` (passed).
5. Retention/scope/pagination explicit: `GET /v1/dag-metrics/retention`
   (`routes/metrics.py:50`), fail-closed scope + retention-eviction tests
   (passed).
6. Migration/parity precede retirement: transport-parity + durable-store tests
   green; profile PostgREST cutover fail-loud.

## Inventory

No tests added or removed by this round; the merge brought develop's tests
with their own committed notes and baseline. No
`docs/testing/inventory-notes` delta required; full inventory re-verified
matching (34183 identities).

## Residual risks

- Hosted CI has not yet observed the merge head; every `test`-job step and
  both previously red jobs' root causes were re-proven locally with CI's
  exact commands.
- Canvas frontend steps, `npm audit`, pip-audit, and the docker build + trivy
  scan were not re-executed here: the merge touches none of their inputs
  beyond develop's own green merge-queue content (canvas untouched; lock delta
  is beartype marker cleanup; pypdf pin unchanged from the round-3 proven
  state).
