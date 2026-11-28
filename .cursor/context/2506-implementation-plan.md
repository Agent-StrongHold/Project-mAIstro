# #2506 implementation plan (checkpoint)

Lane L2506, worktree /home/dev/Git/wt/auto-2506, base 7eacf6ebe4. Fresh implement (prior attempt died at startup, no salvage needed).

## Failure being fixed
`CanonicalEventPublisher.emit` = canonical `append_with_disposition` then, only `if outcome.inserted`,
`legacy_bus.emit(project)`; the bus bridge `_persist_bus_event` (subscribed `before_handlers=True`)
appends the projection into the ADR-086 `durable_event_log`. If that append throws after the canonical
append committed, the retry (`inserted=False`) suppresses the bridge forever -> persisted canonical
event permanently invisible to its only durable trigger processor.

## Design (chosen: bounded canonical-EventStore cursor projector)
1. **Log-level dedupe**: `event_log.source_event_id TEXT` (nullable, plain UNIQUE index; NULLs distinct
   in PG + SQLite) on all three backends. `EventLogStore.append(..., source_event_id=None)` is
   idempotent per source id: returns the existing row instead of raising. The bridge
   (`append_from_bus_event`) sets it from `payload[CANONICAL_EVENT_METADATA]["event_id"]`; the
   projector sets it too. Exactly one log row per canonical event across both ingress paths, atomically.
2. **Stream registration at watermark**: publisher gains optional `projection_registry`
   (`register_stream(stream_id)`), called BEFORE the canonical append; absent streams are inserted at
   the canonical store's current `stream_watermark` so retained pre-projection history is never
   rescanned/duplicated. New `EventStreamWatermarkReader` capability on the 3 canonical stores.
3. **Projector tick** `project_canonical_events(...)` in `events/processing.py` (no new source module —
   promotion-surface gate): per registered stream, claim a leased+fenced cursor (CursorLease shape,
   monotonic advance), scan `list_stream(after=position)`, honor backoff for retryable append
   failures, dead-letter past a bounded attempt count (terminal disposition releases the stream),
   idempotent appends make revisits safe. Two-replica delivery = per-stream lease + fencing token.
4. **Durable failure bookkeeping**: `canonical_projection_failures` table (3 backends).
   Projection cursor table: `canonical_event_projection_streams` (3 backends).
5. **Production tick**: `Container.process_durable_events` runs the projection pass first, then the
   existing legacy processing — the repair is reachable from the ordinary production tick only.
   No new lifecycle, no new event identity.

## Files (frozen snapshot)
- EDIT envelope.py (watermark reader), durable_log.py (source_event_id + sqlite upgrade + bridge mapping),
  pg_stores.py (schema + PgEventLog dedupe + 2 PG stores), processing.py (projector + protocols +
  in-memory/SQLite stores), publisher.py (registry seam), wiring.py (wire_canonical_projection),
  container.py (field, wiring, tick pass), events/__init__.py (exports)
- ADD alembic/versions/074_canonical_event_projection.py
- EDIT tests/migrations/test_event_schema_agreement.py (EVENT_TABLES + range), quality/durable-table-retention.json (2 new table entries, `undecided` like consumer_cursors precedent — functional inventory, not a ratchet ledger)
- ADD tests: packages/maistro-core/tests/events/test_canonical_projection.py (in-memory+sqlite),
  test_canonical_projection_pg.py (real PG, MAISTRO_TEST_DATABASE_URL-gated)
- ADD docs/testing/inventory-notes/2506-canonical-log-replay-projection.md

## Gates to run
ruff check/format; pytest events dir + test_container_wiring.py; check-durable-table-inventory;
check-promotion-surface; check-suite-inventory; schema agreement + migration chain vs live PG (docker postgres:17).

## Acceptance mapping
1. PG fault (CHECK constraint on event_log) after canonical commit -> 1 canonical row, 0 log rows, 0 receipts, bus trigger never fires (PG test phase 1).
2. Two containers over one PG DB: emit+fail in A, heal, only `process_durable_events` in B -> exactly 1 log row + 1 receipt carrying original event_id/workspace sequence (PG test phase 2/3).
3. Duplicate emission after failure cannot skip delivery; log-commit-before-cursor => no duplicate row (unit tests); poison dead-letter releases stream; identity stable (unit + PG).
4. Aborted envelope append cannot skip committed events (PG contiguity test); two replicas share claim, progress after lease expiry (unit + PG store test).
5. Tests fail if projector removed (revert to bridge-only => no healing) — negative-shape test + core tests.
6. CI/live evidence: local run of the CI durable-events battery against real PG; live evidence recorded in job notes.
