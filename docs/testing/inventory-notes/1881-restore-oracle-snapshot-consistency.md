---
inventory-delta:
  tests/: +19
---
# 1881 — restore-verification oracle made snapshot-consistent and dump-byte-independent

Issue #1881: the weekly restore drill (`deploy/scripts/verify-restore.sh`) verified a
restore by re-running `pg_dump` on the restored database and comparing SHA-256 with a
hash of a *second* plain-text dump `backup.sh` had taken separately. Two independent
defects made that an invalid oracle: the two dumps are unconstrained, so concurrent
writes can make them describe different snapshots; and PostgreSQL ≥ 17 plain output
embeds a random psql restrict key by default, so raw bytes differ even for unchanged
semantic state — on the supported pgvector:pg17 image the old drill fails a perfectly
good restore.

The fix binds the authoritative custom-format archive and its verification evidence to
one exported snapshot (`pg_export_snapshot` + `pg_dump --snapshot`), single-sources the
evidence queries in `deploy/scripts/pg-semantic-oracle.sh`, verifies restored semantics
(schema inventory + exact per-table row counts) with four distinct failure classes
(artifact / restore / semantic / verifier), and keeps pg_dump/psql security defaults
(no `--restrict-key`, no dump rewriting).

## What the tests check

`tests/test_backup_restore_oracle.py` (always on): pins the fix's structure —
single-sourced oracle definitions, snapshot binding in the producer, semantic
comparison in the consumer (schema types recorded via `pg_catalog.format_type`,
so typmods like `vector(1536)` vs `vector(768)` are distinguishable), distinct
failure classes, no `--restrict-key` invocation,
docs no longer claiming the retired "bit-for-bit via pg_dump hash" property. Each
structural property is also asserted to fail against the pre-#1881 scripts, pinned
as fixtures under `tests/fixtures/pre-1881/` (not `git show HEAD:...`: on a
committed checkout that already returns the post-change blob), so the tests cannot
pass vacuously against the replaced behavior.

`tests/test_restore_oracle_characterization.py` (integration, skipped without Docker):
live characterization on the production image (pgvector/pgvector:pg17) in throwaway
containers — (1) unchanged state ⇒ varying plain-dump bytes but stable evidence;
(2) a concurrent write makes two unconstrained dumps disagree while the snapshot-bound
archive + evidence agree and the restore matches the snapshot's counts; (3) the real
`verify-restore.sh` passes end-to-end on artifacts produced by the real oracle library;
(4) semantic loss (dropped table; tampered evidence) is rejected as SEMANTIC FAIL.
Known limits: the oracle proves structure and cardinality, not cell-level content.

## CI-repair round at 0f84314dcf51 (2026-10-18)

CI's `test` and `coverage-gate` jobs failed on the pre-existing
`tests/test_backup_permissions.py`: its docker stub exited the snapshot-export psql
session instantly, bash reaped the coprocess and unset the `ORACLE_TX` array, and the
oracle library aborted backup.sh under `set -u` (`ORACLE_TX[1]: unbound variable`).
Repaired on three fronts, +2 tests: the library now treats a dead session and a
garbage "snapshot id" (the id is interpolated into `SET TRANSACTION SNAPSHOT '<id>'`)
as its own clean failure classes; the two new always-on behavioral tests in
`test_backup_restore_oracle.py` run the real lib against fake `oracle_psql()` doubles;
and the permission test's stub now speaks the one-session protocol so the real
backup.sh completes end-to-end in the stub environment, with its artifact-inventory
assertion updated to the #1881 contract (dump/provenance/schema/rowcounts + sha256
car + deployed ref) while keeping every permission assertion (dir 0700, files 0600).

## Independent verification at d58eeea055ba (2026-10-18)

Executed from a clean checkout of the exact head, develop base `ab8b3737`:

- `uv run pytest tests/test_backup_restore_oracle.py tests/test_backup_permissions.py`
  — 21 passed (includes the two CI-failing permission tests and the two dead-session /
  garbage-snapshot-id behavioral regressions).
- `uv run pytest tests/test_restore_oracle_characterization.py` — 4 passed on
  `pgvector/pgvector:pg17` throwaway containers; scratch containers removed on exit.
- CI's exact root lane, `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/
  --ignore=tests/tools/registry -q` — 5001 passed, 135 skipped, 0 failed. The coverage
  gate's extra named legs (`tests/test_model_check_consumer_claim.py`,
  `packages/maistro-core/tests/extensions/test_lifecycle_proof.py`) — 38 passed.
- Gates: `ruff check .`, `ruff format --check .`, `scripts/check-suite-inventory.py`
  (tests/: 5229 = baseline 4117 + all note deltas, this note's +19 included),
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (1322 identities = 1322 findings), `check-ratchet-provenance.py`,
  `check-shipped-surface-truth.py` — all rc=0. `quality/` untouched vs base.
- Failure classes exercised live against the real drill: corrupt dump → RESTORE FAIL;
  missing hash file and re-signed tampered evidence → ARTIFACT FAIL; the drill's
  SEMANTIC path via `test_semantic_loss_is_rejected`. No scratch containers leaked.
- Pre-#1881 fixture provenance checked: `verify-restore.sh` fixture is byte-identical
  to the base blob; `backup.sh` fixture is the issue-cited `6454aac` blob, and the
  fail-before assertions (`--snapshot=` absent, `.sql` present) hold for the base blob
  too, so the fail-before property is not fixture-dependent.

### Hosted-CI follow-up at d58eeea05 (same day, handoff for the repair round)

The required `test` job went red at this head — NOT on the old failure: the named
root lane passed in CI (`tests/test_restore_oracle_characterization.py` 4/4 PASSED in
the dedicated `tests/ --ignore=tests/tools/registry` step), and the red moved to the
"trees pass in one process" step, where the module-scoped `pg_source_container`
fixture errored all four characterization tests: `docker exec … psql … CREATE TABLE`
returned exit 2. Root cause, reproduced locally against pgvector/pgvector:pg17 with
fast polling: the postgres image's initdb **temporary server** accepts connections
on the unix socket before the real server (and `POSTGRES_DB`) exists, so a green
`pg_isready -U maistro` does not imply `psql -d maistro` can run — first-green
pg_isready followed immediately by CREATE TABLE yields
`psql: error: … FATAL: database "maistro" does not exist` (exit 2, the CI
signature). `_wait_ready` (tests/test_restore_oracle_characterization.py) gates on
pg_isready alone; repair shape: gate readiness on a real query against the target
DB (loop `psql -X -Atq -c 'SELECT 1'` until green). The same latent pg_isready-only
race exists in `deploy/scripts/verify-restore.sh`'s scratch-readiness loop
(pre-existing pattern; on a slow init it would surface as a spurious VERIFIER FAIL)
— the same one-line hardening applies there.
