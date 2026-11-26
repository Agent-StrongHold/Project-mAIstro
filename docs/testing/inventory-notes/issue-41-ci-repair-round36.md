---
inventory-delta:
  packages/maistro-canvas/tests: +0
  tests/: +0
---

# Issue #41 CI-repair round 36: coverage-gate flake repair at the two thin margins

The merge queue reported `Coverage gate (publish-set floor + diff coverage)`
red. This round reproduced the gate's full multi-artifact composition locally
at `ea1231adb` against the merge base `2a24c8a82` — every producer CI runs, in
CI order, including the two prior rounds had not combined — and found the
verdict logic clean while two load-sensitive points inside the pipeline
intermittently red:

1. `packages/maistro-canvas/tests/test_canvas_store_migration.py` — the
   `empty_database` fixture's `DROP DATABASE ... WITH (FORCE)` teardown runs
   inside the test's `--timeout=30` window (reproduced once here as an error on
   `TestTheChainRunsTheStore::test_upgrade_head_on_an_empty_database_serves_the_store`
   in the full-suite composition, passing in isolation in 3.45s and on rerun;
   same signature round 35 documented). When it fires, the PostgreSQL coverage
   producer reds and the coverage-gate family never reports green.
2. `tests/test_check_security_inventory.py::test_the_shipped_document_passes` —
   the SECURITY.md gate re-measures its counted claims over every package
   source; under the coverage gate's `--source=scripts` producer it red once
   here (heavy-load run, suite 769s vs 438s/407s on the two clean reruns), then
   passed twice unchanged. Measured margin: 13s bare, 21s pinned to one CPU
   under that tracing, against the suite's 30s default.

Both now carry `@pytest.mark.timeout(120)`, the repair this repository already
uses for the same shape (`tests/test_check_cross_package_imports.py:189`,
`tests/test_check_execution_lifecycles.py:196`, `tests/test_check_frontend_api_routes.py:228`).
Mark precedence over the CLI flag was proven by running each marked test with
`--timeout=10`: both ran longer than 10s and passed. No test was added,
removed, or weakened — a genuinely drifted census or a genuinely hung drop
still fails, on a stated leash instead of an intermittent red.

Full-composition gate evidence at `ea1231adb` + this fix (all producers, CI
order): coverage-unit core 12,025 passed / 782 skipped, canvas 464+75, evolve
987+6, rsi 968, bootstrap 237+1; coverage-archive 128 passed against MinIO;
coverage-postgres migrations 107, schema suites 4,930+8, canvas 516+3;
combine-step producers server 499+8, turing 210, turing/backend 90, design
540+1, registry 257, hive 3,328+6, root `tests/` 4,229+94. Publish-set floor
92% against the 87 floor; `scripts/check-diff-coverage.py` ok for all 12
changed measured files at 90% lines / 80% branch arcs; the final root-suite
producer run replayed under the same heavy-load profile as the original
failure (760s) and passed. Ruff clean, `check-vulture-baseline.py` (CI args)
clean at 1,342 reviewed identities, suite inventory unchanged for
`packages/maistro-canvas/tests` and `tests/`.

Unchanged residual: `TaskQueue` still mints the canonical Run at
`packages/maistro-core/src/maistro/tasks/queue.py:741` and separately
completes the idempotency claim at `:766`; the joint PostgreSQL Run+binding
commit and real process-kill/multi-replica proof remain #1845's explicit
ownership. This note neither changes that architecture nor claims closeout.
