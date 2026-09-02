---
inventory-delta:
  packages/maistro-core/tests: +30
---

# M1 #61 canonical Event-envelope convergence inventory

Base audited: `develop@93401f3485ebb815dedc1b0c6b7ad1d7e767fa32`.

## Canonical authority already present on develop

`maistro.events.envelope.EventEnvelope` is the canonical universal Event identity and correlation schema. `InMemoryEventStore` and `SqliteEventStore` already assign sequence numbers per canonical stream, with existing evidence in `test_event_persistence_evidence.py` that a Workspace sequence survives a SQLite restart and serializes across independent store connections.

This branch adds the missing PostgreSQL implementation of that same `EventStore` contract and migration `030`. PostgreSQL allocation is serialized per canonical stream and retries are idempotent by canonical `event_id`; focused tests cover restart, concurrent Workspace writers, and concurrent duplicate delivery.

## Production producer and consumer inventory

- **Run recovery:** `AttemptLifecycleReconciler` is a real producer. On develop, `runs.recovery_events` minted the legacy `events.bus.Event`, and `Container.recover_abandoned_attempts()` injected the legacy `EventBus`. This branch removes universal identity from the package-local recovery fact and supplies `CanonicalRecoveryEventSink`, which resolves the canonical Run scope and envelopes the domain payload. `test_recovery_event_pipeline.py` proves the real reconciler producer can flow through the canonical durable SQLite store before a compatibility trigger consumer observes it, and that the canonical event survives reopen.
- **Legacy trigger bus / ADR-086 delivery log:** `EventBus`, `LoggedEvent`, trigger definitions and handler invocations remain compatibility delivery infrastructure. `EventBus` is now an explicit projection adapter rather than a type that package facts must imitate. `CanonicalEventPublisher` persists the canonical envelope first and only then projects its canonical identity and Workspace sequence to the legacy bus. Full retirement of the ADR-086 delivery subsystem is not claimed here.
- **Governed Invocation:** `capabilities/governed_invocation.py` already constructs canonical `EventEnvelope` records. Its production activation is owned by active #55 work and is intentionally untouched.
- **Event outbox:** `events/outbox.py` is canonical-envelope aware, but repository search found no production construction/caller outside its module/tests. This branch does not manufacture traffic to make it look reachable.
- **Execution Runtime:** `PythonExecutionRuntime` is real production mechanics and still exposes `RuntimeEventEnvelope.sequence`. Repository search found production Runtime construction but no production `.emit()` callers. The convergence contract therefore exposes this counter as explicitly declared transport metadata instead of inventing events or changing Runtime semantics without a consumer.
- **Hive DAG run history:** `DagRunEvent` and the current Hive DAG run/history surfaces remain product-local event projections. They overlap active DAG/Workspace/Conductor convergence work, including #770 and #797, and are recorded as dependencies instead of being edited here.

## Collision boundary honored

No Builders, Evolve, Canvas, Turing, scheduler, DAG product implementation, Invocation implementation, canonical Run/Graph store, shared quality ratchet, or workflow topology is modified. Active product lanes found during the live ownership audit include Builders #744, Evolve #733, Canvas #746, scheduler #759, DAG/Workspace #770, Turing #784, Conductor durability #629, and cross-product parity #797. #135 is historical and owns PostgreSQL persistence for the legacy ADR-086 `LoggedEvent`/trigger/invocation subsystem, not the canonical `EventEnvelope` store.

## Discriminatory tests

The +11 collected tests are all new event-convergence evidence: 3 publisher tests, 4 authority-contract tests, 3 PostgreSQL canonical-store tests, and 1 real recovery-producer pipeline test. The existing 7 recovery-event characterization tests are rewritten against the canonical adapter with no collected-count change.

## Diff-coverage follow-up (+19)

The follow-up coverage-closure commit adds 19 more `maistro-core` tests, bringing this branch's recorded delta to +30 with no node ID removed:

- **Publisher (2):** `emit` refuses a fact that cannot project itself, and refuses a projection that is not a legacy event.
- **Authority contract (6):** the publisher exposes its single sequence authority; a legacy projection carries a declared category; an unknown category name falls back to system; plain class annotations are inspected for authority fields; instances are inspected through their type; a plain projection without authority fields is metadata-only.
- **Canonical store (3):** `ensure_schema` locks then creates the canonical table; `append` refuses an envelope that already carries a sequence; `get` returns `None` for an unknown event id.
- **PostgreSQL envelope (2):** a stored row round-trips with object jsonb columns; a degenerate `list_stream` limit issues no query.
- **Wiring (5):** without pools the in-memory store is the authority; a supplied db pool selects the SQLite store after its schema; a supplied pg pool selects the PostgreSQL store after its schema; a pg pool takes precedence over a sqlite connection; the wired publisher persists before notifying legacy consumers.
- **Recovery (1):** a recovery fact for an unknown run is refused.

`test_event_authority_contract.py` plants a package-local object that owns `event_id`, `sequence`, and `correlation_id` and proves the convergence contract rejects it. The same test proves `RecoveryDispositionEvent` owns none of those universal fields, while legacy `Event` and `RuntimeEventEnvelope.sequence` remain visible only through explicit metadata dispositions.

## Remaining #61 work

This slice does **not** close #61. Current `Container.recover_abandoned_attempts()` still injects the compatibility `EventBus`; the branch keeps that path behaviorally valid through the explicit recovery projection, but does not claim the shipped Container has switched that producer to `CanonicalEventPublisher`. Product-owned event families listed above also remain outstanding until their active convergence lanes land or expose a collision-free adapter seam.

The independently mergeable contribution here is the common canonical PostgreSQL Event store, persist-first publisher, explicit adapter/authority contract, recovery-domain de-duplication, and producer-to-durable-to-consumer proof. #61 should remain open until the remaining reachable production wiring and product-family migrations are verified on then-current `develop`.
