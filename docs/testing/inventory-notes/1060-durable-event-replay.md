---
inventory-delta:
  packages/maistro-core/tests: +56
---

# Issue #1060 durable event replay — receipt protocol iteration

Two iterations share this note. The first (recorded `+6`) added the
`HandlerDeliveryContract` opt-in and its dispatch/crash tests. The second —
the reviewed 2026-10-04 remote-commit contract, recorded here as the branch
total `+56` — replaces that model outright with the delivery-receipt
protocol and is what ships on this branch:

- `invocations.py`: frozen `DeliveryIdentity` + digest v1 + the
  `claim`/`begin_dispatch`/`settle` writer protocol under claim-token/revision
  fencing, `HandlerCallOutcome` evidence DTOs, `unknown` status, cumulative
  `uncertain_prior_dispatch`, and the fail-closed SQLite legacy-row upgrade
  (`legacy_unkeyed_attempt` / `legacy_failed_unproven`).
- `pg_stores.py`: the same protocol on PostgreSQL, plus the idempotent
  `_SCHEMA_UPGRADES` mirror of migration `064`
  (`alembic/versions/064_durable_delivery_receipts.py`).
- `processing.py`: the receipt-reading `HTTPHandlerCaller` (persisted
  `Idempotency-Key`, digest validation, indeterminate classification for
  transport/4xx/5xx), the §4 classification table, prior-uncertainty
  classification before begin, cancellation as indeterminate, and the
  attempt-cap settlement paths.
- `trigger_store.py`: `replay_safety`/`contract_ref` enrollment with the
  fail-closed `effective_replay_safety` (a safe declaration without a
  contract ref acts unproven).

New test bodies: `TestDeliveryReceiptContract` + `TestLegacyRowMigration`
(conformance, memory/SQLite/PostgreSQL legs), the §4 classification-table
tests, `TestCrashPhases` (death before begin / after begin before HTTP /
during the in-flight marker / after remote commit before SUCCESS persistence
via `_CrashBeforeSettleStore` / after SUCCESS before cursor save, against the
atomic key+digest-committing `FakeReceiver`), `TestAttemptBudgetCannotBeEvaded`,
the receipt-reading `TestHTTPHandlerCaller` refusals, trigger-store enrollment
fail-closed tests, and migration-chain updates (schema agreement `063:064`,
installed-base chain tip `064`). The m8a8 replay-equivalence research fixtures
and the container-wiring cursor tests migrated from
`HandlerDeliveryContract.AT_LEAST_ONCE_IDEMPOTENT` to the new enrollment
fields — same node counts, no semantics change for what they measure.

## Develop-sync reconciliation (merges 48071677a and 8bf37764d)

Union resolutions in `events/__init__.py`, `events/processing.py`
(`ProcessedBatch` export + replay docstring), and the SPEC. Develop's #1163
hole-reporting tests and the container-wiring/m8a8 fixtures construct
triggers explicitly; they now opt into the idempotent enrollment so the
cursor mechanics they target remain exercised.

## PostgreSQL legs executed (this iteration)

Real PostgreSQL 18 (`pgvector/pgvector:pg18`, dedicated container), CI shape
(migrate to head first):

- `packages/maistro-core/tests/events` with `MAISTRO_REQUIRE_PG_LEGS=1`:
  448 passed including every `[postgres]` conformance leg — detached
  snapshots, one-key-winner, immutability, begin/send cap, stale CAS, delayed
  old sender, indeterminate+not_applied exhaustion, UNKNOWN visibility,
  changed-target refusal, legacy fail-closed migration, and the
  `063:064` schema-agreement render.
- `tests/migrations` against a fresh database: 168 passed (chain upgrade,
  reversibility, episodic/goal/capability migrations, event schema
  agreement, installed-base upgrades to `064`).

A non-CI ordering (events suite against a *never-migrated* database, then
`tests/migrations`) fails at migration 004 because `ensure_event_schema`
created `event_log` outside alembic — pre-existing on develop
(`_pg_pool` already called it before this branch) and an ordering CI never
runs; CI's `durable-events` job applies `alembic upgrade head` before pytest.
