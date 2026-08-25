---
id: SPEC-070226-b234
title: "Events, triggers, and the reactor: durable event log with idempotent replay"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-07-02
substrate:
  - maistro-engine#ADR-086
  - maistro-engine#ADR-037
  - maistro-engine#SPEC-013
implements:
  - maistro-engine#ADR-086
related:
  - maistro-engine#ADR-082
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
---

# SPEC-070226-b234: Events, triggers, and the reactor — durable event log with idempotent replay

## Context

ADR-086 specifies a durable event log (PostgreSQL table of immutable events) and trigger+handler
model: operators define triggers ("on agent.delegated, run X"), the reactor processes events,
and handlers are replayed durably (idempotent, no lost events on crash).

The 1kHz reactor loop (SPEC-013) currently emits events in-memory; this SPEC persists them.

## Goals

- Durable event log (all events persisted to PostgreSQL).
- Trigger definitions (declarative; stored in config or registry).
- Event processing and handler invocation (async queue, batched).
- Idempotent replay (if reactor crashes mid-handler, resume without duplication).
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
> - `maistro/events/trigger_store.py` — `TriggerDefinition`, `pattern_matches()` (dot-segmented
>   glob: `agent.*` matches `agent.created`, not `task.created` and not `agent.task.created`),
>   `TriggerStore` protocol, `InMemoryTriggerStore`, `SqliteTriggerStore`.
> - `maistro/events/invocations.py` — `HandlerInvocation` with `(trigger_id, event_id)`
>   idempotency key, `InvocationStatus` (pending/success/failed/retrying), `MAX_ATTEMPTS = 3`,
>   `InvocationStore` protocol, `InMemoryInvocationStore`, `SqliteInvocationStore`
>   (composite PK + `INSERT OR IGNORE` enforce the key at the storage layer).
> - `maistro/events/processing.py` — `HandlerCaller` protocol (injected async callable),
>   `HTTPHandlerCaller` (httpx POST of `event.to_dict()` to `trigger.handler_url`, raises
>   `HandlerCallError` on >=400 or transport error), and the pure async `process_events()`
>   loop function ticked by the reactor with injected stores.
>
> Deviations from the original text: `process_events()` is cursor-based (`after_id` in,
> new cursor out) — the cursor only advances past an event once all matching triggers are
> terminal, so retries happen on subsequent ticks and a crash (lost cursor) safely replays
> from an older position. Retry backoff is not `sleep`-based inside the loop; it falls out
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

### Reactor event processing

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
    
  - name: "notify-on-task-failure"
    event_pattern: "task.failed"
    handler_url: "http://localhost:8000/handlers/notify"

  - name: "update-cache-on-memory-write"
    event_pattern: "memory.written"
    handler_url: "http://localhost:8000/handlers/cache-update"
```

### Idempotency guarantee

The `(trigger_id, event_id)` unique key ensures a handler is invoked at most once per event:
- If a handler crashes mid-execution, the invocation status is "retrying".
- On reactor restart, the handler is retried (same invocation row).
- If the handler succeeds (status="success"), it's skipped on any future replay.

## Acceptance criteria

```gherkin
Feature: Durable event log with idempotent replay

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
  Scenario: A handler is invoked exactly once per event across a crash
    Given a trigger whose handler has claimed an invocation for an event
    When the process dies mid-handler and the processor runs again
    Then the handler is not invoked a second time for that event
    And the invocation record still names its terminal status

  @AC-4
  Scenario: A failing handler is retried three times and then given up on
    Given a handler that raises on every call
    When the processor runs until the invocation settles
    Then the handler is called no more than 4 times in total
    And the invocation ends in a terminal failed status
    And the backoff is paced by reactor ticks rather than an in-loop sleep

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

- Unit: trigger pattern matching, idempotency key logic.
- Integration: emit event, handler invoked; crash reactor mid-handler, restart, confirm handler
  completed without duplication.
- Property: "every event in log is processed by all matching triggers exactly once" (Hypothesis).
- Load: 1000 events/second, 10 triggers, verify no dropped events.

## References

- [ADR-086: Events, Triggers, Reactor](../adr/ADR-086-events-triggers-reactor.md)
- [SPEC-013: Reactor loop](SPEC-013-1khz-reactor.md)
