# #1064 follow-up verification (2026-11-23)

This verification does not add tests or claim issue closure. It records checks
run against `db22f8bb9433022c912b5644733bd701445180d0` and the acceptance gaps
that remain visible in production code.

## Executed

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -x -q`
  -> **16 passed, 10 skipped**. PostgreSQL was not configured (`MAISTRO_TEST_PG_DSN` unset), so the PG legs are not evidence for PostgreSQL recovery.
- `uv run ruff check . && uv run ruff format --check .` -> passed (3,650 files formatted).
- CI-exact acceptance-state ratchet:
  `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate 88ca7a1ccb5cc1fca7f0d2fa51f2527b1a2b918f`
  -> **failed**, design coverage `39.7781%` below the base floor `44.4608%`.
  No authorization or quality-ledger change was made.

## Acceptance remains unproven

- `services/evolution_graph.py::_recovery_resolver` (around lines 1480-1503)
  explicitly states that the production `PopulationStore`/`EloTournament` are
  not durably reconstructible in a new process; it refuses recovery instead
  of satisfying restart/resume.
- The `recover_queued_graph_runs` path can leave a candidate QUEUED on an
  eager resolver failure (documented in the same resolver docstring), so an
  explicit terminal/blocked disposition for missing prerequisites is not
  established.
- The replay tests reopen stores in one Python process; no distinct-OS-process
  Run-level launch is exercised. The scoped run above also skipped the PG
  cases, and does not prove the required PostgreSQL parity.
- The existing fault cases do not inject faults after every cull/breed/
  migrate/self-improve/finalize publication boundary. Exact production-harness
  parity, stale-fence concurrent publication, and uninterrupted-versus-
  process-kill population/lineage equivalence remain unverified.

The SQLite passing cases show the narrower receipt behavior exercised by those
tests only. This note does not upgrade that evidence to the issue's close-only
bar or assert remote exact-head CI / #947 review disposition.

## Re-verification at `f264d5eeb392cb698ac5dae9e03ef7042e4a9623` (2026-11-23)

Corrects the ratchet record above: the earlier acceptance-state "failure" was
an environment artifact, not a branch defect. CI's `Quality / Acceptance state`
job runs with a pgvector service and `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` set
(quality.yml:2367-2392) before invoking the gate; the earlier run reused CI's
command without CI's service, so the PostgreSQL legs did not execute and
design coverage landed at `39.7781%`.

Executed this round (postgres `pgvector/pgvector:pg18` on `127.0.0.1:5570`,
`alembic upgrade head` applied first):

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -q`
  -> **26 passed** (16 same-interpreter legs + 10 PostgreSQL legs against the
  real server). The PG recovery/idempotency legs pass; they were never seen
  running in earlier rounds.
- CI-exact `uv run python scripts/check-ac-state.py --run-tests --ratchet
  --mandate 88ca7a1ccb5cc1fca7f0d2fa51f2527b1a2b918f` with CI's PG env
  -> **exit 0**; design coverage sits exactly on the banked floor `44.4608%`,
  every declared criterion proven, no chain regressions. Run twice, ~2 min.
- `ruff check` / `ruff format` / suite-inventory gates: passed (driver logs).

The close-only gaps are unchanged by this head (docs-only delta):

- No distinct-OS-process Run-level launch: kills are in-interpreter
  `_ProcessKilled` and `_restore_process` re-enters the same interpreter;
  `test_evolution_restart_replay_pg.py:7-11` states this is not evidence for
  the distinct-process requirement.
- PG legs run `harness=SimpleNamespace(fidelity="proxy")` (lines 207, 237,
  331) and populations arrive pre-scored, so production-harness byte/semantic
  parity is not established.
- `_config()` pins `cull_pct=0.0` / `migration_interval=1000` and
  `_self_improve_top` is a no-op, so no fault is injected after the cull,
  migrate, or self-improve publication boundaries.
- The stranded-QUEUED disposition stays QUEUED by design
  (`test_evolution_recovery.py:460-505`), which does not satisfy the
  criterion requiring an explicit terminal/recovery-blocked disposition for
  prerequisites that never become durable.
- The production service restores its Evolve domain from the durable store at
  startup (`services/evolution.py::restore_or_initialize_domain_state`), so
  the earlier claim that `_recovery_resolver` categorically refuses genuine
  new-process recovery was overstated. What remains unproven is end-to-end
  Run-level recovery from a distinct OS process using the production startup
  path; the current replay test reconstructs a service object in-process.
- #947 P1 threads show no explicit disposition in the snapshot; remote
  exact-head CI remains UNVERIFIED (rollup empty at capture). Branch commits
  and the #2497 body carry no fixes/closes/resolves keywords.

## Re-check at `53a4c4d8a55d7c2c9b882e2a09c280c547c2827d` (2026-11-23)

- Re-ran the restart replay suites: `16 passed, 10 skipped`; PostgreSQL was
  unavailable in this environment, so skipped PG cases are not acceptance
  evidence.
- Targeted `ruff check` for the replay implementation/tests passed.
- No test or production-code change in this round. The remaining distinct
  process, publication-boundary, production-harness parity, queued disposition,
  #947 review-disposition, and exact-head CI gaps above are not repaired here.

## Independent verification at `3e2c77c65f05c53c70dae9cb78800502d78cc682` (2026-11-23)

Corrects the previous section: PostgreSQL **was** reachable this round
(`maistro-1064-pg`, migrated `alembic_version=069`), so the PG legs executed
for real. Executed by the verifier, not inferred:

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test
  uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py
  packages/hive-conductor/backend/tests/test_evolution_startup_wiring.py
  packages/hive-conductor/backend/tests/test_evolve_domain_retention.py
  packages/hive-conductor/backend/tests/test_evolve_domain_store.py
  packages/hive-conductor/backend/tests/test_evolution_recovery.py -q`
  -> **67 passed, 0 skipped**. Includes the Run-level PostgreSQL legs, the
  sqlite restart-replay legs, and the genuine-subprocess publication-ledger
  fence (`test_evolve_domain_store.py`: a distinct OS process INSERTED a
  battle publication and the parent process observed exactly one row and got
  FENCED on re-publication).
- Without the DSN the same five conductor files give 40 passed / 13 skipped
  (matches the driver's deterministic check), and the two replay files alone
  give the 16 passed / 10 skipped recorded above.
- `uv run ruff check .` -> passed; suite-inventory gates for
  `packages/hive-conductor/backend/tests` (4528 node IDs) and
  `packages/maistro-evolve/tests` (1017 node IDs) -> ok.
- Remote exact-head CI refresh (`gh pr view 2497`, read-only): 65 checks
  COMPLETED, 14 IN_PROGRESS (`test`, `coverage (PostgreSQL)`,
  `integration-scope`, `Gate C`, e2e, postgres pg17/pg18, container scan),
  0 observed failures -> exact-head CI remains **UNVERIFIED** until the
  rollup settles green at this SHA.
- `pulls/947/reviews` snapshot: 7/7 COMMENTED, none APPROVED -> the
  close-only review-disposition criterion is still unmet.

The delta `53a4c4d8a55d..3e2c77c65f05c` is docs-only (this note). None of the
enumerated close-only gaps — distinct-OS-process Run-level launch,
publication-boundary fault injection breadth, production-harness parity,
explicit terminal disposition for never-durable prerequisites, approved
design + #947 disposition, exact-head CI — is repaired at this head.
