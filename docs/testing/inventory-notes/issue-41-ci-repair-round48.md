---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 48: the coverage gate reproduced green with all producers live

Round 47 was blocked because Docker was unreachable, so neither the
`coverage-postgres` producer nor the live PG atomicity legs could run and the
merge-queue "Coverage gate (publish-set floor + diff coverage)" failure had no
local reproduction. This round both services were available and the whole gate
was executed locally against head `15266ca72bcf` with CI's own steps and
arguments. Both halves pass on this content; no source change is needed or made.

## Gate reproduction (CI's steps, CI's arguments)

Services: pgvector pg18 on 127.0.0.1:5499 (the `maistro-test-pg` container,
credentials identical to the workflow's service block) and MinIO built from the
workflow's pinned Go pseudo-version
`v0.0.0-20250422221226-0d7408fc9969` (quay/dl.min.io answer 401/410 exactly as
the workflow comment says), serving 127.0.0.1:9000.

Producer fidelity note: the first attempt ran all producers `--append` into one
local `.coverage`, but CI's archive/postgres producers start from a fresh
checkout and their first `coverage run` has no `--append` — replaying those
commands verbatim overwrote the unit data. Each producer's data was therefore
captured separately and staged as `.coverage.{unit,archive,postgres}` for
`coverage combine`, matching CI's artifact combine exactly.

- `coverage (no services)`: core 13416 passed / 940 skipped; canvas 464+75s;
  evolve 987+6s; rsi 1111; bootstrap 237+1s — all green.
- `coverage (MinIO)`: `packages/maistro-core/tests/archive` 128 passed with
  `MAISTRO_REQUIRE_S3_LEGS=1` against real MinIO.
- `coverage (PostgreSQL)`: `tests/migrations` 151 passed against an unmigrated
  database (dropped/recreated first); `alembic upgrade head` then the
  persistence/container/events/runs/graph/projects/workspaces/scheduling/
  purge-driven/PG-live-admission/elevation/user_model/quota selection: 5582
  passed, 92 skipped; canvas again under the PG DSN: 516 passed, 3 skipped.
- `combine` + publish-set floor: `uv run coverage report --fail-under=87` →
  TOTAL 74173 statements, 94%, exit 0.
- Non-publish producers (server 531, turing src 210 + backend 90, design 573,
  registry 257, ext-sdk 118, hive-conductor 3418+1s, root suite for `scripts`
  4615+126s), then `coverage xml`.
- `uv run python scripts/check-diff-coverage.py coverage.xml --base
  a8258ee24dd957d0f0b302db4eee90661fe23439` → 13 changed measured files, all at
  or above 90% lines / 80% branch arcs; exit 0. The 28 other changed paths are
  tests/migrations/conftest/workflow files, exempt by declaration.

## Other named gates re-run at this head

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1332 reviewed identities,
  1332 findings, exit 0 (CI's exact arguments).
- `uv run ruff check .` / `uv run ruff format --check .` → pass (also in the
  driver's check-1/check-2 logs for this job).
- Driver battery for this job (check-3..8): focused seam pytest 470 passed,
  143 skipped; hive-conductor 148 passed; all four suite-inventory gates ok.

## Acceptance battery (canonical Run seam, PG legs enabled)

With `MAISTRO_TEST_PG_DSN` + `MAISTRO_REQUIRE_PG_LEGS=1`:

- `packages/maistro-server/tests/api/test_chat_completions.py
  test_chat_completions_gate.py test_tasks_idempotency.py
  test_tasks_run_identity.py` → 75 passed.
- `packages/maestro-core/tests/runs/test_spine_conformance.py
  runs/test_wiring.py runs/test_chat_admission.py
  tasks/test_admission_commit_atomicity.py
  tasks/test_pg_admission_atomicity_live.py` → 430 passed, including the two
  live-PG joint-commit/replay/rollback proofs against production wiring.

## Residual (unchanged, owned elsewhere)

`test_pg_admission_atomicity_live.py` is, by its own docstring, short of a
process-kill harness; the issue requires #1845's real PG process-kill /
commit-response-loss / multi-replica evidence plus owner dispositions before
issue closeout. That lane is COORDINATION_REQUIRED (#1325/#1855 path) and is
not producible inside this repair round. Everything this branch can prove is
proven above.
