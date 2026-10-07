---
inventory-delta:
  packages/maistro-server/tests: +1
---

# auto-72 verifier repair

Post-merge verification against a real pgvector:pg18 (chain applied 001 -> 039)
found four stale maistro-server tests contradicting production behavior this
branch deliberately introduced; production code is unchanged by this repair.

- `test_strike_tracker_health.py`: two readiness tests asserted the pre-#72
  exact dict shape without the `durable` key. Updated to expect `durable`, and
  added `test_readiness_reports_postgres_strike_tracker_as_durable` pinning that
  a wired `PgStrikeTracker` reports `durable: true` (the restart-survival half
  of the truthfulness contract; constructed without a server — the diagnostic
  inspects the tracker, it does not use it).
- `test_main.py` `TestLifespan::test_the_lifespan_says_which_run_store_is_live`:
  the lifespan now owns the usage-log flush at shutdown (#72/#1204 write-behind
  contract), so the mocked container gained async `flush_usage_log`/`aclose`
  and the test asserts both are awaited on both run-store branches. The mocked
  logger gained `aerror` to cover the flush-failure log path.

Validation: maistro-server suite 365 passed; persistence 613 passed against
migrated PostgreSQL; migration-chain 93 passed live; strike/elevation/quota
conformance 149 passed including the 19 PostgreSQL-leg tests; events 382
passed; ruff check/format clean; mypy (documented package list) clean.
Known pre-existing, out-of-scope: `security/test_log_redaction.py::
test_install_is_idempotent` fails identically on develop base 1dea30df under
pytest 9 (its capture handlers attach after the fixture installs redaction —
handlers-added-later is outside `install_log_redaction`'s documented contract).

## Re-verification at head bba39fad7 against develop base 60862b6c

Independent re-run of the full battery on a fresh empty pgvector:pg18 database
(`verify72`, chain 001 -> 039 applied, single head `039`):

- persistence + quota + elevation-durable + container-wiring: 760 passed,
  0 skipped; strikes battery 69 passed, 0 skipped; `tests/migrations` 93
  passed live; maistro-server 365 passed; ruff/mypy/check-doc-links/
  check-suite-inventory clean.
- Two environment pitfalls worth recording for future lanes, both proven by
  controlled re-runs (neither is a product defect):
  1. `security/test_strike_tracker_conformance.py` gates its PostgreSQL leg on
     `MAISTRO_TEST_DATABASE_URL`, *not* `MAISTRO_TEST_PG_DSN`. Exporting only
     the latter silently skips 19 tests (this is the same symptom as the
     original "19 skipped" finding). `MAISTRO_REQUIRE_PG_LEGS` turns the skip
     into a hard failure for CI (the `strike-ladder` job sets it).
  2. `tests/migrations` fixtures build the alembic subprocess env from `DB_*`
     variables, but `resolve_database_url` gives `DATABASE_URL` precedence.
     Exporting `DATABASE_URL` alongside them redirects the subprocess to the
     other database (scratch DB stays empty; symptoms like "learnings has no
     embedding column"). Run this suite with `DATABASE_URL` unset.
- The `test_log_redaction.py::test_install_is_idempotent` failure reproduces
  identically at this head; the test file and the redaction module are
  byte-identical between this branch and develop, and neither is touched by
  the branch diff — confirmed pre-existing, still out of #72 scope.
- No production code and no tests changed by this re-verification; no
  inventory delta.

## CI-repair round at head 63268c635 (vulture exact-debt ledger)

The only red gate left at this head was `scripts/check-vulture-baseline.py`
(exit 1): five recorded identities no longer produce findings in the combined
`packages/*/src` scan, and the script requires fixed debt to be pruned.
Verified each before amending `quality/vulture-baseline.json` (5 lines removed,
no other edits):

- `maistro/quota/sqlite_usage_log.py::unused method 'restore'` — genuinely
  fixed by #72: `Container._wire_usage_log` now calls `persistence.restore()`
  (container.py) and the module docstring shows the production call shape.
- four `maistro_rsi` `...::unused method 'restore'` entries — still unused
  package-locally (standalone `uv run vulture packages/maistro-rsi/src` still
  reports them), but eliminated from the combined scan because vulture is
  name-based per scan and the container's `.restore()` reference now whitelists
  every method of that name. Pruned per the ledger's per-scan-identity
  contract; if that reference ever disappears the ratchet re-flags them.

Full independent battery re-run against a fresh pgvector:pg18 (`verify72`,
chain 001 -> 039 applied, single head `039`, both `MAISTRO_TEST_DATABASE_URL`
and `MAISTRO_TEST_PG_DSN` exported, `DATABASE_URL` unset):
persistence+quota+elevation+container-wiring 760 passed / 0 skipped; security
1271 passed (PG strike legs ran, no skips; the sole failure is the documented
pre-existing pytest-9 `test_log_redaction.py::test_install_is_idempotent`, whose
test and module are byte-identical to origin/develop per empty `git diff`);
tests/migrations 93 passed live; maistro-server 365 passed; ruff check/format,
mypy (711 files), check-vulture-baseline, check-doc-links,
check-suite-inventory, check-deployment-claims, check-compose-secrets all
exit 0. The prior run's deterministic-check logs were absent from the job
directory; every claim above was re-executed in this round. Scratch analysis
file from an earlier run preserved at the job directory as
`incoming-ISSUES_SUMMARY.md`. No test additions: no inventory delta.
