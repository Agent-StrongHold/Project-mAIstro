"""Canonical events, legacy event bus, durable log, and trigger processing."""

from maistro.events.bus import (
    ActionHandler,
    Event,
    EventBus,
    EventCategory,
    Trigger,
    TriggerActionFailure,
    TriggerCondition,
    get_event_bus,
)
from maistro.events.durable_log import (
    EventLogStore,
    InMemoryEventLog,
    LoggedEvent,
    SqliteEventLog,
    append_from_bus_event,
)
from maistro.events.envelope import (
    MAX_EVENT_FIELD_BYTES,
    MAX_EVENT_FIELD_DEPTH,
    EventEnvelope,
    EventPayloadTooLarge,
    EventStore,
    InMemoryEventStore,
    SqliteEventStore,
    reconstruct_persisted_event,
)
from maistro.events.invocations import (
    MAX_ATTEMPTS,
    DeliveryAlreadyStarted,
    DeliveryAttemptLimitReached,
    DeliveryDisposition,
    DeliveryIdentity,
    DeliveryIdentityMismatch,
    HandlerCallOutcome,
    HandlerInvocation,
    InMemoryInvocationStore,
    InvocationStatus,
    InvocationStore,
    ReplaySafety,
    SqliteInvocationStore,
    request_digest_v1,
    validated_outcome,
)
from maistro.events.outbox import SqliteEventOutbox
from maistro.events.processing import (
    HANDLER_FAILED_EVENT,
    HandlerCaller,
    HTTPHandlerCaller,
    ProcessedBatch,
    process_events,
    process_events_batch,
)
from maistro.events.trigger_store import (
    InMemoryTriggerStore,
    SqliteTriggerStore,
    TriggerDefinition,
    TriggerStore,
    pattern_matches,
)

# Public protocol methods are consumed through injected store instances. Keep
# explicit references so static reachability analysis does not classify these
# intentionally dynamic interfaces as dead code.
_EVENT_STORE_STREAM_READS = (
    EventStore.list_stream,
    InMemoryEventStore.list_stream,
    SqliteEventStore.list_stream,
)
_OUTBOX_OPERATIONS = (
    SqliteEventOutbox.ensure_schema,
    SqliteEventOutbox.stage,
    SqliteEventOutbox.publish_pending,
    SqliteEventOutbox.pending_count,
)

__all__ = [
    "HANDLER_FAILED_EVENT",
    "MAX_ATTEMPTS",
    "MAX_EVENT_FIELD_BYTES",
    "MAX_EVENT_FIELD_DEPTH",
    "ActionHandler",
    "DeliveryAlreadyStarted",
    "DeliveryAttemptLimitReached",
    "DeliveryDisposition",
    "DeliveryIdentity",
    "DeliveryIdentityMismatch",
    "Event",
    "EventBus",
    "EventCategory",
    "EventEnvelope",
    "EventLogStore",
    "EventPayloadTooLarge",
    "EventStore",
    "HTTPHandlerCaller",
    "HandlerCallOutcome",
    "HandlerCaller",
    "HandlerInvocation",
    "InMemoryEventLog",
    "InMemoryEventStore",
    "InMemoryInvocationStore",
    "InMemoryTriggerStore",
    "InvocationStatus",
    "InvocationStore",
    "LoggedEvent",
    "ProcessedBatch",
    "ReplaySafety",
    "SqliteEventLog",
    "SqliteEventOutbox",
    "SqliteEventStore",
    "SqliteInvocationStore",
    "SqliteTriggerStore",
    "Trigger",
    "TriggerActionFailure",
    "TriggerCondition",
    "TriggerDefinition",
    "TriggerStore",
    "append_from_bus_event",
    "get_event_bus",
    "pattern_matches",
    "process_events",
    "process_events_batch",
    "reconstruct_persisted_event",
    "request_digest_v1",
    "validated_outcome",
]
