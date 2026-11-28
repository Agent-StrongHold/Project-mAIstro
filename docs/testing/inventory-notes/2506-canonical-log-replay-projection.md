---
inventory-delta:
  packages/maistro-core/tests: +22
---
# 2506-canonical-log-replay-projection

Issue #2506 (M1-E1, P1): a persisted canonical EventEnvelope could remain
permanently invisible to its only durable trigger processor. `CanonicalEventPublisher.emit`
append-committed the canonical Event and then — only `if outcome.inserted` —
projected it onto the legacy bus, whose authoritative `before_handlers` bridge
appended it into the ADR-086 durable log. A durable-log append that threw
after the canonical commit was correctly surfaced (`EventSubscriberFailure`
before any trigger could claim success), but the canonical fact was already
durable, the retry emission returned `inserted=False` and suppressed the bus
forever, and `Container.process_durable_events` scanned only the durable log:
neither restart nor the existing trigger replay cursor could repair the
missing occurrence.

**What changed (behaviour).** Canonical Envelope -> ADR-086 log is now a
replayable, idempotent projection; the legacy bus stays at-most-once
compatibility delivery and is never the only durable trigger ingress. No new
event identity, no new processing lifecycle:

- **Log-level source dedupe.** `event_log` gains nullable `source_event_id`
  with a unique index (NULLs distinct on PostgreSQL and SQLite, so legacy and
  non-canonical rows never collide). `EventLogStore.append(source_event_id=...)`
  is idempotent: an append naming a source id already in the log returns the
  existing row instead of writing a second occurrence. The bridge
  (`append_from_bus_event`) sets it from the projection's canonical-identity
  payload metadata, so the success path keys rows too. Migration `074`.
- **Stream registration at the canonical watermark.** `CanonicalEventPublisher`
  gains an optional `projection_registry`; the container wires it, and every
  emit registers the event's stream BEFORE the canonical append, positioned at
  the store's current `stream_watermark` (new capability on all three
  canonical stores). Registration-before-append means a bridge failure or a
  process crash after the canonical commit always leaves the Event inside a
  tracked, scan-reachable range, and retained pre-projection history is never
  rescanned or re-projected.
