---
id: ADR-086
title: "Events, Triggers, and the Reactor"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-037
implements: []
related:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-046
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# ADR-086: Events, Triggers, and the Reactor

**Date:** 2026-05-30
**Specifies the delivery semantics** of the ADR-037 event bus and the trigger/reactor layer that
turns events into action — the substrate every proactive behavior in the engine stands on.

---

## Context

ADR-037 names the event bus and the `policy.decision` / `security.violation` events, but does not say
how events are delivered, what happens on a crash mid-handling, or how an event causes work to run.
Proactive automation — scheduled tasks (ADR-046), proactive producers — needs a dependable
answer: events must not be silently lost, and a process restart must not strand in-flight work. A
local dispatch record cannot make an arbitrary remote commit exactly-once, so this ADR also states
where idempotency must be proven.

## Decision

**Delivery is AT-LEAST-ONCE.** The event bus guarantees an event reaches its handlers at least once;
it may deliver more than once (retry, redelivery after crash). The `(trigger_id, event_id)`
Invocation row deduplicates MAIstro dispatch only; it does not deduplicate a remote commit.
Replay-truthful delivery is therefore a receipt protocol (#1060): each receipt freezes a
`DeliveryIdentity` (handler URL, request digest, replay safety, contract ref) and allocates one
random delivery key — the `Idempotency-Key` of every send. Automatic redelivery after an
uncertain send is admitted only for a recipient enrolled `idempotent` or `read_only` (with an
operator-approved contract ref) through the authorized trigger store; an unproven recipient gets
a one-shot attempt and never auto-retry after an ambiguous outcome, which settles `UNKNOWN` —
visible, cursor-settled, unresolved until reconciled by its owner (or by the governed
Capability/Provider/Binding/Invocation seam, #55). Effectful work that needs stronger semantics
belongs on that seam.

**Triggers are declarative rules** of the form `(event-pattern -> recipe)`. The reactor evaluates
incoming events against the registered trigger patterns and, on a match, fires the bound recipe.
Triggers are data (a pattern and a recipe reference), not code — the reactor is the fixed engine that
evaluates them.

**Events and their processing are durable and replayable** via an **event log**. Events are appended
to the log before handling; a crash mid-handling **replays** from the log on restart rather than
dropping the event. For an enrolled idempotent recipient, HTTP redelivery repeats the same
persisted key, so a partially-applied handler can re-run without double-applying its committed
effect. A response loss or timeout remains an ambiguous remote outcome; HTTP 2xx and the local
SUCCESS write are not one transaction, and a local lease, status code or header never proves a
remote effect did not occur.

This event log + trigger + reactor stack is the **substrate for proactive automation**: scheduled
tasks (ADR-046) and proactive producers are expressed as triggers firing recipes, so they inherit
at-least-once delivery and crash-replay. Effect safety still depends on each trigger's declared
handler-owned idempotency contract.

> **Amended 2026-09-15 (#1163): a durable consumer's resume position is owned by a leased,
> fenced cursor and never persisted past an id the log has not committed.** The replay cursor
> the reactor's legacy-event bridge (`Container.process_durable_events`) resumes from used to be
> a process-local integer, so every restart replayed the whole retained log. It is now a row in
> a `ConsumerCursorStore` (`maistro.events.consumer_cursor`; in-memory, SQLite and PostgreSQL
> twins, table `consumer_cursors`, Alembic revision `036_consumer_cursors`), keyed by a fixed
> consumer id, with these semantics:
>
> - **Ownership.** One consumer id owns one position. The bridge is the single consumer today
>   (`legacy-event-bridge`); a second consumer of the same log takes its own id and cursor.
> - **Lease.** Before ticking, a replica `claim`s the cursor with a holder id; the claim returns
>   the position to resume from or `None` while another holder's lease is live, in which case the
>   replica skips the tick rather than repeating work the holder already covers. The same holder
>   renews by claiming again; a lapsed lease can be taken over.
> - **Fencing.** Every `advance` carries the fencing token its claim returned. A token the store
>   no longer recognises — the lease was taken over — is refused, and the write is additionally
>   monotonic (`GREATEST`/`MAX`), so a stale or reordered write cannot move the position back.
> - **Fenced acknowledgement.** Amended 2026-11 (#2511): the log's own replay acknowledgement
>   (`EventLogStore.acknowledge_replay`, #836) has no fencing token of its own, so the bridge
>   fences it through the primary cursor instead of trusting the tick's own view. An `advance`
>   the store refuses — the lease was taken over mid-tick — acknowledges nothing on the log and
>   reports the authoritative cursor position (re-read from the store), never the rejected one;
>   an accepted advance acknowledges the position re-read from the authoritative cursor, so a
>   takeover between the primary write and the acknowledgement can only publish a position the
>   primary already accepted. The acknowledgement stays monotonic, so a crash between the two
>   writes leaves it lagging the cursor — conservative, never contradictory — until the next
>   settled tick carries it forward. `ConsumerCursorStore.current_position` is the read-only
>   projection the rejected holder reports from; it adds no second authority.
> - **Settled before persisted.** The position is written only after every event up to it has a
>   terminal invocation on every matching trigger; a crash between processing and the write costs
>   a replay of already-idempotent work and never skips an event still in flight.
> - **Gap policy.** PostgreSQL hands out `event_log.id` before the appending transaction
>   commits, so a lower id can be invisible while a higher one is readable. The bridge processes
>   what it can see but persists its position only up to the first skipped id it has not proven
>   terminally absent — the log reports and proves **every** skipped id of a run individually
>   (`EventLogStore.prove_holes_absent`, #2509), because proof that one id's append rolled back
>   says nothing about a neighbouring id that may still commit. "Terminally absent" is durable
>   database evidence — never elapsed time — that the allocating transaction ended
>   without committing and that no future transaction can make the id visible. On PostgreSQL the
>   evidence is `pg_locks`: a transaction that has called `nextval` holds a granted lock on the
>   sequence until it commits or aborts, so when no such lock exists and a fresh read still cannot
>   see the id, the append rolled back and a sequence never hands the id out again. A time-based
>   grace used to move the position past an unresolved hole after 60 s; that was removed — a
>   transaction can stay open past any timeout and commit afterwards, and the position moving past
>   it then loses the event from every later read. Handler work is never delayed by a hole; only
>   the persisted resume point is.
>
> None of this changes the correctness contract above: the cursor is a resume *optimisation*,
> and `InvocationStore`'s `(trigger_id, event_id)` claim remains what makes redelivery safe
> (ADR-082426-82c7, "the occurrence is the claim, not the cursor").

> **Amended 2026-11-28 (#2506): the durable log's canonical-Envelope ingress is a replayable,
> idempotent projection; the legacy bus is never the only durable trigger ingress.** The
> persist-first publisher projected an inserted canonical Event onto the in-memory bus, whose
> authoritative `before_handlers` bridge appended it into this log — at-most-once. A bridge
> append that failed after the canonical append committed therefore left a persisted Event
> permanently outside the only log the trigger cursor scans: the retry emission returned
> `inserted=False` and suppressed the bus forever. The ingress is now repairable from canonical
> authority, with no second event identity and no second processing lifecycle:
>
> - **One row per canonical Event, atomically.** `event_log` carries a nullable
>   `source_event_id` under a unique index; the bridge keys every canonical projection with it,
>   and an append naming a known source id returns the existing row. Two ingress paths — the
>   bridge and the replay projector — are two writers of one durable fact, never two occurrences.
> - **Registered streams.** The publisher registers each event's stream with the projection
>   store *before* the canonical append, positioned at the stream's canonical high-water mark, so
>   a failure or crash after the commit always leaves the Event scan-reachable, and retained
>   pre-projection history is never re-projected.
> - **The replay tick.** `Container.process_durable_events` first replays the projection: per
>   registered stream, under a leased and fenced claim, every canonical Event above the cursor is
>   confirmed in the log through the idempotent append; the cursor advances only past confirmed
>   sequences; a failing append gets bounded attempts with backoff and a visible terminal
>   dead-letter disposition that releases its stream. Healing is reachable only through this
>   ordinary production tick. Canonical stream sequences are contiguous by construction, so an
>   aborted envelope append cannot leave a hole the projection cursor could skip — the gap
>   policy above remains what guards the *trigger* cursor against `event_log`'s own `BIGSERIAL`
>   holes.

## Acceptance criteria

- [ ] The event bus delivers each event to its handlers at least once; redelivery is possible and
      expected.
- [ ] Enrolled recipients consume and durably deduplicate the persisted delivery key at their
      own effect commit boundary; unproven recipients receive one-shot delivery only and are never
      automatically replayed after an uncertain send (property test: deliver twice under the same
      key, observe one effect for the enrolled recipient).
- [ ] A trigger is a declarative `(event-pattern -> recipe)` rule; the reactor fires the bound recipe
      on a pattern match.
- [ ] Events are appended to a durable event log before handling; a crash mid-handling replays from
      the log on restart rather than dropping the event.
- [ ] Scheduled tasks (ADR-046) and proactive producers are expressed as triggers and inherit
      at-least-once delivery; effect idempotency/replay safety is conditional on the recipient's
      enrolled contract.

## Consequences

- ADR-037 gains explicit delivery semantics; "the bus delivers events" now has a contract.
- The at-least-once + persisted delivery key + enrolled idempotency + truthful UNKNOWN
  combination makes proactive automation honest across post-effect crashes: redelivery under a
  recipient-owned key is safe for enrolled recipients, and everything unresolved stays visibly
  UNKNOWN instead of being retried on an assumption. The local Invocation row alone makes no such
  claim.
- Triggers being data (not code) means new proactive behavior is authored as rules, not deployed as
  handler code — the reactor stays fixed.

## Out of scope

- The on-disk format and retention policy of the event log.
- The pattern language for triggers (a follow-up SPEC).
- Exactly-once / transactional delivery — explicitly not provided; recipient-enrolled idempotency
  is the supported contract, and the local Invocation row is not an external-effect authority.
