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
