"""Shared execution mechanics boundary."""

# The canonical extension contract (#950, ADR-104) is the runtime-facing SDK:
# hosts drive extension lifecycle from inside their Attempt execution, so the
# package that owns execution mechanics is the contract's static anchor. This
# import is deliberate wiring, not re-export: the extension SDK is imported as
# `maistro.extensions`, and the reachability ratchet must see it as wired from
# here until the M9 graph integration lands its direct consumer.
from maistro import extensions as extensions
from maistro.runtime.execution import (
    EventSink,
    ExecutionCallable,
    ExecutionPaused,
    ExecutionRuntime,
    PythonExecutionRuntime,
    RuntimeDeadlineExceeded,
    RuntimeEventEnvelope,
    RuntimeHealth,
    RuntimeMetrics,
)

__all__ = [
    "EventSink",
    "ExecutionCallable",
    "ExecutionPaused",
    "ExecutionRuntime",
    "PythonExecutionRuntime",
    "RuntimeDeadlineExceeded",
    "RuntimeEventEnvelope",
    "RuntimeHealth",
    "RuntimeMetrics",
    "extensions",
]
