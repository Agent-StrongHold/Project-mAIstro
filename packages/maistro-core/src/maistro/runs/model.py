from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.graph.definitions import Graph


def _id() -> str:
    return uuid.uuid4().hex


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_finished_at(
    *,
    terminal: bool,
    finished_at: datetime | None,
    subject: str,
) -> None:
    if terminal and finished_at is None:
        raise ValueError(f"terminal {subject} requires finished_at")
    if not terminal and finished_at is not None:
        raise ValueError(f"non-terminal {subject} cannot have finished_at")


class _FrozenDict(dict[Any, Any]):
    """Dict-shaped immutable-by-value evidence that remains JSON serializable."""

    @staticmethod
    def _deny(*_args: object, **_kwargs: object) -> None:
        raise TypeError("AttemptResult evidence is immutable")

    __setitem__ = _deny
    __delitem__ = _deny
    clear = _deny
    pop = _deny
    setdefault = _deny
    update = _deny

    def popitem(self) -> tuple[Any, Any]:
        raise TypeError("AttemptResult evidence is immutable")

    def __deepcopy__(self, _memo: dict[int, object]) -> _FrozenDict:
        return self


class _FrozenList(list[Any]):
    """List-shaped immutable-by-value evidence that preserves list equality/JSON shape."""

    @staticmethod
    def _deny(*_args: object, **_kwargs: object) -> None:
        raise TypeError("AttemptResult evidence is immutable")

    __setitem__ = _deny
    __delitem__ = _deny
    append = _deny
    clear = _deny
    extend = _deny
    insert = _deny
    pop = _deny
    remove = _deny
    reverse = _deny
    sort = _deny

    def __iadd__(self, _values: Iterable[Any]) -> Self:  # type: ignore[misc]
        """Reject list's mutating += contract for immutable evidence."""
        raise TypeError("AttemptResult evidence is immutable")

    def __imul__(self, _value: int) -> Self:  # type: ignore[misc,override]
        """Reject list's mutating *= contract for immutable evidence."""
        raise TypeError("AttemptResult evidence is immutable")

    def __deepcopy__(self, _memo: dict[int, object]) -> _FrozenList:
        return self


def _freeze_evidence_value(value: Any) -> Any:
    """Detach and recursively freeze common mutable result containers."""
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze_evidence_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze_evidence_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_evidence_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_evidence_value(item) for item in value)
    if isinstance(value, BaseModel):
        return value.model_copy(deep=True)
    try:
        return deepcopy(value)
    except Exception:
        return value


def evidence_values_equal(left: Any, right: Any) -> bool:
    """Compare persisted projections, including non-reflexive numeric values such as NaN."""
    if left is right:
        return True
    if (
        isinstance(left, float)
        and isinstance(right, float)
        and math.isnan(left)
        and math.isnan(right)
    ):
        return True
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            evidence_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            evidence_values_equal(l_item, r_item)
            for l_item, r_item in zip(left, right, strict=True)
        )
    try:
        return bool(left == right)
    except Exception:
        return False


class RunStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class AttemptStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    YIELDED = "yielded"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }
)
TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
        AttemptStatus.TIMED_OUT,
        AttemptStatus.YIELDED,
    }
)
ACCEPTED_NODE_OUTCOME_STATUSES = frozenset(
    {
        RunStatus.WAITING,
        RunStatus.PAUSED,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
    }
)


class GraphSnapshot(BaseModel):
    """Immutable-by-value Graph definition captured when a Run is created."""

    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_inf_nan="constants")

    graph_id: str
    workspace_id: str
    project_id: str
    content_hash: str
    definition_json: str

    @classmethod
    def from_graph(cls, graph: Graph) -> GraphSnapshot:
        return cls(
            graph_id=graph.graph_id,
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            content_hash=graph.content_hash,
            definition_json=graph.model_dump_json(),
        )

    def materialize(self) -> Graph:
        # Imported here, not at module scope: `maistro.graph`'s package __init__
        # imports `maistro.graph.traversal_commit`, which imports this module.
        # Binding Graph at import time made `import maistro.runs` fail outright
        # whenever `maistro.graph` had not already been imported — the canonical
        # execution spine was unimportable from its own front door. Graph is only
        # ever needed inside a method body, so the edge does not need to exist.
        from maistro.graph.definitions import Graph

        return Graph.model_validate_json(self.definition_json)

    @model_validator(mode="after")
    def _validate_snapshot(self) -> GraphSnapshot:
        graph = self.materialize()
        if graph.graph_id != self.graph_id:
            raise ValueError("graph snapshot graph_id does not match definition")
        if graph.workspace_id != self.workspace_id:
            raise ValueError("graph snapshot workspace_id does not match definition")
        if graph.project_id != self.project_id:
            raise ValueError("graph snapshot project_id does not match definition")
        if graph.content_hash != self.content_hash:
            raise ValueError("graph snapshot content_hash does not match definition")
        return self