- **The replay projector.** `project_canonical_events` (in
  `events/processing.py`, the ADR-086 processing module) scans each registered
  stream above its cursor and confirms every event's durable-log row through
  the idempotent append — a row the bridge already wrote comes back unchanged,
  a missing row is written with exactly the mapping the bridge uses
  (`canonical_log_append_kwargs`), and a concurrent duplicate append converges
  on the one row. Per-stream claim leases + fencing tokens (the same shape as
  the legacy bridge's `consumer_cursors` mechanics) make two replicas share
  delivery; positions advance monotonically only past confirmed sequences.
  Retryable append failures record bounded attempts with backoff and hold the
  stream below the failure; past the bound the event is dead-lettered — a
  visible terminal disposition (`poisoned_records`) that releases the stream.
  Canonical sequences are contiguous by construction (the stream watermark
  advances only in the appending transaction), so an aborted envelope append
  can never leave a sequence hole for the cursor to skip.
- **Ordinary-tick healing only.** `Container.process_durable_events` runs the
  projection pass before the legacy pass, under its own leases. There is no
  repair entry point, no test-only append, no direct bus emit in the healing
  path.

**Tests (+19, `packages/maistro-core/tests`).**
`tests/events/test_canonical_projection.py` (+14): the bridge-failure heal
(identity + Workspace sequence preserved in the healed row), retry-emission
after failure cannot skip delivery, log-commit-before-cursor never duplicates,
watermark registration excludes retained history, poison dead-letter releases
its stream (bounded attempts, visible disposition, later events flow),
backoff holds the stream for exactly the backoff window, two replicas share
one stream lease and progress after expiry with fenced stale writes refused,
concurrent ticks converge on one row, and the negative shape — a publisher
without a projection registry cannot heal, so reverting the projector to
`if outcome.inserted: legacy_bus.emit(...)` fails these tests — plus SQLite
backend round-trips, the in-place `event_log` column upgrade, and two
in-memory `create_container` tests forcing the bridge append to throw after
the canonical commit (one canonical event, zero log rows, no receipt, no
bus-trigger fire; then the healed ordinary tick delivers exactly one row and
one receipt).

`tests/events/test_canonical_projection_pg.py` (+5, PostgreSQL-gated, the
issue's live-server criteria): the CHECK-constraint fault on `event_log`
forced after the canonical commit across two independent containers (criterion
1 and 2: one canonical event, zero log rows, no handler Invocation, no
success-shaped claim; heal; only `process_durable_events` on the second
container; exactly one log occurrence and one receipt referencing the original
event identity and Workspace sequence); concurrent ticks of two replicas
converging on one occurrence and one receipt (criterion 3); an aborted
canonical append reusing — never skipping — its sequence with all committed
events projected contiguously (criterion 4); projection-store claim
expiry/takeover/fencing on a real server; and the log-level dedupe converging
bridge and projector across connections.

**Existing-test integration.** `test_container_pg_durable_events.py`'s
absolute-id math (TRUNCATE ... RESTART IDENTITY) now truncates the canonical
projection state too: a surviving stream registration would re-project its
canonical Event as a fresh `event_log` row on the next tick and shift every id
below the cursor by one. Assertions are unchanged — the freshness premise got
wider, not weaker.

**Legs.** `packages/maistro-core/tests/events` over real PostgreSQL (docker
`postgres:17`, `MAISTRO_TEST_DATABASE_URL`): 549 passed / 5 skipped, run twice
for order stability. `tests/migrations/test_event_schema_agreement.py` 5
passed and `tests/migrations/test_migration_chain.py` 18 passed over docker
`pgvector:pg17` (revision `074` renders and applies; the chain test's
`EXPECTED_TABLES` gains the two projection tables). `test_container_wiring.py`,
`test_wiring.py`, `test_recovery_event_pipeline.py`,
`test_event_authority_contract.py`, `test_canonical_event_publisher.py`,
`test_event_projection_dedupe.py`: 96 passed. Gates at CI's exact arguments:
vulture per-identity ledger clean (1217 -> 1217, no ledger edits — the
projection uses the established explicit-reference idiom and its own
`poisoned_at`/`poisoned_records` names so no banked identity moves), radon
clean, promotion surface ok, reachability ok, wiring-reads ok,
durable-table inventory ok (131 tables; the two new tables recorded as
`undecided` bounded-state rows, same shape as `consumer_cursors`), ruff check
+ format clean, mypy clean on `events` and `container.py` (only the
pre-existing optional-extra import notes remain).

**Repair round (chain-tip pins, CI evidence).** The candidate head's first
merge-queue evaluation failed `integration-scope`, whose required producer
`postgres (pg18)` (and `pg17`, plus the `test` and `coverage (PostgreSQL)`
jobs) concluded failure on exactly one root cause: three pre-existing
migration suites pin the Alembic chain tip at `073`, and this branch appends
`074` (CI: `assert {'074'} == {'073'}` /
`assert ['074'] == ['073']` /
`upgrade head left the base at '074', head is ['074']`). The pins are the
established convention — each of `068`-`073` landed by moving them — so the
repair is the same lockstep move, with no behaviour change:
`test_legacy_principal_ownership_live.py` head pin `073` -> `074` (comment
extended), `test_goal_installed_base_upgrade.py` `CHAIN_HEAD = "073"` ->
`"074"` plus its head-parent assertion `072` -> `073` and both comments,
`test_capability_invocation_effect_index_migration.py` `get_heads() == ["073"]`
-> `["074"]` (the landed-revision identity assertions for `064`-`073` stay —
they pin history, not the tip). No test added or removed anywhere, so the
`inventory-delta` above is unchanged. Reproduced and re-proven first-hand on
docker `pgvector/pgvector:pg18` (`MAISTRO_TEST_DATABASE_URL`, port 55432):
the three live-PG failures reproduced at the unfixed head, then
`tests/migrations` **174 passed** with the PG env (CI's coverage-PG leg was
162 passed / 6 failed on the same suite set), `test_migration_chain.py` 18
passed, `test_legacy_principal_ownership_live.py` 3 passed,
`test_goal_installed_base_upgrade.py` + `test_capability_invocation_effect_index_migration.py`
10 passed, `alembic downgrade base` + `upgrade head` ending at stamp `074`,
`tests/` (CI `test` job's env: no database) **6474 passed / 141 skipped**
(CI was 6472 passed / 2 failed), `packages/maistro-core/tests/events` 551
passed / 4 skipped with `MAISTRO_REQUIRE_PG_LEGS=1` (all 20 projection tests
green, 5 over real PG), `tests/migrations/test_event_schema_agreement.py` 5
passed, ruff check + format clean repo-wide. The criterion-5 regression pin
was exercised directly: with the container's projection pass mutated out
("solely `if outcome.inserted: legacy_bus.emit(...)`"), both heal tests fail
(`test_container_heals_a_failed_bridge_append_through_the_ordinary_tick`,
`test_bridge_failure_after_canonical_commit_heals_across_two_containers`);
restored byte-exact, both pass. `docker-build` concluded success on the same
head, and `durable-events`/`wheel-imports`/`hive-conductor-e2e-ui` were
already green — the stale pins were the only red evidence.

**Salvage round 2 (external writer, worktree-found; preserved and validated).**
A second batch of #2506-review changes appeared uncommitted in the worktree
while this repair was running (not this worker's edits; preserved per the
salvage rule): `wire_canonical_projection` now selects the projection backend
from the canonical EventStore in hand — `PgEventStore.pool`,
`SqliteEventStore.conn` (new accessors), anything else in memory beside the
store — instead of separately supplied `pg_pool`/`db_pool`. Rationale
(#2506 review): a container can be handed a composed `effect_context` whose
event authority is not the container's own database; an injected context
skips `wire_canonical_events`' schema work, so pool-based selection built the
registry on a database with no `canonical_event_stream_watermarks` table
(every emission failing at registration) or read another database's
watermark. Three tests join (+3, `packages/maistro-core/tests`, delta above
updated): the SQLite store composes the projection on its own connection, a
non-durable store gets an in-memory registry beside itself, and the injected
`effect_context` regression end-to-end through `create_container` (emission
succeeds where pool-based selection failed every emit at registration). The
aborted-append PG test follows the new store-only signature. Validated at
this tree on docker `pgvector/pgvector:pg18` (schema dropped, `alembic
upgrade head` applied first, then suites): `packages/maistro-core/tests/events`
**554 passed / 4 skipped** (was 551 + 3 new), mypy clean on
`packages/maistro-core/src` (860 files), ruff check + format clean repo-wide,
and the repair-round suites re-proven over the changed `container.py`:
legacy-principal live + both chain-tip pin files + `test_container_postgres`
28 passed. Note: the purge fixture in `test_envelope.py` truncates tables
from the full migrated chain, so the events directory must run after
`alembic upgrade head` (CI's durable-events job orders it the same way); out
of that order it errors on `quota_invocation_evidence` — environmental, not
a regression.
