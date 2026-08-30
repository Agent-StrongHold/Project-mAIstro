"""SuperPlanner waves as a Repertoire ensemble (SPEC-070226-b624 / ADR-071).

A *wave* is a parallel branch of execution: one or more agents attempting the
same task with an isolated context (no shared mutable state between waves).
All waves run concurrently (``asyncio.gather`` with ``return_exceptions``);
a per-wave timeout marks only that wave failed while the others continue.
After the waves finish, a :class:`ResultComparator` picks the single best
result and the rest are discarded (the Repertoire pattern, ADR-070).

Checkpoints are written before and after wave execution using the ADR-056
checkpoint type (:class:`maistro.tasks.checkpoint.TaskCheckpoint`); on crash
recovery a ``waves_complete`` checkpoint short-circuits re-running the waves.

The existing :class:`maistro.orchestrator.planner.SuperPlanner` is *extended*
(``execute_ensemble()`` / ``recover_ensemble()``) rather than forked.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from maistro.agents.circuit_breaker import CircuitBreaker
from maistro.graph.types import (
    AgentRole,
    CodeOutput,
    GraphBlackboard,
    GraphTask,
    PlanOutput,
    ReviewOutput,
)
from maistro.tasks.checkpoint import CheckpointKind, TaskCheckpoint
from maistro.tasks.recovery import CrashLoopPolicy, version_compatible
from maistro.tasks.replay import ResumeState, replay

# Event names (ADR-037 dotted format).
EVENT_WAVES_PLANNED = "waves.planned"
EVENT_WAVE_STARTED = "wave.started"
EVENT_WAVE_COMPLETED = "wave.completed"
EVENT_WAVE_FAILED = "wave.failed"
EVENT_WAVES_COMPARED = "waves.compared"
# Recovery says what it decided, on the same stream (ADR-037, #462's shape).
EVENT_RECOVERY_RESUMED = "recovery.resumed"
EVENT_RECOVERY_REFUSED = "recovery.refused"
EVENT_RECOVERY_QUARANTINED = "recovery.quarantined"

# Checkpoint ``payload["state"]`` markers (SPEC-070226-b624).
STATE_WAVES_PLANNED = "waves_planned"
STATE_WAVES_COMPLETE = "waves_complete"

EmitFn = Callable[..., None]


def _noop_emit(event: str, **fields: Any) -> None:
    return None


def _resume_fields(state: ResumeState) -> dict[str, Any]:
    """What the fold reconstructed, as event fields.

    Counts rather than the ids themselves: the event is a statement about the
    run, and a tool-call id is only meaningful to the subsystem that wrote it.
    """
    return {
        "open_tool_calls": len(state.open_tool_calls),
        "pending_approval_gates": len(state.pending_approval_gates),
        "cumulative_spend": state.cumulative_spend,
        "waves_recorded": len(state.wave_status),
    }


class WaveEnsembleError(Exception):
    """Raised when every wave in an ensemble failed (no result to compare)."""


class WaveRecoveryQuarantined(Exception):
    """Raised when a task has been recovered too many times without completing.

    A distinct exception rather than a `None` return: "there is nothing to
    recover" and "this task must stop being recovered" call for opposite
    actions, and a caller that cannot tell them apart would answer a crash loop
    by starting the work again (#624).
    """


@dataclass
class WaveTask:
    """The task a wave ensemble attempts."""

    id: str
    description: str
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Wave:
    """A parallel branch with one or more sub-agents.

    ``context`` is *isolated*: expanders deep-copy the task context per wave
    so no mutable state is shared between waves.
    """

    id: str
    agent_ids: list[str]
    context: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30_000
    priority: int = 0


@dataclass
class WaveResult:
    """Result of one wave attempt (spec's ``TaskResult`` for waves)."""

    wave_id: str
    task_id: str
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out

    @property
    def quality_score(self) -> float:
        return float(self.metadata.get("quality_score", 0.0))


def _result_from_payload(payload: dict[str, Any]) -> WaveResult:
    return WaveResult(
        wave_id=str(payload["wave_id"]),
        task_id=str(payload["task_id"]),
        output=payload.get("output"),
        metadata=dict(payload.get("metadata", {})),
        error=payload.get("error"),
        timed_out=bool(payload.get("timed_out", False)),
    )


# --------------------------------------------------------------------------
# Expansion
# --------------------------------------------------------------------------


@runtime_checkable
class WaveExpander(Protocol):
    """Expand a task into waves (parallel branches)."""

    async def expand(self, task: WaveTask, max_waves: int) -> list[Wave]: ...


class MultiStrategyExpander:
    """Create waves that use distinct reasoning strategies.

    Each wave gets a deep copy of the task context plus its own
    ``reasoning_strategy`` key — contexts are fully isolated.
    """

    strategies: tuple[str, ...] = (
        "chain_of_thought",
        "tree_of_thought",
        "self_critique",
    )

    def __init__(
        self,
        strategies: tuple[str, ...] | None = None,
        *,
        timeout_ms: int = 30_000,
    ) -> None:
        if strategies is not None:
            self.strategies = strategies
        self._timeout_ms = timeout_ms

    async def expand(self, task: WaveTask, max_waves: int) -> list[Wave]:
        waves: list[Wave] = []
        for i, strategy in enumerate(self.strategies[:max_waves]):
            context = copy.deepcopy(task.context)
            context["reasoning_strategy"] = strategy
            waves.append(
                Wave(
                    id=f"wave_{i}",
                    agent_ids=[f"agent_{strategy}"],
                    context=context,
                    timeout_ms=self._timeout_ms,
                )
            )
        return waves


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


@runtime_checkable
class ResultComparator(Protocol):
    """Compare wave results and pick the best."""

    def compare(self, results: list[WaveResult]) -> WaveResult: ...


class QualityComparator:
    """Pick the result with the highest ``metadata["quality_score"]``.

    Deterministic: ties resolve to the earliest wave in input order.
    """

    def compare(self, results: list[WaveResult]) -> WaveResult:
        if not results:
            raise WaveEnsembleError("no successful wave results to compare")
        return max(results, key=lambda r: r.quality_score)


@runtime_checkable
class AsyncResultComparator(Protocol):
    """Async comparator variant (e.g. an LLM judge)."""

    async def compare(self, results: list[WaveResult]) -> WaveResult: ...


class LLMJudgeComparator:
    """Protocol stub: use an LLM to judge which result is better.

    Phase 2 (SPEC-070226-b624 non-goal for phase 1) — intentionally not
    implemented; wire an LLM client and implement pairwise judging here.
    """

    async def compare(self, results: list[WaveResult]) -> WaveResult:
        raise NotImplementedError("LLMJudgeComparator is a Phase 2 stub (SPEC-070226-b624)")


# --------------------------------------------------------------------------
# Checkpointing (ADR-056)
# --------------------------------------------------------------------------


@runtime_checkable
class CheckpointStore(Protocol):
    """Append-only store of ADR-056 task checkpoints."""

    async def save(self, checkpoint: TaskCheckpoint) -> None: ...

    async def load(self, task_id: str) -> tuple[TaskCheckpoint, ...]: ...


class InMemoryCheckpointStore:
    """In-memory CheckpointStore (reference implementation for tests/dev)."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, list[TaskCheckpoint]] = {}
        self._lock = asyncio.Lock()

    async def save(self, checkpoint: TaskCheckpoint) -> None:
        async with self._lock:
            self._checkpoints.setdefault(checkpoint.task_id, []).append(checkpoint)

    async def load(self, task_id: str) -> tuple[TaskCheckpoint, ...]:
        async with self._lock:
            return tuple(sorted(self._checkpoints.get(task_id, []), key=lambda c: c.sequence))

    async def next_sequence(self, task_id: str) -> int:
        async with self._lock:
            existing = self._checkpoints.get(task_id, [])
            return max((c.sequence for c in existing), default=-1) + 1


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

WaveRunner = Callable[[Wave, WaveTask], Awaitable[WaveResult]]


@dataclass
class SuperPlannerConfig:
    """Configuration for wave-ensemble orchestration."""

    max_waves: int = 3
    timeout_ms: int = 60_000
    recovery_strategy: Literal["resume", "restart"] = "resume"
    recipe_version: str = "0"
    code_registry_version: str = "0"
    #: How many times recovery may resume one task before quarantining it
    #: (ADR-056's crash-loop breaker). Counted from the task's own checkpoints,
    #: so it survives the process crash it is counting.
    max_recovery_attempts: int = 3


class WaveOrchestrator:
    """Runs a wave ensemble: expand → checkpoint → gather → checkpoint → compare.

    Injected collaborators:
      - ``runner`` executes one wave (the agents) and returns a WaveResult;
      - ``expander`` partitions the task into waves (default multi-strategy);
      - ``comparator`` picks the winner (default max quality_score);
      - ``checkpoint_store`` persists ADR-056 checkpoints;
      - ``emit`` receives ADR-037 events.
    """

    def __init__(
        self,
        runner: WaveRunner,
        *,
        expander: WaveExpander | None = None,
        comparator: ResultComparator | None = None,
        checkpoint_store: CheckpointStore | None = None,
        config: SuperPlannerConfig | None = None,
        emit: EmitFn | None = None,
    ) -> None:
        self._runner = runner
        self._config = config or SuperPlannerConfig()
        self._expander = expander or MultiStrategyExpander()
        self._comparator = comparator or QualityComparator()
        self._checkpoint_store = checkpoint_store or InMemoryCheckpointStore()
        self._emit: EmitFn = emit or _noop_emit

    async def execute(self, task: WaveTask) -> WaveResult:
        """Execute the task as a wave ensemble and return the best result.

        With ``recovery_strategy="resume"``, a prior ``waves_complete``
        checkpoint short-circuits execution: saved results are compared and
        returned without re-running any wave.
        """
        if self._config.recovery_strategy == "resume":
            recovered = await self._recover(task.id)
            if recovered is not None:
                return recovered

        waves = await self._expander.expand(task, self._config.max_waves)
        await self._checkpoint(
            task.id,
            CheckpointKind.WAVE_FAN_OUT,
            {
                "state": STATE_WAVES_PLANNED,
                "task_id": task.id,
                "wave_ids": [w.id for w in waves],
            },
        )
        self._emit(EVENT_WAVES_PLANNED, task_id=task.id, wave_count=len(waves))

        ordered = sorted(waves, key=lambda w: -w.priority)
        gathered = await asyncio.gather(
            *(self._run_wave(wave, task) for wave in ordered),
            return_exceptions=True,
        )
        results: list[WaveResult] = []
        for wave, outcome in zip(ordered, gathered, strict=True):
            if isinstance(outcome, asyncio.CancelledError):
                # A cancelled wave is a crash, not a comparable failure:
                # propagate so the caller can resume from the checkpoint.
                raise outcome
            if isinstance(outcome, BaseException):
                results.append(WaveResult(wave_id=wave.id, task_id=task.id, error=str(outcome)))
            else:
                results.append(outcome)

        await self._checkpoint(
            task.id,
            CheckpointKind.WAVE_COMPLETED,
            {
                "state": STATE_WAVES_COMPLETE,
                "task_id": task.id,
                "results": [asdict(r) for r in results],
            },
        )
        return self._compare(task.id, results)

    async def recover(self, task_id: str) -> WaveResult | None:
        """Recovery path: reuse saved results if waves already completed.

        Returns ``None`` when there is no ``waves_complete`` checkpoint
        (caller should re-run :meth:`execute`).
        """
        return await self._recover(task_id)

    async def _recover(self, task_id: str) -> WaveResult | None:
        """Decide what to do with this task's checkpoints, and say so.

        Returns a result only when the recorded work is safe to reuse. `None`
        means "run it": either there is nothing to recover, or recovery refused
        what it found. Every branch emits, because a recovery that cannot be
        told from a fresh run is not inspectable (#624).
        """
        checkpoints = await self._checkpoint_store.load(task_id)
        if not checkpoints:
            return None

        quarantine = self._quarantine_reason(checkpoints)
        if quarantine is not None:
            self._emit(EVENT_RECOVERY_QUARANTINED, task_id=task_id, reason=quarantine)
            raise WaveRecoveryQuarantined(quarantine)

        drift = self._version_drift(checkpoints)
        if drift is not None:
            self._emit(EVENT_RECOVERY_REFUSED, task_id=task_id, **drift)
            return None

        await self._checkpoint(task_id, CheckpointKind.RECOVERY_ATTEMPTED, {"task_id": task_id})
        state = replay(checkpoints)
        for checkpoint in reversed(checkpoints):
            if checkpoint.payload.get("state") == STATE_WAVES_COMPLETE:
                results = [_result_from_payload(p) for p in checkpoint.payload.get("results", [])]
                self._emit(
                    EVENT_RECOVERY_RESUMED,
                    task_id=task_id,
                    complete=True,
                    **_resume_fields(state),
                )
                return self._compare(task_id, results, recovered=True)

        # Interrupted before the waves finished. There is no result to reuse,
        # but what the run left open is knowable and was previously invisible:
        # `replay` folds it, and the caller sees it rather than a silent re-run.
        self._emit(EVENT_RECOVERY_RESUMED, task_id=task_id, complete=False, **_resume_fields(state))
        return None

    def _version_drift(self, checkpoints: tuple[TaskCheckpoint, ...]) -> dict[str, str] | None:
        """The mismatch that makes these checkpoints unusable, or None.

        The checkpoint has recorded both versions since ADR-056 and recovery
        compared neither, so an upgraded deployment resumed results produced by
        code that no longer exists and reported them as its own (#624). The
        newest checkpoint decides: they are written by one run under one
        configuration, and a task whose oldest checkpoint predates an upgrade
        is exactly the case this refuses.
        """
        newest = max(checkpoints, key=lambda c: c.sequence)
        if version_compatible(
            newest,
            current_recipe_version=self._config.recipe_version,
            current_code_registry_version=self._config.code_registry_version,
        ):
            return None
        return {
            "checkpoint_recipe_version": newest.recipe_version,
            "current_recipe_version": self._config.recipe_version,
            "checkpoint_code_registry_version": newest.code_registry_version,
            "current_code_registry_version": self._config.code_registry_version,
        }

    def _quarantine_reason(self, checkpoints: tuple[TaskCheckpoint, ...]) -> str | None:
        """Why this task must stop being recovered, or None.

        A crash loop is a *process* crash, so an in-process breaker cannot count
        it — the count has to survive the restart it is counting. Recovery
        records its own attempt as a checkpoint, and the store that survives the
        restart is therefore the one that holds the tally; `CrashLoopPolicy`
        still makes the decision, as ADR-056 says it does.
        """
        attempts = sum(1 for c in checkpoints if c.kind is CheckpointKind.RECOVERY_ATTEMPTED)
        if attempts == 0:
            return None
        breaker = CircuitBreaker(
            failure_threshold=self._config.max_recovery_attempts, name=f"recovery.{id(self)}"
        )
        policy = CrashLoopPolicy()
        for _ in range(attempts):
            policy.record_crash(breaker)
        if not policy.should_quarantine(breaker):
            return None
        return (
            f"recovered {attempts} time(s) without completing; "
            f"the limit is {self._config.max_recovery_attempts}"
        )

    async def _run_wave(self, wave: Wave, task: WaveTask) -> WaveResult:
        self._emit(EVENT_WAVE_STARTED, wave_id=wave.id, task_id=task.id)
        try:
            result = await asyncio.wait_for(
                self._runner(wave, task), timeout=wave.timeout_ms / 1000.0
            )
        except TimeoutError:
            self._emit(EVENT_WAVE_FAILED, wave_id=wave.id, task_id=task.id, error="timeout")
            return WaveResult(
                wave_id=wave.id,
                task_id=task.id,
                error=f"wave timed out after {wave.timeout_ms}ms",
                timed_out=True,
            )
        except Exception as exc:
            self._emit(EVENT_WAVE_FAILED, wave_id=wave.id, task_id=task.id, error=str(exc))
            return WaveResult(wave_id=wave.id, task_id=task.id, error=str(exc))
        self._emit(
            EVENT_WAVE_COMPLETED,
            wave_id=wave.id,
            task_id=task.id,
            quality_score=result.quality_score,
        )
        return result

    def _compare(
        self, task_id: str, results: list[WaveResult], *, recovered: bool = False
    ) -> WaveResult:
        successes = [r for r in results if r.ok]
        if not successes:
            errors = "; ".join(f"{r.wave_id}: {r.error}" for r in results)
            raise WaveEnsembleError(f"all waves failed for task {task_id!r}: {errors}")
        best = self._comparator.compare(successes)
        self._emit(
            EVENT_WAVES_COMPARED,
            task_id=task_id,
            winner=best.wave_id,
            candidates=len(successes),
            recovered=recovered,
        )
        return best

    async def _checkpoint(
        self, task_id: str, kind: CheckpointKind, payload: dict[str, Any]
    ) -> None:
        store = self._checkpoint_store
        if isinstance(store, InMemoryCheckpointStore):
            sequence = await store.next_sequence(task_id)
        else:
            sequence = len(await store.load(task_id))
        await store.save(
            TaskCheckpoint(
                task_id=task_id,
                sequence=sequence,
                kind=kind,
                payload=payload,
                recipe_version=self._config.recipe_version,
                code_registry_version=self._config.code_registry_version,
                created_at=datetime.now(UTC),
            )
        )


# --------------------------------------------------------------------------
# Graph integration (ADR-062): NodeStrategy-compatible wrapper
# --------------------------------------------------------------------------


class WaveEnsembleOutput(BaseModel):
    """Typed output of a wave-ensemble graph node."""

    task_id: str = ""
    winner_wave_id: str = ""
    quality_score: float = 0.0
    output: str = ""
    wave_count: int = 0


class WaveEnsembleStrategy:
    """NodeStrategy-compatible wrapper (see ``maistro.graph.strategy``).

    Satisfies the structural :class:`maistro.graph.strategy.NodeStrategy`
    protocol so wave orchestration can sit in a GraphRun as a regular node:
    it builds the ensemble prompt, and :meth:`run_ensemble` performs the
    actual wave orchestration, caching the winner so ``score_output`` and
    ``update_blackboard`` reflect the ensemble outcome.
    """

    role: AgentRole = AgentRole.CONDUCTOR
    output_type: type[BaseModel] = WaveEnsembleOutput

    def __init__(self, orchestrator: WaveOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def run_ensemble(self, task: WaveTask) -> WaveEnsembleOutput:
        best = await self._orchestrator.execute(task)
        return WaveEnsembleOutput(
            task_id=task.id,
            winner_wave_id=best.wave_id,
            quality_score=best.quality_score,
            output=str(best.output) if best.output is not None else "",
            wave_count=int(best.metadata.get("wave_count", 0)),
        )

    def build_user_prompt(
        self,
        task: GraphTask,
        blackboard: GraphBlackboard,
        plan: PlanOutput | None,
        code: CodeOutput | None,
        review: ReviewOutput | None,
    ) -> str:
        constraints = "\n".join(f"- {c}" for c in task.constraints) if task.constraints else "None"
        return (
            f"Task: {task.description}\n\n"
            f"Workspace: {task.workspace}\n"
            f"Constraints:\n{constraints}\n\n"
            "Orchestrate parallel solution waves and return the best result."
        )

    def score_output(self, output: BaseModel) -> float:
        if isinstance(output, WaveEnsembleOutput):
            return output.quality_score
        return 0.0

    def update_blackboard(
        self,
        output: BaseModel,
        blackboard: GraphBlackboard,
    ) -> GraphBlackboard:
        if isinstance(output, WaveEnsembleOutput):
            annotations = dict(blackboard.node_annotations)
            annotations["wave_ensemble"] = (
                f"winner={output.winner_wave_id} quality={output.quality_score:.3f}"
            )
            return blackboard.model_copy(update={"node_annotations": annotations})
        return blackboard


def task_to_wave_task(task: GraphTask) -> WaveTask:
    """Adapt a graph task into a wave-ensemble task."""

    return WaveTask(
        id=uuid.uuid4().hex[:12],
        description=task.description,
        context={"workspace": task.workspace, "constraints": list(task.constraints)},
    )
