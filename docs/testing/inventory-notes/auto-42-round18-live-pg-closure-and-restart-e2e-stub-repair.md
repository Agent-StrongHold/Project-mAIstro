---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/maistro-canvas/tests: +0
---

# auto-42 round 18: live-PG closure of the round-17 verifier BLOCK, inherited restart-E2E stub repair

Repair round at `d5cd26db0` (merge of `origin/develop` `045cfdfbe` into
`auto-42`; base re-fetched and confirmed identical — no sync conflict). The
previous verify job (`3925ed15…`, head `20fd2e856`) returned BLOCKED on exactly
one environmental ground: "Docker daemon unavailable … PostgreSQL
persistence/migration assertions were skipped". This round ran the CI
postgres jobs against a real server and repaired the one real defect the
server exposed.

## Live PostgreSQL executed (verifier finding 3 closed)

Docker 29.7.2 is available (`DOCKER_HOST=unix:///var/run/docker.sock`); a
throwaway `pgvector/pgvector:pg18` container (127.0.0.1:54331, user `maistro`,
db `maistro_test`) reproduced the CI service. CI's exact `ci.yml`
`postgres (pg18)` step sequence, in order, at the merged head:

- `pytest tests/migrations/test_migration_chain.py -v` against the **unmigrated**
  database — 13 passed.
- `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` —
  clean round trip (chain tip 050).
- `pytest packages/maistro-core/tests/persistence
  packages/maistro-core/tests/test_container_postgres.py` — 720 passed.
- `pytest packages/maistro-server/tests/api/test_canvas_supported_path.py`
  with `MAISTRO_REQUIRE_PG_LEGS=1` — 7 passed.
- quality.yml's full PG-producer suite list (`persistence`,
  `test_container_postgres.py`, `events`, `runs`, `graph`, `projects`,
  `workspaces`, `scheduling`, `tasks/test_idempotency_purge_driven.py`,
  `security/test_elevation_durable.py`) with `MAISTRO_REQUIRE_PG_LEGS=1` —
  **4876 passed, 8 skipped, 0 failed** in 297s. This includes the durable-runs
  legs (`test_attempt_executor.py`, `test_ambiguous_effect_replay_guard.py`,
  `runs/pg_store.py` conformance) that were previously skip-green.
- Lane battery (the verify job's 14-file pytest selection) with PG legs —
  671 passed, 0 skipped.
- #1170 evidence run standalone: `runs/test_chat_attempt_recovery.py`,
  `formal/models/test_run_lease_fence.py`,
  `runs/test_crash_window_invariants.py` — 20 passed against live PG.
- #232/#143 E2E: `maistro-server/tests/test_task_restart_recovery.py` —
  SIGKILL-between-admission-and-dispatch recovery executes exactly once
  (marker written once, receipt `completed`, stock third instance idempotent).

Method notes: `MAISTRO_TEST_DATABASE_URL` must accompany
`MAISTRO_REQUIRE_PG_LEGS` or the suites *error* by design ("the PostgreSQL leg
cannot run and must not be silently skipped") — an earlier partial run with
only `MAISTRO_TEST_PG_DSN` produced 47 such errors and 6 associated failures,
all gone with the full env. The container was lane-private; the concurrently
running `maistro-860-…-pg` container belongs to another session and was not
touched.

## Inherited test-stub drift repaired (one real defect the server exposed)

`packages/maistro-server/tests/test_task_restart_recovery.py`'s
`_EXECUTE_DRIVER` stubbed `conductor.run_task` as
`_execute(request, on_response=None)`. Develop's `#718` runner-executor wiring
(`51c0e1188`, present on `origin/develop` and in this merge base) calls
`run_task(task, governed_egress=…, workspace_id=…, project_id=…)`, so every
recovered task died with
`TypeError: _execute() got an unexpected keyword argument 'governed_egress'`
recorded as the receipt error. Both the wiring and the stub are byte-identical
on `origin/develop` (file last touched there by `02422a420`; no CI workflow
runs this module), so the break is inherited, not lane-introduced — it only
became observable now that the module ran with a live server.

Fix (test-only, minimal): the stub signature gains `**_kwargs` with a comment
naming the `#718` wiring. No production behavior changed; the test count is
unchanged (the file holds one test; `packages/maistro-server/tests` stays 424
in `docs/testing/inventory/baseline.json`).

## Other gates at the merged head

- `ruff check .` / `ruff format --check .` — clean (2804 files).
- `check-suite-inventory.py` (CI's argumentless invocation) — 14 suites match.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — 1360/1360 reviewed identities (exit 0; ledger
  untouched vs develop: only `radon-baseline.json` and
  `shipped-surface-truth.json` differ, from previously landed rounds).
- `check-radon-baseline.py` — 145/145 (the round-16 invocation.py improvement
  was already banked in `9814654bf`).
- `check-execution-lifecycles.py` — 19 lifecycles, all classified.
- `check-owned-store-access.py` / `check-agent-store-writes.py` /
  `check-reachability.py` (1210 modules) — all exit 0.
- Child issues re-verified read-only: #1169, #1170, #1194 CLOSED; #42 itself
  remains OPEN for the integrators.

## Residual

None new. The formal/models RSI collection ImportError called out in round 17
remains byte-identical to develop (inherited, out of lane scope). PostgreSQL
19 has no pgvector image, matching CI's matrix note.
