---
inventory-delta:
  packages/maistro-core/tests: +6
---

# Issue #1060 durable event replay

The durable-event tests now distinguish local dispatch leasing from remote
commit idempotency. They cover unsafe handlers being held, worker death before
dispatch, delivery failure during the call, remote commit before local SUCCESS
persistence, replay after an expired lease, and stable HTTP `Idempotency-Key`
headers. The post-commit crash test models a handler-owned effect store keyed by
`maistro-event:{trigger_id}:{event_id}` and proves redelivery creates one logical
effect while the local invocation eventually reaches SUCCESS.

## Delta correction (develop-sync round)

The first round recorded `+5`, counting test *functions*: four top-level tests in
`test_processing.py` plus `test_unknown_delivery_contract_defaults_unsafe` in
`test_trigger_store.py`. The gate counts collected node IDs, and the
`TriggerStore` test is parametrized over `[memory]` and `[sqlite]`, so the true
collected delta is `+6`. This note corrects the recorded number to match
reality; no test was added or removed by the correction itself.

## Develop-sync reconciliation (merges 48071677a and 8bf37764d)

Two conflict classes were resolved while syncing develop into the branch:

- Union resolutions in `events/__init__.py`, `events/processing.py`
  (`ProcessedBatch` export + replay docstring), and the SPEC (truthful
  at-least-once wording retained alongside the ADR-086 authority note).
- `trigger_store.py`: develop's `serialized_schema_upgrade` discipline now wraps
  the `ensure_schema` body, and the `delivery_contract` legacy-column migration
  runs inside it, keeping the fail-closed `UNSAFE` default for pre-existing rows.
- Develop's #1163 hole-reporting tests (`TestTheBatchReportsWhatTheLogSkipped`)
  were written before the fail-closed default existed. Their triggers now opt
  into `HandlerDeliveryContract.AT_LEAST_ONCE_IDEMPOTENT` explicitly, matching
  every other delivery test in the file, so the cursor-contiguity mechanics they
  target remain exercised. No node-count change.
- The same collision surfaced outside `tests/events` once develop was merged:
  the #1163 container-wiring cursor tests and the m8a8 replay-equivalence
  research fixtures construct triggers without a contract. They target cursor
  persistence, hole safety, and replay equivalence — not contract enforcement —
  so they now opt into `AT_LEAST_ONCE_IDEMPOTENT` explicitly as well. On pure
  develop tip all of them pass (verified side by side); only the branch's
  fail-closed default made them hold the cursor. No node-count change.

## PostgreSQL legs executed

The durable-event suite was run with `MAISTRO_TEST_DATABASE_URL` pointed at a
real PostgreSQL 18 server (`pgvector/pgvector:pg18` on 127.0.0.1:5433):
`389 passed` with zero skips in `packages/maistro-core/tests/events`, including
the previously-skipped `test_durable_store_conformance.py` claim/lease legs and
`test_container_pg_durable_events.py` wiring legs, all parametrized
`[postgres]`.

Full-suite post-merge runs (`packages/maistro-core/tests`, PG URL set):
`15445 passed, 6 failed` — the six failures are the pre-existing
`conformance/test_approval_store_conformance.py[postgres-*]` legs, which fail
identically on pure develop tip under the same server, so they are inherited
develop debt, not branch regression.

PostgreSQL trigger DDL agreement: `pg_stores.py` declares
`delivery_contract TEXT NOT NULL DEFAULT 'unsafe'` and adds it idempotently
(`ADD COLUMN IF NOT EXISTS`) in `ensure_event_schema`; the SQLite store performs
the equivalent legacy-column migration inside `serialized_schema_upgrade`. Both
backends fail closed to `unsafe` for pre-existing rows.