class Run(BaseModel):
    """One logical execution of a stable Graph snapshot in one Project scope."""

    model_config = ConfigDict(extra="forbid", ser_json_inf_nan="constants")

    run_id: str = Field(default_factory=_id)
    workspace_id: str
    project_id: str
    graph: GraphSnapshot
    status: RunStatus = RunStatus.CREATED
    parent_run_id: str | None = None
    parent_node_run_id: str | None = None
    persona_id: str | None = None
    actor_principal_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    #: When this Run may be purged, or None to retain it indefinitely
    #: (ADR-082326-c126). A floor, not a ceiling: a Run past its deadline that
    #: is still running is never purged, because deleting the execution
    #: identity of live work is worse than the storage it reclaims. None is the
    #: default so that task Runs, graph Runs and every Run recorded before this
    #: field existed keep exactly the retention they already had.
    retention_expires_at: datetime | None = None
    result: Any | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _validate_run(self) -> Run:
        _require_non_empty(self.workspace_id, "workspace_id")
        _require_non_empty(self.project_id, "project_id")
        self._validate_scope_identity()
        if self.parent_run_id == self.run_id:
            raise ValueError("Run cannot be its own parent")
        _validate_finished_at(
            terminal=self.status in TERMINAL_RUN_STATUSES,
            finished_at=self.finished_at,
            subject="Run",
        )
        return self

    def _validate_scope_identity(self) -> None:
        if self.graph.workspace_id != self.workspace_id:
            raise ValueError("Run and Graph snapshot must belong to the same Workspace")
        if self.graph.project_id != self.project_id:
            raise ValueError("Run and Graph snapshot must belong to the same Project")


class ExecutionLease(BaseModel):
    """Durable authority token for one physical Attempt execution epoch."""

    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_inf_nan="constants")

    node_run_id: str
    attempt_id: str
    lease_epoch: int = Field(ge=1)
    holder: str
    fencing_token: str = Field(default_factory=_id)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_lease(self) -> ExecutionLease:
        _require_non_empty(self.node_run_id, "node_run_id")
        _require_non_empty(self.attempt_id, "attempt_id")
        _require_non_empty(self.holder, "holder")
        _require_non_empty(self.fencing_token, "fencing_token")
        if self.expires_at is not None and self.expires_at <= self.issued_at:
            raise ValueError("ExecutionLease.expires_at must be later than issued_at")
        return self


