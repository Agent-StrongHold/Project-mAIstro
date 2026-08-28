"""Node contract for the DAG-first self-improving fleet.

Every node in a user DAG implements this contract: typed input + output
Pydantic schemas plus an async `run()` method. Node *kinds* differ in their
execution semantics — sync LLM, sync tool, sync pure transform, wait (durable
async), hitl (paused on user input), composite (sub-DAG), negative_signal
(emits a cost into the blackboard).

This module defines the shape; concrete kinds (jira.poll, llm.summarize,
human.ask_question, ...) live in sibling modules and self-register via
``register_node`` from :mod:`maistro.graph.nodes`.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)

# Categorical taxonomy. The optimizer + UI reason about category, not just
# kind. e.g. "wait" + "hitl" categories trigger durable run-state checkpoints;
# "sync.*" categories never pause.
KindCategory = Literal[
    "sync.llm",
    "sync.tool",
    "sync.transform",
    "wait",
    "hitl",
    "composite",
    "negative_signal",
]


class NodeContext(BaseModel):
    """Per-execution context handed to every node's :meth:`Node.run`.

    Carries logical Run/Node identity plus the canonical NodeRun/Attempt IDs
    once physical execution begins, so nested capability Invocations can be
    correlated to the real execution spine. The GraphBlackboard lets the node
    read upstream signals and write annotations downstream nodes will see.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    dag_id: str
    node_id: str
    node_run_id: str = ""
    attempt_id: str = ""
    user_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    # blackboard kept as Any so we don't force a circular import on
    # maistro.graph.types; in practice this is GraphBlackboard.
    blackboard: Any = None
    # Caller-provided budget hint; nodes may decline to run if exceeded.
    deadline_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeResult(BaseModel):
    """Uniform result envelope from every node, regardless of kind.

    `output` is the node's typed output (matching the class's
    ``output_schema``); the surrounding fields are the telemetry the
    optimizer + observability layer rely on.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    output: dict[str, Any] | BaseModel | None = None
    latency_ms: int = 0
    error_code: str | None = None  # http status / exception class / "timeout"
    error_message: str | None = None
    tokens_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model_used: str | None = None
    cost_usd: float = 0.0
    # For wait/hitl: when the node has paused, set status = "paused" and
    # carry the resume metadata. Runtime checkpoints before persisting.
    status: Literal["completed", "paused", "failed"] = "completed"
    resume_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Node(Protocol):
    """Structural protocol every node kind implements.

    Subclasses are expected to be Pydantic-compatible (or at least set the
    ``ClassVar`` schemas as ``type[BaseModel]``). The runtime executor reads
    the class-level metadata to decide checkpoint behavior, palette display,
    and optimizer hints.
    """

    kind: ClassVar[str]
    kind_category: ClassVar[KindCategory]
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]
    cost_hint: ClassVar[float]  # 0.0 = free; 10.0 = very expensive
    idempotent: ClassVar[bool]
    external_io: ClassVar[bool]
    display_name: ClassVar[str]
    description: ClassVar[str]

    async def run(self, inputs: BaseModel, ctx: NodeContext) -> NodeResult: ...


class BaseNode(Generic[InputT, OutputT]):
    """Concrete base class for node kinds — handles the boilerplate of
    timing, schema enforcement, and result envelope construction so subclasses
    only define :meth:`_execute`.

    Generic over the input/output Pydantic models so subclasses can declare:

        class JiraPollNode(BaseNode[JiraPollIn, JiraPollOut]):
            ...
            async def _execute(self, inputs: JiraPollIn, ctx: NodeContext) -> JiraPollOut: ...

    Pyright + mypy then enforce the input/output shapes for the subclass
    without LSP variance errors (the override narrows correctly because the
    parameter is typed at the Generic parameter, not at `BaseModel`).
    """

    kind: ClassVar[str] = ""
    kind_category: ClassVar[KindCategory] = "sync.transform"
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]
    cost_hint: ClassVar[float] = 1.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""

    async def run(
        self, inputs: InputT | BaseModel | dict[str, Any], ctx: NodeContext
    ) -> NodeResult:
        # Validate inputs against the declared schema (defense in depth — the
        # caller should already have done this, but a misconfigured DAG could
        # skip it).
        if not isinstance(inputs, self.input_schema):
            validated: InputT = self.input_schema.model_validate(inputs)  # type: ignore[assignment]
        else:
            validated = inputs  # type: ignore[assignment]
        start = time.perf_counter()
        try:
            output = await self._execute(validated, ctx)
            latency_ms = int((time.perf_counter() - start) * 1000)
            return NodeResult(
                success=True,
                output=output,
                latency_ms=latency_ms,
                status="completed",
            )
        except _NodePaused as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return NodeResult(
                success=True,
                output=None,
                latency_ms=latency_ms,
                status="paused",
                resume_at=exc.resume_at,
                metadata={"paused_reason": exc.reason, **exc.metadata},
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return NodeResult(
                success=False,
                output=None,
                latency_ms=latency_ms,
                status="failed",
                error_code=type(exc).__name__,
                error_message=str(exc)[:512],
            )

    async def _execute(self, inputs: InputT, ctx: NodeContext) -> OutputT:
        """Subclasses implement this. Return the typed output (or raise)."""
        raise NotImplementedError(f"{type(self).__name__}._execute not implemented")


class _NodePaused(Exception):
    """Internal signal a wait/HITL node raises to surface a durable pause.

    Use :func:`pause_until` from the node ``_execute`` body rather than
    raising this directly.
    """

    def __init__(
        self,
        reason: str,
        *,
        resume_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.reason = reason
        self.resume_at = resume_at
        self.metadata = metadata or {}
        super().__init__(reason)


def pause_until(
    reason: str,
    *,
    resume_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Signal that the current node should pause and the run should checkpoint.

    Wait/HITL node `_execute` bodies call this to suspend execution. The
    runtime catches the signal, persists the run state, and resumes later
    (when the polled condition becomes true or the user supplies input).
    """
    raise _NodePaused(reason, resume_at=resume_at, metadata=metadata)


def now_utc() -> datetime:
    """Single source of truth for "now" so tests can monkeypatch."""
    return datetime.now(UTC)
