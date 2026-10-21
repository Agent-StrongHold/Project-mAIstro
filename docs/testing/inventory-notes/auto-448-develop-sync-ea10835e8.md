---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-448 — third + fourth develop syncs (0179dfabe, ea10835e8) and conflict resolution

Lane L448 (issue #448), CI-repair round. The branch head `b7f796e27` was
**behind `origin/develop` (`0179dfabe`)**, and the merge queue carried an
**in-progress `git merge` with one unresolved conflict** preserved in the
worktree (`MERGE_HEAD = 0179dfabe`, `deploy/scripts/verify-restore.sh` both
modified). This note records the resolution, the follow-up sync to the then-
current `origin/develop` (`ea10835e8`), and the evidence that the
`integration-scope` red is green at the final merged head.

## Why the red was a sync artifact, not branch code

`integration-scope` is an aggregator (`.github/workflows/integration-scope.yml`)
that waits for the specialized checks the path classifier selects and fails if
any of them concluded non-success. For this branch the required set is:

```
docker-build, hive-conductor-e2e, hive-conductor-e2e-ui,
postgres (pg17), postgres (pg18), wheel-imports
```

At the last merge-queue evaluation (`34379a1660c39f445fa143bcedb422022daa9007`)
`postgres (pg17)` and `postgres (pg18)` were the failing legs; the
`c2e7c2cba` "keep audit_log DDL in the alembic chain, not startup" repair and
the subsequent develop syncs closed that. The remaining block was the
unresolved sync conflict itself, which this round resolves in place.

## The merges and the single conflict

`git merge --no-ff origin/develop` against the preserved `0179dfabe` (local
commit `ded032ece0bc`, parents `b7f796e2746` + `0179dfabe5e7`). One file
conflicted. After resolving it, `origin/develop` had advanced to `ea10835e8`
(three WIP commits: extension scaffold CLI, reactor state authority, and the
API-gate temporary-disposition contract); a `git merge-tree` simulation showed
the follow-up merge was clean, so it was taken as commit `32e46bdaa59e`.

### `deploy/scripts/verify-restore.sh` — the scratch-postgres readiness loop

Three-way conflict between the branch (`HEAD`, `seq 1 120` with `pg_isready`
only, plus `docker logs` and `{{.State.Running}}` diagnostics), the merge base
`c2d7209f1` (`seq 1 60`, `pg_isready` only, bare failure message), and
develop `0179dfabe` (`seq 1 60` requiring `psql … -d "${PG_DB}" -c 'SELECT 1;'`
— the entrypoint temp-server race fix, with a `fail_verifier` guard).

The two branch-side tests pin opposite halves of one contract and both must
pass:

- `tests/test_backup_restore_oracle.py::test_verify_readiness_failure_is_diagnosable`
  (branch) — requires `docker logs`, `{{.State.Running}}` and `seq 1 120`;
- `tests/test_backup_restore_oracle.py::test_scratch_ready_means_the_target_database_answers`
  (develop) — requires the loop body to require the **target database** to
  answer, and the post-loop guard to fail as a verifier failure before
  `pg_restore`.

Resolution keeps both: `seq 1 120` (the branch's slow-initdb budget) with the
loop body requiring `pg_isready` **and** `psql … -d "${PG_DB}" -c 'SELECT 1;'`
(develop's race fix), the `{{.State.Running}}` fail-fast, `docker logs` on both
failure paths, and the `fail_verifier "scratch postgres did not become ready …"`
guard. The develop test's `split("for _ in $(seq 1 60); do", 1)` marker is
absent, so its fallback splits on the first `done` (the only one in the file)
and still sees the `pg_isready`/`psql`/`-d "${PG_DB}"` loop body and the
post-loop `fail_verifier … < pg_restore` ordering.

## Counts

This round authored **no new test node**: the merges carried develop's own
tests, which develop's own notes already account for. The lane's own
contribution to `packages/maistro-core/tests` is `+0`. Measured at the final
merged head (`32e46bdaa59e`): `scripts/check-suite-inventory.py` reports
**21 suites match; 32778 collected = 32778 unique; 0 duplicates**.

## Evidence at the merged head (`ded032ece0bc`)

| check | command | result |
|---|---|---|
| postgres (pg17) | full `ci.yml` postgres leg sequence on `pgvector/pgvector:pg17` | `test_migration_chain` 18 passed; persistence 837 passed/84 skipped; workspaces 330/2; personas 130; goals 77; container_postgres 15; canvas 7; design 4; scheduling 339 — **all pass** |
| postgres (pg18) | full `ci.yml` postgres leg sequence on `pgvector/pgvector:pg18` | identical pass counts — **all pass** |
| wheel-imports | `scripts/verify-wheel-imports.py --dist dist/ --python 3.12` | all 12 wheels import from a clean venv |
| min-dep floors | `scripts/verify-minimum-dependencies.py --package packages/maistro-core` | 24 checks passed, all 12 declared deps at floors |
| vulture ledger | `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1324 reviewed identities → 1324 findings, OK (base `ea10835e8`, candidate `32e46bdaa`) |
| ratchet provenance | `scripts/check-ratchet-provenance.py` | OK (candidate `ded032ece0bc`, 53 quality JSON consumers) |
| shipped-surface truth | `scripts/check-shipped-surface-truth.py` | complete |
| reachability | `scripts/check-reachability.py` | 1430 modules, 168 unreachable, **no newly unreachable** |
| route permissions | `scripts/check-route-permissions.py` | 41 declared, 0 undeclared |
| radon ratchet | `scripts/check-radon-baseline.py` | 134 reviewed, 0 new/regressed/stale |
| suite inventory | `scripts/check-suite-inventory.py` | 21/21 suites match, 32778 collected, 0 duplicates |
| merge markers | `scripts/check-merge-markers.py` | ok: no conflict markers in any tracked file |
| restore oracle | `pytest tests/test_backup_restore_oracle.py` | 17 passed |
| restore characterization | `pytest tests/test_restore_oracle_characterization.py` | 6 passed (incl. live `test_real_verify_restore_drill_passes_end_to_end`) |
| readiness gate | `pytest tests/test_restore_oracle_readiness_gate.py` | 4 passed |
| root suite | `pytest tests/ --ignore=tests/tools/registry` | 5403 passed, 138 skipped |
| server | `pytest packages/maistro-server/tests` | 596 passed, 8 skipped |
| hive backend | `pytest packages/hive-conductor/backend/tests` | 3846 passed, 24 skipped |
| core changed areas | `pytest packages/maistro-core/tests/{extensions,runs,tools/sandbox,capabilities,fitness,sandbox}` | 3598 passed, 384 skipped |

| new develop commits | `pytest packages/maistro-core/tests/{reactor,extensions/test_extension_scaffold.py} packages/hive-conductor/backend/tests/test_foundation_reactor_state.py tests/test_check_api_route_contracts.py` | 177 passed, 5 skipped |

Not re-run locally (time-bound, and not among the failing gates):
`docker-build` (45-min cold-path build job) and `hive-conductor-e2e(-ui)`
(browser e2e). Both are required by `integration-scope` for this branch; neither
was in the failing-leg list at `34379a166`.
