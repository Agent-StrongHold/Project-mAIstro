# REPAIR-NOTES-2509: aiosqlite import contract broken by the #2509 durable-cursor fix

Branch `auto-2509`, repair round for issue #2509 (durable event cursor skips late
PostgreSQL commits). Starting head `7f2aad24246f`, develop base `c2beba3f810d`.

## Failure evidence (CI at 7f2aad24246f)

Five merge-queue jobs failed with the same signature,
`ModuleNotFoundError: No module named 'aiosqlite'`:

- wheel-imports (bare tier + all tier: `maistro_server.*`, `maistro_rsi.*`,
  `maistro_design`), which integration-scope requires
- docker-build and Container scan + SBOM + cosign
  (`Dockerfile.research` builder smoke, `#20`/`#22` stages)
- Validate ADR/spec front-matter (`tests/tools/registry/test_cli.py` import)
- Coverage gate: `producer coverage-postgres contributed no coverage data`

## Root cause

Commit `8396b62ad7` (this PR's own fix) moved `import aiosqlite` in
`packages/maistro-core/src/maistro/events/durable_log.py` from the
`TYPE_CHECKING` block to module scope — needed because the new
`SqliteEventLog.prove_holes_absent` opens an isolated proof connection via
`aiosqlite.connect`. But `maistro.events` re-exports `SqliteEventLog`, so every
`maistro_server`/`maistro_rsi`/`maistro_design` import graph now needed the
driver at import time. aiosqlite is core's *optional* `sqlite` extra — exactly
the invariant `scripts/verify-wheel-imports.py` documents ("aiosqlite is
TYPE_CHECKING-only — and the bare tier asserts that", line 92).

Two images prove the split: `Dockerfile` (engine) exports
`--extra image`, whose extra chain includes `maistro-core[...,sqlite]`
(`packages/maistro-server/pyproject.toml:87`) — so the engine image still
built. `Dockerfile.research:115` exports only
`--extra observability --extra browser` — no aiosqlite — then smoke-imports
`maistro_server.main`; that is the exact `#20`/`#22` failure in the
docker-build/scan logs.

## Repair

`durable_log.py` only: `import aiosqlite` back under `TYPE_CHECKING`
(alphabetical order restored, matching `consumer_cursor.py`'s guard); the one
runtime use — `aiosqlite.connect` inside `SqliteEventLog.prove_holes_absent` —
imports the module function-locally, with a comment stating the contract and
the #2509 CI round. `import sqlite3` (stdlib) stays at module scope. No
behaviour change on any path that has aiosqlite installed; the hole-proof
semantics are untouched.

## Validation executed

- `python scripts/verify-wheel-imports.py --dist <12 freshly built wheels> --python 3.12`
  (CI's exact command): **all tiers green** — bare 66 core checks incl.
  `maistro.events`/`maistro.container`; all-tier `maistro-server` 34,
  `maistro-rsi` 50, `maistro-design` 71 (the exact modules CI listed).
- Meta-path blocker (no `aiosqlite` importable): `maistro.events`,
  `maistro.container`, `maistro_server.main`, `maistro_server.api.*`,
  `tests/tools/registry/test_cli.py` all import.
- `docker build --target builder -f Dockerfile.research`: **"builder smoke ok"**
  in the exact closure that failed in CI.
- coverage-postgres producer surface, mirrored against a real
  `pgvector/pgvector:pg17` with the migrated chain and
  `MAISTRO_REQUIRE_PG_LEGS=1`: `packages/maistro-core/tests/events`
  + `test_container_postgres.py` + `test_container_wiring.py`
  = **612 passed, 4 skipped** under `coverage run --branch` (events package
  97%); the two-connection #2509 oracles (live-append hold, rollback proof)
  included.
- `uv run ruff check .` / `ruff format --check .`: green.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: 1217/1217 balanced, green.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: green (19293 nodes; src-only change).

## Residual risk

The coverage-postgres producer failure at 7f2aad2 is not fully explainable from
local evidence: every suite the branch touches passes against real migrated
pgvector pg17 with PG legs forced. The `RuntimeError: Event loop is closed`
lines in the coverage-gate log are the pre-existing benign aiosqlite teardown
noise the workflow itself documents (`.github/workflows/quality.yml:99-101`:
"the same pre-existing noise develop's passing runs print; they are not
failures"). If the next CI round still fails that producer, diff its full log
against a develop run before changing code.
