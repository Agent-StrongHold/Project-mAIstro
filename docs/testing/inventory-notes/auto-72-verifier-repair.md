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