class AttemptResult(BaseModel):
    """Immutable evidence produced by one terminal physical Attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_inf_nan="constants")

    attempt_id: str
    node_run_id: str
    ordinal: int = Field(ge=1)
    status: AttemptStatus
    result: Any | None = None
    error: str | None = None
    finished_at: datetime

    @model_validator(mode="after")
    def _validate_attempt_result(self) -> AttemptResult:
        _require_non_empty(self.attempt_id, "attempt_id")
        _require_non_empty(self.node_run_id, "node_run_id")
        if self.status not in TERMINAL_ATTEMPT_STATUSES:
            raise ValueError("AttemptResult requires a terminal physical Attempt status")
        frozen = _freeze_evidence_value(self.result)
        if frozen is not self.result:
            object.__setattr__(self, "result", frozen)
        return self

    @classmethod
    def from_attempt(cls, attempt: Attempt) -> AttemptResult:
        if attempt.status not in TERMINAL_ATTEMPT_STATUSES or attempt.finished_at is None:
            raise ValueError("AttemptResult can only be created from a terminal Attempt")
        return cls(
            attempt_id=attempt.attempt_id,
            node_run_id=attempt.node_run_id,
            ordinal=attempt.ordinal,
            status=attempt.status,
            result=attempt.result,
            error=attempt.error,
            finished_at=attempt.finished_at,
        )


class AcceptedNodeOutcome(BaseModel):
    """Authoritative logical projection of one physically completed AttemptResult."""

    model_config = ConfigDict(extra="forbid", frozen=True, ser_json_inf_nan="constants")

    node_run_id: str
    attempt_result: AttemptResult
    logical_status: RunStatus = RunStatus.COMPLETED
    result: Any | None = None
    error: str | None = None
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def _default_legacy_projection(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        projected = dict(value)
        physical = projected.get("attempt_result")
        if "result" not in projected:
            if isinstance(physical, AttemptResult):
                projected["result"] = physical.result
            elif isinstance(physical, dict):
                projected["result"] = physical.get("result")
        if "error" not in projected:
            if isinstance(physical, AttemptResult):
                projected["error"] = physical.error
            elif isinstance(physical, dict):
                projected["error"] = physical.get("error")
        return projected

    @model_validator(mode="after")
    def _validate_accepted_outcome(self) -> AcceptedNodeOutcome:
        _require_non_empty(self.node_run_id, "node_run_id")
        if self.attempt_result.node_run_id != self.node_run_id:
            raise ValueError("accepted AttemptResult must belong to the NodeRun")
        if self.attempt_result.status is not AttemptStatus.COMPLETED:
            raise ValueError("only a physically completed AttemptResult can be accepted")
        if self.logical_status not in ACCEPTED_NODE_OUTCOME_STATUSES:
            raise ValueError("accepted Node outcome has an unsupported logical disposition")
        return self


class NodeRun(BaseModel):
    """One logical execution of one Node within a Run."""

    model_config = ConfigDict(extra="forbid", ser_json_inf_nan="constants")

    node_run_id: str = Field(default_factory=_id)
    run_id: str
    node_id: str
    ordinal: int = Field(ge=1)
    status: RunStatus = RunStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    accepted_outcome: AcceptedNodeOutcome | None = None
    result: Any | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _validate_node_run(self) -> NodeRun:
        _require_non_empty(self.run_id, "run_id")
        _require_non_empty(self.node_id, "node_id")
        if self.accepted_outcome is not None:
            if self.accepted_outcome.node_run_id != self.node_run_id:
                raise ValueError("accepted outcome must belong to this NodeRun")
            if self.status is not self.accepted_outcome.logical_status:
                raise ValueError("NodeRun status must match its accepted logical outcome")
            if not evidence_values_equal(self.result, self.accepted_outcome.result):
                raise ValueError("NodeRun.result must project the accepted logical result")
            if self.error != self.accepted_outcome.error:
                raise ValueError("NodeRun.error must project the accepted logical error")
        _validate_finished_at(
            terminal=self.status in TERMINAL_RUN_STATUSES,
            finished_at=self.finished_at,
            subject="NodeRun",
        )
        return self


class Attempt(BaseModel):
    """One physical try under a NodeRun."""

    model_config = ConfigDict(extra="forbid", ser_json_inf_nan="constants")

    attempt_id: str = Field(default_factory=_id)
    node_run_id: str
    ordinal: int = Field(ge=1)
    status: AttemptStatus = AttemptStatus.CREATED
    runtime_id: str = "python"
    executor_id: str = ""
    execution_lease: ExecutionLease | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    deadline_at: datetime | None = None
    resume_checkpoint_id: str | None = None
    result: Any | None = None
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_attempt(self) -> Attempt:
        _require_non_empty(self.node_run_id, "node_run_id")
        if self.execution_lease is not None:
            if self.execution_lease.attempt_id != self.attempt_id:
                raise ValueError("ExecutionLease.attempt_id must match Attempt.attempt_id")
            if self.execution_lease.node_run_id != self.node_run_id:
                raise ValueError("ExecutionLease.node_run_id must match Attempt.node_run_id")
        _validate_finished_at(
            terminal=self.status in TERMINAL_ATTEMPT_STATUSES,
            finished_at=self.finished_at,
            subject="Attempt",
        )
        return self


__all__ = [
    "ACCEPTED_NODE_OUTCOME_STATUSES",
    "TERMINAL_ATTEMPT_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "AcceptedNodeOutcome",
    "Attempt",
    "AttemptResult",
    "AttemptStatus",
    "ExecutionLease",
    "GraphSnapshot",
    "NodeRun",
    "Run",
    "RunStatus",
    "evidence_values_equal",
]
