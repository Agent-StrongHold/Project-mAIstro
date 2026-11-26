---
inventory-delta:
  packages/maistro-core/tests: 0
---

# auto-966 — coverage (PostgreSQL) red at cdd0ab5f9133 is the known recovery-claim race, re-proven green

Repair round at exact head `cdd0ab5f913360013ec360bdc9c9f8f91990fdf2`
(develop base `ed5613457d6fa54e99d0b968b72870cb96938573` already merged in).
No code or test changed this round: `inventory-delta` is zero by construction.
The round's product is evidence, recorded here so the next merge-queue
evaluation does not re-derive it.

## The one red check, read from its log

At cdd0ab5f the PR CI had exactly one failing check run:
**coverage (PostgreSQL)** (job 114127981042, run 38023050999). The `gates-ran`
commit statuses ("Required execution evidence is missing or non-executed")
are the aggregate of that same failure plus the coverage-gate job it skips
(`needs: [coverage-unit, coverage-archive, coverage-postgres]`). Every other
check run was green, including `coverage (no services)`, `coverage (MinIO)`,
`exact-debt-ledger`, the Quality gate, and `Coverage gate` prerequisites
`coverage-unit`/`coverage-archive`.

The failing step ("Apply the chain, then the suites that need a schema (under
coverage)") died on exactly one test of 5,982:

```
packages/maistro-core/tests/graph/durable_runs/test_harness_timer_recovery.py::
test_two_recovery_stores_cannot_poll_the_same_observation_twice[postgres]
```

with the run stranded `RUNNING`, `resume_at = start + 10s poll wait + 60s`,
i.e. exactly `clock + GRAPH_RECOVERY_CLAIM_TTL` at the recovery-claim
checkpoint, `version=9` — the same signature already diagnosed on 2026-10-08
for the `[sqlite]` parametrization of the same test in
`docs/research/884-tla-plus-model-checking-execution-concurrency.md`
(commit `f933928c4`): the continuation store's version fence is check-then-act
across two independently composed store instances, so a late writer can
clobber the completion and strand the run until the claim TTL lapses. That
analysis assigned the seam to M8-A3 (#2056), which introduced the file; this
branch's diff (extensions/manifests/rubric + tests/docs) touches nothing under
`src/maistro/graph` or `tests/graph` (`git diff ed5613457..HEAD --stat`
confirms), so it cannot have caused the race.

Develop's own CI on the identical suite content — run 38022445732 at
`ed5613457`, 15 minutes before this branch's run — was fully green.

## Local re-proof at this head (CI's env, real PostgreSQL 18 + pgvector)

A fresh database was migrated with this branch's chain (`alembic upgrade
head`, 001→061) and every leg of the producer step ran with the job's env
(`DB_*`, `MAISTRO_TEST_PG_DSN`, `MAISTRO_REQUIRE_PG_LEGS=1`,
`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`):

| Leg (CI argv subset) | Result |
| --- | --- |
| `tests/migrations` against an unmigrated database | 157 passed |
| `tests/graph` | 2073 passed, 1 skipped |
| `tests/persistence tests/runs tests/projects tests/workspaces` | 2774 passed, 91 skipped |
| `tests/events tests/scheduling tests/tasks/{test_idempotency_purge_driven,test_pg_admission_atomicity_live}.py tests/security/test_elevation_durable.py tests/memory/user_model tests/quota tests/backlog tests/test_container_postgres.py` | 1157 passed, 2 skipped |
| canvas leg (`maistro-canvas/tests --timeout=30`) | 517 passed, 3 skipped |
| the named flaky file, 10 consecutive repetitions | 10 × 15 passed |

Changed-line coverage from the extensions suite alone
(`coverage run --branch --source=packages/maistro-core/src/maistro -m pytest
packages/maistro-core/tests/extensions`): `extensions/packs.py` 99%,
`extensions/manifest.py` 93%, `ontology/rubric.py` 90% — the diff gate's
per-file requirement is met by the producers that already ran green in CI.

## Gate battery re-run at this head

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3260 files already formatted.
- `uv run mypy <the seven CI.yml source trees>` — no issues in 953 files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1323 reviewed
  identities → 1323 findings, exact match (CI's exact arguments).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` — 16190 node IDs, matches the recorded
  inventory.
- Full `packages/maistro-core/tests/extensions` (1019 passed), `tests/ontology`
  (63 passed), rubric consumers (`test_rubric_contracts.py`,
  `test_rubric_model.py`, `test_rubric_store.py`: 45 passed), and the
  manifest fuzz consumer `test_m8a15_fuzz_research.py` (12 passed).

## Decision

No repair beyond documentation: the failure is a liveness race in a
concurrency test seam this branch does not own, recoverable by design
(`list_due_run_ids` rescans once the claim TTL lapses), with a prior
in-repo diagnosis of the identical signature and a green develop run on
identical content. The next CI run of this head either passes (expected,
per the 10/10 local repetitions and develop's green) or reproduces the race
in `[postgres]`/`[sqlite]` — in which case the fix belongs to the M8-A3
continuation-store fence, not to #966's pack contracts.
