from enum import StrEnum


class NodePhase(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


TERMINAL_NODE_PHASES = frozenset(
    {
        NodePhase.SUCCEEDED,
        NodePhase.FAILED,
        NodePhase.SKIPPED,
        NodePhase.CANCELLED,
    }
)


class GraphPhase(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_GRAPH_PHASES = frozenset(
    {
        GraphPhase.COMPLETED,
        GraphPhase.FAILED,
    }
)
