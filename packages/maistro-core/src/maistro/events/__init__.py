"""Canonical events, legacy event bus, durable log, and trigger processing."""

from maistro.events.bus import (
    ActionHandler,
    Event,
    EventBus,
    EventCategory,
    Trigger,
    TriggerCondition,
    get_event_bus,
)
from maistro.events.checkpoints import (
    CHECKPOINT_SCHEMA_VERSION,
    SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS,
    Checkpoint,
    CheckpointError,
    CheckpointNotFoundError,
    CheckpointRef,
    CheckpointStore,
    CheckpointVersionError,
    InMemoryCheckpointStore,
    SqliteCheckpointStore,
    checkpoint_created_event,
    resolve_checkpoint,
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
_CHECKPOINT_STORE_OPERATIONS = (
    CheckpointStore.append,
    CheckpointStore.get,
    CheckpointStore.latest,
    CheckpointStore.list_run,
    InMemoryCheckpointStore.append,
    InMemoryCheckpointStore.get,
    InMemoryCheckpointStore.latest,
    InMemoryCheckpointStore.list_run,
    SqliteCheckpointStore.append,
    SqliteCheckpointStore.get,
    SqliteCheckpointStore.latest,
    SqliteCheckpointStore.list_run,
)
_OUTBOX_OPERATIONS = (
    SqliteEventOutbox.ensure_schema,
    SqliteEventOutbox.stage,
    SqliteEventOutbox.publish_pending,
    SqliteEventOutbox.pending_count,
)

__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "HANDLER_FAILED_EVENT",
    "MAX_ATTEMPTS",
    "SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS",
    "ActionHandler",
    "Checkpoint",
    "CheckpointError",
    "CheckpointNotFoundError",
    "CheckpointRef",
    "CheckpointStore",
    "CheckpointVersionError",
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
    "InMemoryCheckpointStore",
    "InMemoryEventLog",
    "InMemoryEventStore",
    "InMemoryInvocationStore",
    "InMemoryTriggerStore",
    "InvocationStatus",
    "InvocationStore",
    "LoggedEvent",
    "SqliteCheckpointStore",
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
    "checkpoint_created_event",
    "get_event_bus",
    "pattern_matches",
    "process_events",
    "resolve_checkpoint",
]
