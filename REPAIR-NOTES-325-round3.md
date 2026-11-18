# Issue #325 repair round 3 — coverage-gate diff floor + container-scan timeout

Starting head `013b6a0e` (identical to the round-2 exit head; no develop drift
this round). Two CI findings at that head, both reproduced and fixed with
evidence:

## 1. Coverage gate (publish-set floor + diff coverage) = failure

**Root cause (from CI job 120953220695's log, fetched read-only):** not the
combine step and not the floor — the run progressed past both to the
per-file diff gate, which failed 8 files of the #325 retention work below
90% lines / 80% branch arcs against merge-group base `3825fb9b5`:

| file | CI measured | uncovered lines |
|------|-------------|-----------------|
| events/durable_log.py | 80.8% | 253, 271-273, 284 |
| events/envelope.py | 74.1% | 429, 433-435, 449-451 |
| events/pg_envelope.py | 87.5% | 97, 100-101 |
| events/pg_stores.py | 76.9% | 244, 248-249, 262-263, 273 |
| persistence/pg_audit.py | 77.8% | 181, 185-186, 199-200, 212 |
| persistence/sqlite_audit.py | 81.5% | 201, 219-221, 233 |
| security/pg_strikes.py | 88.1% | 239, 243-244, 487, 514 |
| turing backend/execution.py | 83.3% | 212-213 |

Every uncovered region is a purge-contract arc the tests never drove:
the `limit <= 0` guard, the PostgreSQL legal-hold parameter branch, the
SQLite rollback-on-failure path, the PG delete-status parse fallback, the
health-probe throttle early-return, and the Turing continuation-reclaim
failure path. The many `RuntimeError: Event loop is closed` lines in the
same log are hive-conductor aiosqlite teardown **warnings** in a producer
that exited 0 — noise, not the failure.

**Fix: 24 new tests across the 8 already-changed test files** (23 in
`packages/maistro-core/tests`, 1 in `packages/maistro-turing/backend/tests`;
zero production-code changes). Each test pins one named arc: nonpositive
limits refused before pool I/O; PG legal holds compiled into the DELETE
(`<> ALL($2::text[])`, limit moved to `$3`) and held rows proven to survive;
a mid-transaction DELETE failure raising, deleting nothing, and leaving the
SQLite connection usable (the post-failure statement proves the rollback);
unparseable PG delete status degrading to 0; a second purge inside the probe
interval sampling once; a failed continuation reclaim leaving the resumable
Run alone. Deltas recorded in
`docs/testing/inventory-notes/auto-325-diff-coverage-purge-arcs.md`.

**Proof with CI's exact invocation:** the full producer battery re-run
locally under one coverage database — postgres producer (migrations suite +
`alembic upgrade head` + the producer's 17-suite list + backlog +
`security/test_pg_strikes.py`, against real PostgreSQL with
`MAISTRO_REQUIRE_PG_LEGS=1`), full `packages/maistro-core/tests`, turing
backend producer, and the root `tests/` (scripts) producer — then:

```
uv run coverage xml -o coverage.xml
uv run python scripts/check-diff-coverage.py coverage.xml \
  --base 3825fb9b57f0145c26e1479396388879bd8e4da5
# ok: every measured file this change touches is at or above 90% lines / 80% branch arcs
```

(The same invocation on the pre-repair tree reproduces CI's failure
verbatim, including the same 8 files plus 3 files my local producer subset
had not yet measured — observability/metrics.py, tasks/idempotency.py,
scripts/check-image-lock-reconciliation.py — all green once the full
battery ran.)

## 2. Container scan + SBOM + cosign = cancelled

**Root cause (from run 40119239790's job steps):** the job hit its own
`timeout-minutes: 30` cap — started 18:16:30Z, killed 18:46:57Z, mid-step
"Reconcile installed packages to uv.lock", after four image builds (the
research image alone 16 minutes on a cold cache), four Trivy scans, a Grype
cross-check and two SBOMs consumed 29.5 minutes. Recent healthy runs take
18-20 minutes, so 30 left no headroom. No scan failed; every completed step
was green. **Fix: 30 -> 45** with an evidence comment, same
capacity-not-scope precedent as the coverage gate's documented 15 -> 30.

## Validation (all at this head)

- `ruff check .` / `ruff format --check .` — pass.
- `mypy` (CI's 10-package argument set) — Success, 1102 files.
- `check-suite-inventory.py` — both touched suites match (core +23,
  turing backend +1 via the new note).
- `check-durable-table-inventory.py` — `ok: 123 durable tables`.
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1302 = 1302, no ledger amendment needed.
- `check-ratchet-provenance.py` — OK (no quality/*.json edits this round).
- Targeted retention battery (driver's 17-file list): 536 passed, 109
  skipped. With `MAISTRO_TEST_PG_DSN` against a fresh chain-migrated
  database: 324 passed across the touched events/persistence files, PG
  legal-hold legs included.

## Residual findings (recorded, not repaired here)

1. **Pre-existing capability-approval schema divergence, not introduced by
   this branch and not exercised by CI:** alembic `043` adds
   `uq_capability_approval_effect UNIQUE (run_id, node_run_id, binding_id,
   effect_key)` while the runtime bootstrap
   (`capabilities/durable_schema.py`) declares the same constraint name
   WITH `effect_scope`, and `PgApprovalStore` inserts with
   `ON CONFLICT (run_id, effect_scope, binding_id, effect_key)`. On a fresh
   chain-migrated database the INSERT fails with
   `InvalidColumnReferenceError`; `tests/conformance`
   `[postgres]` legs (6 approval tests) fail. No CI job runs
   `tests/conformance` against a migrated chain, and the branch's diff does
   not touch approvals or alembic 043. Needs its own issue.
2. Backlog durable-leg conformance assumes a clean table per invocation
   (second run against one database fails with "already exists") — same
   "not exercised by CI" class, observed while replicating the producers.
3. hive-conductor aiosqlite `Event loop is closed` teardown warnings
   (warnings only; the producer exits 0). Pre-existing.

## Not re-run locally, and why

- The MinIO archive producer (`tests/archive`): its measured source
  (`packages/maistro-core/src/maistro`) is covered by the full core run;
  no changed file is archive-only, and the diff gate is per file.
- The publish-set 87% floor: CI's failed run evaluated it before the diff
  gate and passed it (the run reached diff-coverage), so the floor is not
  the failing gate; a local recomputation over a different producer subset
  would not be comparable.
