---
inventory-delta:
  packages/maistro-canvas/tests: +0
  packages/maistro-server/tests: +0
---

# auto-393 develop-sync cd655954 resolution

Repair round for #393 ([M4 eventual] Bound Canvas layer scale before image
allocation). The named failing gate was `integration-scope`; its failure was
**inherited develop drift**, not a defect in this branch's own change. This
round merged `origin/develop` (`cd655954018c3bfd17861a75dfee6ac78f67353d`)
into `auto-393` and re-validated the #393 contract on the merged head.

**No test was added, removed, or modified by this round** — the suite counts
are unchanged (`packages/maistro-canvas/tests` keeps the +88 recorded in
`auto-393.md`, `packages/maistro-server/tests` keeps its +10; develop's own
notes supply the rest).

## Why the gate was red

`integration-scope` is an aggregator: it classifies the candidate's changed
paths and then waits for exactly the specialized legs those paths can affect.
Before the sync, the branch's diff against develop still carried `uv.lock`,
which the classifier reads as "can affect every leg" — so `durable-events` was
required, and that leg was failing for a reason that has nothing to do with
Canvas:

- `durable-events` failed in
  `packages/maistro-core/tests/events/test_container_pg_durable_events.py`
  with `relation "audit_log" does not exist`.
- The `test` job failed in `tests/test_restore_oracle_characterization.py`
  with PostgreSQL `database "maistro" does not exist`.

Both are defects in `origin/develop` itself, fixed upstream:

- `packages/maistro-core/src/maistro/persistence/pg_audit.py` now bootstraps
  the `audit_log` schema (plus its indexes and the newer columns) itself.
- `deploy/scripts/verify-restore.sh` now waits for the **target database** to
  answer `SELECT 1` instead of only probing `pg_isready`. The image
  entrypoint starts a temporary bootstrap server that accepts connections
  *before* its init step creates `${PG_DB}`, so the old probe could pass
  inside that window and `pg_restore` then died with
  `FATAL: database "maistro" does not exist`.

The merge was conflict-free (`git merge-tree` previewed it), so no content
was resolved by hand. Resolution commit: `5c109ba5e` (parents `f9d150affd`
and `cd655954018`).

## Post-merge scope (the gate's own arithmetic)

```
$ git diff --no-renames --name-only origin/develop...HEAD | \
    xargs python3 scripts/ci_merge_group_scope.py --json
{"docker_build": true, "durable_events": false, "hive_e2e": true,
 "object_storage": false, "postgres": false, "strike_ladder": false,
 "wheel_imports": true}

$ python3 scripts/check-integration-scope.py --event-name pull_request \
    --scope-json "$scope_json" --required-json
["docker-build", "hive-conductor-e2e", "hive-conductor-e2e-ui", "wheel-imports"]
```

`uv.lock` is no longer in the diff (the merged lock is byte-identical to
develop's, and already carries `aiohttp 3.14.5`), so `durable-events` is no
longer in the required set, and the four required legs are exactly the ones
that had already succeeded at the pre-sync head.

## Ledger integrity through the merge

- The branch touches no `quality/` file except `quality/radon-baseline.json`
  (one Canvas row: `execute_canvas` line 307 -> 408, complexity 38 -> 32).
  `git diff --numstat origin/develop HEAD -- quality/` shows exactly that one
  file with 3 added / 3 removed lines, and no row was lost: develop's rows
  are the merged state and the branch's one row is the expected change.
- The vulture half of the gate was re-run with **CI's exact arguments**:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> exit 0, 1321 reviewed
  identities == 1321 findings, 0 unclassified. **No amendment of
  `quality/vulture-baseline.json` was required** (and none was made).

## Re-validation on the merged head (`5c109ba5e`)

- `uv run ruff check .` -> `All checks passed!`;
  `uv run ruff format --check .` -> 3405 files already formatted.
- `uv run mypy` over the ten CI source trees -> Success, 1079 files;
  `uv run mypy --strict packages/maistro-core/src` -> Success, 808 files.
- `uv run pytest packages/maistro-canvas/tests packages/maistro-server/tests -q`
  -> 1170 passed, 83 skipped.
- `uv run python scripts/check-suite-inventory.py` -> 21 suites match
  (canvas 608, server 625).
- The inherited legs, re-run against a real PostgreSQL 17
  (`postgresql://postgres:postgres@127.0.0.1:55493/maistro_test`,
  `MAISTRO_REQUIRE_PG_LEGS=1`):
  `packages/maistro-core/tests/events` -> 385 passed;
  `tests/migrations/test_event_schema_agreement.py` -> 5 passed;
  `tests/test_restore_oracle_characterization.py` -> 4 passed.
- `uv run python scripts/check-diff-coverage.py /tmp/coverage.xml --base origin/develop`
  -> `ok: every measured file this change touches is at or above 90% lines /
  80% branch arcs` (6 changed files measured, 3 test files exempt by
  declaration).
- 30 further `scripts/check-*.py` gates (route contracts, route permissions,
  cross-package imports, doc links, backlog consistency, merge markers,
  shipped surface, durable table inventory, workflow inventory, security
  inventory, test duplicates, ...) -> all exit 0.
