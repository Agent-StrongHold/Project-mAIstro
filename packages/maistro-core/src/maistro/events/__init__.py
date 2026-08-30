"""Canonical events, legacy event bus, durable log, and trigger processing.

`maistro.events.checkpoints` is deliberately not re-exported here. Nothing
imported those names from this package -- the module's only direct importer is
its own test -- so the re-export published a public surface for a contract with
no consumer, and it was what made the reachability walker count that module as
reached (`_imports` treats an `ImportFrom` in a package `__init__` as an edge
like any other). Dropping it lets the module be classified in the ledger with
every other unwired module, and retires the tuple of method references that used
to sit here keeping its store's methods looking used (ADR-083026-ebcb, #729).
"""

from maistro.events.bus import (
    ActionHandler,
    Event,
    EventBus,
    EventCategory,
    Trigger,
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
    EventEnvelope,
    EventStore,
    InMemoryEventStore,
    SqliteEventStore,
)
from maistro.events.invocations import (
    MAX_ATTEMPTS,
    HandlerInvocation,
    InMemoryInvocationStore,
    InvocationStatus,
    InvocationStore,
    SqliteInvocationStore,
)
from maistro.events.outbox import SqliteEventOutbox
from maistro.events.processing import (
    HANDLER_FAILED_EVENT,
    HandlerCaller,
    HandlerCallError,
    HTTPHandlerCaller,
    process_events,
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
    "ActionHandler",
    "Event",
    "EventBus",
    "EventCategory",
    "EventEnvelope",
    "EventLogStore",
    "EventStore",
    "HTTPHandlerCaller",
    "HandlerCallError",
    "HandlerCaller",
    "HandlerInvocation",
    "InMemoryEventLog",
    "InMemoryEventStore",
    "InMemoryInvocationStore",
    "InMemoryTriggerStore",
    "InvocationStatus",
    "InvocationStore",
    "LoggedEvent",
    "SqliteEventLog",
    "SqliteEventOutbox",
    "SqliteEventStore",
    "SqliteInvocationStore",
    "SqliteTriggerStore",
    "Trigger",
    "TriggerCondition",
    "TriggerDefinition",
    "TriggerStore",
    "append_from_bus_event",
    "get_event_bus",
    "pattern_matches",
    "process_events",
]
