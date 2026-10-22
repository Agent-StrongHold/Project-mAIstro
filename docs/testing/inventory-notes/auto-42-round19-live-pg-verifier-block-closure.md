---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/maistro-canvas/tests: +0
---

# auto-42 round 19: live-PG re-validation closing the round-18 verifier BLOCK

Repair round at `9cab77816` (no code changes; the tree is byte-identical to the
round-18 head). The previous verify job (`d97bb638…`, same head) returned
BLOCKED on exactly one ground: "local PG validation failed before tests because
the running Docker PostgreSQL rejected its configured host credential (psycopg
OperationalError); temporary DB was removed." That failure was environmental —
the verifier never reached a test — so this round re-ran the entire live-PG
battery first-hand against a lane-private server.

## Live PostgreSQL executed (verifier finding closed)

`docker` 29.7.2 via `DOCKER_HOST=unix:///var/run/docker.sock`; lane-private
container `auto42-repair-pg` (`pgvector/pgvector:pg18`, 127.0.0.1:54333, user
`maistro`, db `maistro_test` — CI's exact service env from `ci.yml`, on a host
port not used by other sessions). Credentials proven with a direct `psycopg`
connect (`select version()` → PostgreSQL 18.6) before any suite ran. Env carried
CI's full set: `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`,
`MAISTRO_TEST_DATABASE_URL`, `MAISTRO_TEST_PG_DSN`; `MAISTRO_REQUIRE_PG_LEGS=1`
added where CI adds it. A bare `alembic` run without the `DB_*` vars fails with
the intentional `CONFIG_ERROR` from `maistro.config.database` (#187) — the
verifier's credential error was a different, environmental failure.

CI `postgres (pg18)` step sequence, in order:

- `pytest tests/migrations/ -v` — **98 passed** (includes
  `test_migration_chain.py`, the exact module the verifier could not reach:
  13 chain tests plus the pg-store-wiring, quota/session and head-guard
  suites in the same directory).
- `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head`
  — clean round trip; `alembic_version` = `051`, 59 public tables.
- `pytest packages/maistro-core/tests/persistence
  packages/maistro-core/tests/test_container_postgres.py` — **720 passed**.
- `MAISTRO_REQUIRE_PG_LEGS=1 pytest packages/maistro-core/tests/workspaces`
  — 328 passed, 2 skipped.
- `MAISTRO_REQUIRE_PG_LEGS=1 pytest
  packages/maistro-server/tests/api/test_canvas_supported_path.py` — 7 passed.

quality.yml PG-producer legs with `MAISTRO_REQUIRE_PG_LEGS=1`: `events`,
`runs`, `graph`, `projects`, `scheduling`,
`tasks/test_idempotency_purge_driven.py`, `security/test_elevation_durable.py`
— **3847 passed, 6 skipped, 0 failed** in 146s. Lane battery with PG legs (the
verify job's file selection) — **714 passed, 0 skipped, 0 failed** in 37s,
covering the durable-runsAttempt executor, the ambiguous-effect replay guard,
pg invocation store, a2a delegate, and `test_task_restart_recovery.py`
(#232/#143 SIGKILL-recovery E2E).

Path correction to the round-18 note: the #1170 lease/fence evidence module
lives at repo-root `formal/models/test_run_lease_fence.py`, **not**
`packages/maistro-core/tests/formal/models/…` (that directory does not exist;
the round-17 "formal RSI collection ImportError" refers to the root `formal/`
tree). With the corrected path, `test_run_lease_fence.py` plus
`runs/test_chat_attempt_recovery.py` and `runs/test_crash_window_invariants.py`
all passed inside the lane battery count above.

## Other gates at `9cab77816`

- `ruff check .` / `ruff format --check .` — clean (2829 files).
- `check-suite-inventory.py` (CI's argumentless invocation) — 14 suites match.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — 1355/1355 reviewed identities (exit 0).
- `check-radon-baseline.py` — 145/145.
- `check-execution-lifecycles.py` — 19/19 classified;
  `check-owned-store-access.py` / `check-agent-store-writes.py` /
  `check-reachability.py` (1222 modules) — all exit 0.

## Residual

None new. `origin/develop` advanced by two commits after the round-15 sync
(`cf4a562b6` #1829 tool-choice preservation, `a80dcaba5` M4-C population
search) — unrelated to this lane's surface; recorded, not merged, per the
lane brief (the block was not a develop-sync conflict). The lane-private
container was removed after evidence collection.
