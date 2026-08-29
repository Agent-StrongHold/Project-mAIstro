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

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

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
    #: ``SerializeAsAny`` because the union member is bare ``BaseModel``, which
    #: declares no fields. Without it Pydantic serializes a typed output through
    #: that empty declared schema and the node's own fields are dropped -- so a
    #: persisted Attempt said the node produced nothing (#566). Duck-typed
    #: serialization writes the runtime model's real fields instead. Reading a
    #: record back gives the mapping, not the original class: the envelope never
    #: recorded which model it was, and inventing one here would be a guess.
    output: dict[str, Any] | SerializeAsAny[BaseModel] | None = None
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


#: Every ``paused_reason`` a node in this package passes to :func:`pause_until`,
#: mapped to who is owed the next action.
#:
#: A pause reason is a cross-module contract, not a node-local string: the node
#: writes it and two *other* modules read it back to decide whether a person or
#: the system is waited on. One table here, beside the function that carries
#: the reason, is what lets those readers agree by construction instead of by
#: both being edited on the same day.
#:
#: They previously held two hand-written allowlists which agreed on two reasons
#: and omitted the rest, so `human.review_and_edit` and `human.delegate_to_role`
#: parked as "the system will retry" on both paths: a prompt nobody can see,
#: indistinguishable from a provider being down. A second literal set is a
#: second thing to forget, and the reason it got forgotten is that nothing
#: failed when it was.
#:
#: A reason absent from this table is not a new feature but an unclassified
#: one -- the readers fall back to WAITING and nothing says whether that was
#: the intent. A structural test over the node package's calls is what turns
#: that silent default into a failing one.
PAUSE_AWAITING_HUMAN_ANSWER = "awaiting_human_answer"
PAUSE_AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
PAUSE_AWAITING_HUMAN_REVIEW = "awaiting_human_review"
PAUSE_AWAITING_ROLE_DELEGATE = "awaiting_role_delegate"
PAUSE_AWAITING_REMOTE_DELEGATION = "awaiting_remote_delegation"
PAUSE_AWAITING_HARNESS = "awaiting_harness"
PAUSE_WAITING_ON_JIRA_SUBTASKS = "waiting_on_jira_subtasks"

#: Who each pause waits on. "human" means a person owes the next action and the
#: NodeRun parks PAUSED; "system" means a retry decision is owed and it parks
#: WAITING. Every reason states its own answer, so adding a pausing node is a
#: question a reviewer sees rather than a default nobody chose.
PAUSE_REASON_OWNERS: dict[str, str] = {
    PAUSE_AWAITING_HUMAN_ANSWER: "human",
    PAUSE_AWAITING_HUMAN_APPROVAL: "human",
    PAUSE_AWAITING_HUMAN_REVIEW: "human",
    PAUSE_AWAITING_ROLE_DELEGATE: "human",
    PAUSE_AWAITING_REMOTE_DELEGATION: "system",
    PAUSE_AWAITING_HARNESS: "system",
    PAUSE_WAITING_ON_JIRA_SUBTASKS: "system",
}

#: The reasons a *person* is owed an action, derived from the table above so
#: the two can never disagree. Both readers -- the durable graph executor's
#: `_is_human_pause` and the schedule consumer's yield disposition -- import
#: this rather than spelling the set themselves.
HUMAN_PAUSE_REASONS = frozenset(
    reason for reason, owner in PAUSE_REASON_OWNERS.items() if owner == "human"
)

#: The two things that can make a pause resumable, named rather than inferred.
#:
#: ANSWER: the node dispatched something and is waiting to be told the outcome.
#: Re-entering it without that answer takes the *dispatch* branch again, so an
#: elapsed timer would repeat whatever the node already did -- for
#: `agent.delegate_remote`, a second delegation.
#:
#: ELAPSED: the node polls. Re-entering it re-reads the world, which is the
#: intended behaviour and is idempotent by construction.
RESUME_ON_ANSWER = "answer"
RESUME_ON_ELAPSED = "elapsed"

#: What each pause is waiting *for*, which is a different question from
#: `PAUSE_REASON_OWNERS`' "who owes the next action" and cannot be derived from
#: it: `awaiting_remote_delegation` is owed by the system and is still
#: answer-gated, because the system that owes it is another agent session.
#:
#: One table, beside the owners, for the same reason that one exists: a reader
#: that decides "may I run this node again?" from the reason string is making a
#: safety judgement, and a judgement spelled out per reason is one a reviewer
#: sees. A reason absent here is unclassified, not resumable -- the pause stays
#: parked and visible, which is the honest answer for a condition nobody stated.
PAUSE_RESUME_CONDITIONS: dict[str, str] = {
    PAUSE_AWAITING_HUMAN_ANSWER: RESUME_ON_ANSWER,
    PAUSE_AWAITING_HUMAN_APPROVAL: RESUME_ON_ANSWER,
    PAUSE_AWAITING_HUMAN_REVIEW: RESUME_ON_ANSWER,
    PAUSE_AWAITING_ROLE_DELEGATE: RESUME_ON_ANSWER,
    PAUSE_AWAITING_REMOTE_DELEGATION: RESUME_ON_ANSWER,
    PAUSE_AWAITING_HARNESS: RESUME_ON_ANSWER,
    PAUSE_WAITING_ON_JIRA_SUBTASKS: RESUME_ON_ELAPSED,
}

#: The reasons a timer alone may re-enter, derived so the two cannot disagree.
TIMER_RESUMABLE_PAUSE_REASONS = frozenset(
    reason
    for reason, condition in PAUSE_RESUME_CONDITIONS.items()
    if condition == RESUME_ON_ELAPSED
)

#: Where a resumed execution finds what its own previous pause recorded.
#:
#: A node that pauses to poll needs its first-reach timestamp back, or its
#: overall timeout can never expire and the poll runs forever -- which is the
#: unbounded loop a resume tick would otherwise create. Carrying the pause
#: metadata verbatim keeps the transport generic: the consumer copies a dict it
#: does not read, and each node reads the keys it wrote.
RESUMED_PAUSE_KEY = "resumed_pause"


def resumed_pause(ctx: NodeContext) -> dict[str, Any]:
    """What this node's previous pause recorded, or ``{}`` on a first reach.

    Read through here rather than off `ctx.metadata` directly so that a node
    asking "have I been here before?" and the consumer answering it name the
    same key -- the failure mode being a key written by one and read by
    neither, which is what `wait_first_seen:` was.
    """
    carried = (ctx.metadata or {}).get(RESUMED_PAUSE_KEY)
    return dict(carried) if isinstance(carried, dict) else {}


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
