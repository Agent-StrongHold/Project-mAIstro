---
id: SPEC-070226-b234
title: "Events, triggers, and the reactor: durable at-least-once replay"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-02
substrate:
  - maistro-engine#ADR-037
implements:
  - maistro-engine#ADR-086
related:
  - maistro-engine#ADR-082
  - maistro-engine#ADR-086
  - maistro-engine#SPEC-013
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
tests:
  - packages/maistro-core/tests/events/test_durable_log.py
  - packages/maistro-core/tests/events/test_trigger_store.py
  - packages/maistro-core/tests/events/test_invocations.py
  - packages/maistro-core/tests/events/test_processing.py
ac-modules:
  AC-1: maistro.events.durable_log
  AC-2: maistro.events.trigger_store
  AC-3: maistro.events.invocations
  AC-4: maistro.events.processing
layer: Observability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-26
    reason: >-
      Governing-authority reconciliation (#374): the only decision this SPEC implements is itself not an accepted, shipped decision, and an accepted plan cannot rest on one, so the SPEC returns to Proposed while the decision stays named in implements: and stays marked in prose as design context, not shipped authority.
---

# SPEC-070226-b234: Events, triggers, and the reactor — durable at-least-once replay

## Context

ADR-086 proposes a durable event log (PostgreSQL table of immutable events) and trigger+handler
model: operators define triggers ("on agent.delegated, run X"), the reactor processes events,
and handlers are replayed durably (at-least-once; effect idempotency is handler-owned, with no
lost events on crash). ADR-086 remains Proposed and is retained as design context only; it is not
shipped authority for this SPEC — the operative authority is this SPEC under its Accepted
substrate (ADR-037).

The 1kHz reactor loop (SPEC-013) currently emits events in-memory; this SPEC persists them.

## Goals

- Durable event log (all events persisted to PostgreSQL).
- Trigger definitions (declarative; stored in config or registry).
- Event processing and handler invocation (async queue, batched).
- At-least-once replay with truthful effect semantics: automatic replay requires a
  handler-owned durable idempotency key; the local Invocation row only deduplicates dispatch.
- Audit trail (all events searchable, never deleted).

## Non-goals

- Event streaming to external systems (Kafka, Pub/Sub; Phase 2).
- Learned trigger optimization (operator-configured for Phase 1).

## Decision

> **Implementation note (2026-07-02):** implemented as protocol-driven stores in
> `packages/maistro-core/src/maistro/events/` (per maistro-core DI conventions) rather than
> the raw PostgreSQL DDL originally sketched here. Each store has an in-memory implementation
> and an aiosqlite-backed one (mirroring `maistro.persistence.sqlite_*`); a PostgreSQL
> implementation can be added under `maistro.persistence` later without touching the loop.
> Modules:
>
> - `maistro/events/durable_log.py` — `LoggedEvent`, `EventLogStore` protocol (append-only,
>   query by type/time window, keyset pagination via `after_id`/`limit`),
>   `InMemoryEventLog`, `SqliteEventLog`.
> - `maistro/events/trigger_store.py` — `TriggerDefinition` (with #1060 recipient
>   enrollment: `replay_safety` ∈ unproven/idempotent/read_only plus the
>   operator-approved `contract_ref`; a safe declaration without a contract ref
>   reads as unproven — fail-closed), `pattern_matches()` (dot-segmented
>   glob: `agent.*` matches `agent.created`, not `task.created` and not
>   `agent.task.created`), `TriggerStore` protocol, `InMemoryTriggerStore`,
>   `SqliteTriggerStore`.
> - `maistro/events/invocations.py` — `HandlerInvocation` with `(trigger_id, event_id)`
>   dispatch key, `InvocationStatus` (pending/success/failed/retrying/unknown),
>   `MAX_ATTEMPTS = 3`, frozen `DeliveryIdentity` and `HandlerCallOutcome` DTOs,
>   digest v1, and the `InvocationStore` protocol whose writer half is
>   `claim`/`begin_dispatch`/`settle` under claim-token/revision fencing
>   (#1060 §3): `claim` prepares one winning receipt and allocates the delivery
>   key exactly once; `begin_dispatch` is the sole budget-consuming permission
>   to send; `settle` validates the structural/evidence invariants.
>   In-memory, SQLite and PostgreSQL (`pg_stores.py`, migration `064`) implement
>   the same semantics, and pre-contract rows upgrade fail-closed to `unknown`.
> - `maistro/events/processing.py` — `HandlerCaller` protocol (injected async
>   callable returning `HandlerCallOutcome | None`; `None` is the established
>   acknowledgment), `HTTPHandlerCaller` (reads the prepared receipt, refuses
>   absent/mismatched/not-in-dispatch receipts, snapshots target/body before
>   awaits, validates the digest, sends the persisted delivery key as
>   `Idempotency-Key`, and classifies transport/5xx/4xx as indeterminate —
>   never not_applied), and the pure async `process_events()` loop ticked by
>   the reactor with injected stores. The classification table (#1060 §4)
>   retries only proven not-applied calls, or indeterminate ones under a
>   currently valid idempotent/read_only contract; everything else possibly
>   applied settles UNKNOWN — visible, cursor-settled, never auto-replayed.
>
> Deviations from the original text: `process_events()` is cursor-based (`after_id` in,
> new cursor out) — the cursor only advances past an event once all matching triggers are
> terminal, so retries happen on subsequent ticks and a crash (lost cursor) replays from an
> older position. That redelivery is effect-safe only for a recipient whose currently valid
> enrollment (idempotent/read_only + contract ref) matches the receipt's frozen identity; the
> local invocation row alone is not proof. Retry backoff is not
> `sleep`-based inside the loop; it falls out
> of the tick cadence (the reactor/caller owns pacing). On permanent failure a
> `handler.failed` event is appended to the log (source `reactor`) instead of an in-memory
> `emit()`. The reference SQL/pseudocode below is kept for context; SQLite schemas in the
> modules are the concrete form.

### Event log schema (original PostgreSQL sketch — see implementation note)

```sql
CREATE TABLE event_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(255),  -- "agent.created", "task.completed", etc.
    entity_type VARCHAR(100),  -- "agent", "task", "design"
    entity_id VARCHAR(255),
    payload JSONB,  -- event-specific data
    source VARCHAR(100),  -- "core", "security", "resilience"
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX (event_type, created_at)
);

CREATE TABLE trigger_definitions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    event_pattern VARCHAR(255),  -- glob: "agent.*" matches "agent.created", "agent.delegated"
    handler_url VARCHAR(1024),  -- HTTP endpoint to call
    enabled BOOLEAN DEFAULT true
);

CREATE TABLE handler_invocations (
    id SERIAL PRIMARY KEY,
    trigger_id INTEGER,
    event_id INTEGER,
    status ENUM('pending', 'success', 'failed', 'retrying'),
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (trigger_id, event_id)  -- idempotency key
);
```

### Reactor event processing (historical sketch, not the safety contract)

The original sketch below omits the delivery contract and is retained only to
show the pre-implementation shape. The normative rule is the Delivery and
effect contract above: local status is not evidence of a remote commit.

```python
class Reactor:
    """1kHz loop that processes events and invokes handlers."""
    
    async def process_events(self):
        """Called every 1ms by the event loop."""
        # Fetch unprocessed events
        pending_events = await event_log.get_pending(limit=100)
        
        for event in pending_events:
            # Find triggers that match
            triggers = await trigger_store.get_matching(event.event_type)
            
            for trigger in triggers:
                # Check if already invoked (idempotency)
                invocation = await invocation_store.get(trigger.id, event.id)
                if invocation and invocation.status == "success":
                    continue
                
                # Invoke handler (async, with retry)
                if not invocation:
                    invocation = await invocation_store.create(trigger.id, event.id)
                
                try:
                    await self.invoke_handler(trigger, event)
                    invocation.status = "success"
                except Exception as e:
                    invocation.attempts += 1
                    invocation.last_error = str(e)
                    if invocation.attempts < 3:
                        invocation.status = "retrying"
                    else:
                        invocation.status = "failed"
                        emit("handler.failed", trigger=trigger.name, event=event.id)
                
                await invocation_store.save(invocation)
    
    async def invoke_handler(self, trigger: TriggerDefinition, event: Event):
        """HTTP POST the event to the handler endpoint."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                trigger.handler_url,
                json=event.to_dict(),
                timeout=5.0
            )
            if response.status_code >= 400:
                raise HTTPError(f"{response.status_code}: {response.text}")
```

### Trigger definitions (YAML)

```yaml
triggers:
  - name: "log-delegations"
    event_pattern: "agent.delegated"
    handler_url: "http://localhost:8000/handlers/log"
    # #1060 recipient enrollment: idempotent requires the operator-approved,
    # versioned contract ref naming the key+effect commit protocol.
    replay_safety: "idempotent"
    contract_ref: "log-handler-contract-v3"

  - name: "update-cache-on-memory-write"
    event_pattern: "memory.written"
    handler_url: "http://localhost:8000/handlers/cache-update"
    replay_safety: "read_only"  # applies no external effect; still needs a contract ref

  - name: "notify-on-task-failure"
    event_pattern: "task.failed"
    handler_url: "http://localhost:8000/handlers/notify"
    # no enrollment: unproven — one-shot delivery only, never auto-replayed
```

### Delivery and effect contract (#1060)

The `(trigger_id, event_id)` receipt and its lease ensure exactly one active MAIstro
**dispatcher**, never exactly one remote effect. Each receipt freezes a
`DeliveryIdentity` (handler URL, request digest v1, replay safety, contract
ref) and allocates a full random `delivery_key` exactly once, on its first
prepared claim; the key survives retries and restarts, and the HTTP send
carries it as `Idempotency-Key` on every attempt. An idempotent recipient must
persist that key atomically with its own effect; if a worker dies after that
commit but before the local SUCCESS save, redelivery sends the same key and the
recipient returns its stored result / no-ops.

Automatic replay after an *uncertain* send (transport loss, 5xx, arbitrary
exception, expired in-flight marker, or a crashed worker's folded marker) is
admitted only while the trigger's **currently valid** `idempotent`/`read_only`
enrollment matches the receipt's frozen identity. An unproven recipient keeps
its one-shot attempt: it is never automatically redelivered after an
uncertain send. The truthful terminal state for unresolved uncertainty is
`UNKNOWN` — cursor-settled and visible for reconciliation, not silently
retried and not a FAILED that would claim the effect never applied. A local
identity/config refusal before any send settles FAILED (or UNKNOWN once a
possibly-applied call exists); a proven not-applied call retries while budget
remains and FAILED at the cap. Pre-contract rows upgrade fail-closed
(`legacy_unkeyed_attempt` / `legacy_failed_unproven`), and canonical
side-effect reconciliation stays under the governed Invocation seam (#55).
HTTP 2xx does not make the remote effect and local SUCCESS write atomic.

## Acceptance criteria

```gherkin
Feature: Durable event log with truthful at-least-once replay

  @AC-1
  Scenario Outline: Every emitted event is persisted before any handler sees it
    Given an event log backed by <backend>
    When a sequence of events is emitted
    Then every event is readable from the log
    And each carries an append-assigned id greater than the one before it
    And reads return them in ascending id order

    Examples:
      | backend   |
      | in-memory |
      | sqlite    |

  @AC-2
  Scenario Outline: Trigger patterns match on segments, not substrings
    Given a trigger registered for pattern "<pattern>"
    When an event of type "<event_type>" is emitted
    Then the trigger <outcome>

    Examples:
      | pattern | event_type        | outcome        |
      | agent.* | agent.created     | fires          |
      | agent.* | task.created      | does not fire  |
      | agent.* | agent.sub.created | does not fire  |

  @AC-3
  Scenario: An idempotent handler applies one logical effect across a crash
    Given an enrolled idempotent trigger whose handler stores the delivery key with its effect
    When the process dies after the handler commits but before SUCCESS persistence
    And the processor runs again after the dispatch lease expires
    Then the handler may receive the event again under the same persisted key
    And its effect store observes one logical effect
    And the invocation record eventually names its terminal status

  @AC-4
  Scenario: A failing handler is retried three times and then given up on
    Given a handler whose calls are proven not-applied on every attempt
    When the processor runs until the invocation settles
    Then the handler is called no more than 3 times in total
    And the invocation ends in a terminal failed status
    And the backoff is paced by reactor ticks rather than an in-loop sleep

  @AC-6
  Scenario: An unproven handler's uncertain send is never automatically replayed
    Given a trigger with no replay-safety enrollment whose send loses the response
    When the processor settles the receipt and ticks again
    Then the receipt is UNKNOWN, visible and cursor-settled
    And the handler is not called a second time
    And a later idempotent trigger's events still advance past it

  @AC-5
  Scenario: Events are queryable over HTTP
    Given events in the log spanning several types and times
    When a client requests GET /events with event_type and since filters
    Then it receives the matching events, paginated
```

> **AC-5 is deliberately unproven.** `EventLogStore.query()` supports this at
> store level; the HTTP route belongs in maistro-server / hive-conductor and is
> not wired. No test claims it, so the ladder reports it as `declared` and holds
> this spec's tier there — which is the accurate reading, not a gap in the
> measurement.

## Testing

- Unit: trigger pattern matching, delivery-identity/digest logic, claim/begin/settle fencing.
- Integration: emit event, inject death before dispatch, after begin before the send, during
  the call, after remote commit before SUCCESS persistence, and after SUCCESS persistence;
  restart and confirm one logical effect only for the enrolled idempotent recipient. An
  unproven recipient's uncertain send settles UNKNOWN and is never auto-replayed.
- Property: "every event in the log is delivered at least once; enrolled idempotent recipients
  apply one logical effect per persisted delivery key" (Hypothesis).
- Load: 1000 events/second, 10 triggers, verify no dropped events.

## References

- [ADR-086: Events, Triggers, Reactor](../adr/ADR-086-events-triggers-reactor.md)
- [SPEC-013: Reactor loop](SPEC-013-1khz-reactor.md)
