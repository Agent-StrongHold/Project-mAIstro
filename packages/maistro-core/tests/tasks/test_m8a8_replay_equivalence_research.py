"""M8-A8 research harness — replay, checkpoint, and deterministic-state
equivalence over the durable execution seams.

Issue #888 (leaf of epic #880, M8 exploratory research). Hypothesis under
study: for durable/event-driven MAIstro subsystems, replay equivalence and
idempotent recovery properties detect correctness failures that line coverage
and endpoint tests cannot.

This module is a RESEARCH ARTIFACT, not product code. Unlike the offline M8
harnesses (#915/#919/#920), the seams this issue names — the task-checkpoint
fold (SPEC-256/ADR-056), the idempotent event loop (SPEC-070226-b234/ADR-086),
the recovery-event identity (#462/#61), and the Run/NodeRun/Attempt lifecycle
(ADR-082426-a47f/e3ff/f170) — are offline-pure production functions, so the
harness drives the real seams directly on synthetic histories instead of a
replica of them. The experiment is the issue's own: execute representative
histories to a canonical final state, discard reconstructible runtime state,
replay from durable history/checkpoints, and compare normalized results.

Measured candidate properties (issue text, mapped to sections below):

- ``replay(history)`` is stable/idempotent and delivery-order insensitive;
- checkpoint + suffix replay equals full replay — at the ensemble recovery
  boundary (the only place production consumes the checkpoint fold: it
  re-reads the whole history, so segmentation across restarts must not change
  the recovered outcome) and at the lifecycle boundary (the store row IS the
  checkpoint, so midpoint-record + suffix log must equal full-log replay);
- duplicate delivery does not duplicate canonical effects — event-loop claim
  dedupe, recovery-event identity, and the fold's own duplicate-row fidelity
  (where a fidelity constraint IS found and recorded, not hidden);
- terminal state never regresses after replay — absorbing transition tables
  and revival refusal, measured over the whole status space;
- equivalent durable histories reconstruct equivalent observable state where
  ordering contracts permit — permutation-invariant projections and
  interleaving-equivalent reconstructions.

Findings the harness pins (full analysis in
``docs/research/888-replay-checkpoint-equivalence.md``):

- the checkpoint fold double-counts ``SPEND_UPDATE`` under duplicate rows;
  latent, because no production writer emits that kind at this head (measured
  by the AST surface scan below) — a fidelity constraint, not a live defect;
- the Run-transition table admits WAITING→PAUSED for a NodeRun carrying an
  accepted outcome, but the record validator rejects the resulting state: the
  replay state space is (status, has-accepted-outcome), not status alone;
  no production writer takes that move at this head (the reconciler's pause
  path short-circuits WAITING records), so this is a seam contract to control
  during replay — likewise not a live defect;
- recovery's durable tally counts ``RECOVERY_ATTEMPTED`` rows without
  distinguishing a completed recovery from an interrupted one, so repeated
  recovery of a *completed* task is not idempotent: the fourth — successful —
  recovery opens the crash-loop breaker and hides the completed result.
  Latent at this head (``recover`` has no production caller yet), recorded as
  a recovery-idempotence constraint rather than expected behavior.

Trust boundary (epic contract, enforced by construction and by test):

- Everything here is ADVISORY EVIDENCE. The harness writes no durable store
  (only the reference in-memory implementations production itself ships for
  tests/dev), reads no Goal, touches no authorization path, and changes no
  product code. Its maistro imports are pinned to an explicit allowlist by an
  AST test, and a second AST test fails if any production module ever imports
  this harness — research evidence cannot become an execution authority.
- No test asserts wall-clock timing. Recovery decisions, folds and
  projections are compared by value with injected timestamps only; the
  workload-size test ties the research note's runtime quote to an exact,
  deterministic workload instead of a duration.
"""

from __future__ import annotations

import ast
import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from maistro.events.durable_log import InMemoryEventLog, LoggedEvent
from maistro.events.invocations import InMemoryInvocationStore, InvocationStatus
from maistro.events.processing import (
    HANDLER_FAILED_EVENT,
    HandlerCallError,
    process_events,
    process_events_batch,
)
from maistro.events.trigger_store import InMemoryTriggerStore, TriggerDefinition
from maistro.graph import Graph, Node
from maistro.orchestrator.waves.ensemble import (
    EVENT_RECOVERY_QUARANTINED,
    EVENT_RECOVERY_REFUSED,
    EVENT_RECOVERY_RESUMED,
    STATE_WAVES_COMPLETE,
    STATE_WAVES_PLANNED,
    InMemoryCheckpointStore,
    SuperPlannerConfig,
    WaveOrchestrator,
    WaveRecoveryQuarantined,
    WaveResult,
    WaveTask,
)
from maistro.runs.lifecycle import (
    ATTEMPT_TRANSITIONS,
    RUN_TRANSITIONS,
    InvalidLifecycleTransition,
    UnearnedRunCompletion,
    check_completion_is_earned,
    latest_node_runs,
    lease_is_expired,
    reclaim_attempt,
    refuse_completion_under_terminal_run,
    renew_attempt_lease,
    settle_open_node_run,
    transition_attempt,
    transition_node_run,
    transition_path,
    transition_run,
)
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    CancellationCause,
    ExecutionLease,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.recovery_events import (
    RECOVERY_EVENT_TYPE,
    CanonicalRecoveryEventSink,
    RecoveryDispositionEvent,
    disposition_of,
)
from maistro.tasks.checkpoint import CheckpointKind, TaskCheckpoint
from maistro.tasks.recovery import version_compatible
from maistro.tasks.replay import ResumeState, replay
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

#: Explicit evidence-only contract marker, asserted by a test so it cannot
#: silently rot. Nothing outside this module may treat M8-A8 output as
#: authorization; the canonical execution authority remains
#: Goal -> Graph -> Run -> NodeRun -> Attempt with its own stores.
ADVISORY_ONLY = True

#: Fixed epoch so every lifecycle replay compares injected timestamps only.
T0 = datetime(2026, 8, 8, tzinfo=UTC)
SEED = 20260808

#: The maistro modules this harness may import, pinned by test. Anything the
#: experiment cannot justify reading is outside the set — in particular every
#: store implementation beyond the reference in-memory ones, the service/
#: wiring/container layer, and the server package.
HARNESS_IMPORT_ALLOWLIST = frozenset(
    {
        "maistro.events.durable_log",
        "maistro.events.invocations",
        "maistro.events.processing",
        "maistro.events.trigger_store",
        "maistro.graph",
        "maistro.orchestrator.waves.ensemble",
        "maistro.runs.lifecycle",
        "maistro.runs.model",
        "maistro.runs.recovery_events",
        "maistro.tasks.checkpoint",
        "maistro.tasks.recovery",
        "maistro.tasks.replay",
        "maistro.testing",
    }
)


def _t(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _src_root() -> Path:
    # .../packages/maistro-core/tests/tasks/<file>.py -> .../packages/maistro-core/src
    return Path(__file__).resolve().parents[2] / "src"


def _maistro_imports_of(path: Path) -> set[str]:
    """``maistro.*`` modules a file imports (AST, direct only, full paths)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            if name.split(".")[0] == "maistro":
                found.add(name)
    return found


# ---------------------------------------------------------------------------
# Checkpoint-history fixtures (task fold + ensemble sections)
# ---------------------------------------------------------------------------


def _checkpoint(
    sequence: int,
    kind: CheckpointKind,
    payload: dict[str, Any],
    *,
    task_id: str = "task-1",
    recipe_version: str = "v1",
    code_registry_version: str | None = None,
) -> TaskCheckpoint:
    return TaskCheckpoint(
        task_id=task_id,
        sequence=sequence,
        kind=kind,
        payload=payload,
        recipe_version=recipe_version,
        code_registry_version=(
            recipe_version if code_registry_version is None else code_registry_version
        ),
        created_at=_t(sequence + 1),
    )


def _random_checkpoint_history(rng: random.Random, *, spend_rows: int) -> list[TaskCheckpoint]:
    """A legal-looking history: matched tool-call pairs, per-wave records,
    approval gates, spend updates — every kind the fold understands."""
    checkpoints: list[TaskCheckpoint] = []
    sequence = 0
    for call in [f"c{i}" for i in range(rng.randint(1, 4))]:
        checkpoints.append(
            _checkpoint(sequence, CheckpointKind.TOOL_CALL_ABOUT_TO_FIRE, {"call_id": call})
        )
        sequence += 1
        if rng.random() < 0.7:
            checkpoints.append(
                _checkpoint(sequence, CheckpointKind.TOOL_CALL_DONE, {"call_id": call})
            )
            sequence += 1
    for wave in [f"w{i}" for i in range(rng.randint(1, 3))]:
        checkpoints.append(_checkpoint(sequence, CheckpointKind.WAVE_FAN_OUT, {"wave_id": wave}))
        sequence += 1
        terminal = rng.choice([CheckpointKind.WAVE_COMPLETED, CheckpointKind.WAVE_FAILED])
        checkpoints.append(_checkpoint(sequence, terminal, {"wave_id": wave}))
        sequence += 1
    for gate in [f"g{i}" for i in range(rng.randint(0, 2))]:
        checkpoints.append(
            _checkpoint(sequence, CheckpointKind.APPROVAL_GATE_RAISED, {"gate_id": gate})
        )
        sequence += 1
        if rng.random() < 0.5:
            checkpoints.append(
                _checkpoint(sequence, CheckpointKind.APPROVAL_GATE_ANSWERED, {"gate_id": gate})
            )
            sequence += 1
    for _ in range(spend_rows):
        checkpoints.append(
            _checkpoint(
                sequence, CheckpointKind.SPEND_UPDATE, {"delta": round(rng.uniform(-5, 20), 2)}
            )
        )
        sequence += 1
    return checkpoints


# ---------------------------------------------------------------------------
# Contract: evidence only
# ---------------------------------------------------------------------------


def test_advisory_only_marker() -> None:
    assert ADVISORY_ONLY is True


def test_no_production_module_imports_this_harness() -> None:
    """Research evidence must not become an execution authority.

    Scans every production module under packages/*/src: none may import this
    harness (or anything test-shaped). The experiment reads production seams;
    production must never read back.
    """
    repo_root = Path(__file__).resolve().parents[4]
    offenders: list[str] = []
    scanned = 0
    for path in sorted((repo_root / "packages").glob("*/src/**/*.py")):
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - generated trees only
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if "test_m8a8" in name or name.startswith("tests."):
                    offenders.append(f"{path.relative_to(repo_root)}: {name}")
    assert scanned > 100, f"production scan scanned only {scanned} files; glob is broken"
    assert offenders == [], f"production imports research harness: {offenders}"


def test_harness_imports_within_pinned_allowlist() -> None:
    own = _maistro_imports_of(Path(__file__).resolve())
    outside = own - HARNESS_IMPORT_ALLOWLIST
    assert outside == set(), f"harness imports outside its allowlist: {sorted(outside)}"


def test_checkpoint_kind_surface_is_measured() -> None:
    """Fidelity measurement: which checkpoint kinds does production write?

    The fold (tasks/replay.py) understands every kind; the writers at this
    head are exactly the ensemble's two task-level markers plus recovery's own
    counter. The difference is fold surface no producer exercises — the
    duplicate-SPEND_UPDATE fidelity constraint below is latent precisely
    because of this gap.
    """
    core_src = _src_root() / "maistro"
    fold_files = {"tasks/replay.py", "tasks/checkpoint.py"}
    written: set[str] = set()
    supported: set[str] = set()
    for path in core_src.rglob("*.py"):
        rel = path.relative_to(core_src).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "CheckpointKind"
        }
        if rel in fold_files:
            supported |= used
        else:
            written |= used
    assert written == {"WAVE_FAN_OUT", "WAVE_COMPLETED", "RECOVERY_ATTEMPTED"}
    # The fold branches on these eight; RECOVERY_ATTEMPTED is written but only
    # ever *counted* (quarantine tally), never folded; MEMORY_PROMOTE is
    # referenced by no code outside its definition at this head.
    assert supported == {kind.name for kind in CheckpointKind} - {
        "MEMORY_PROMOTE",
        "RECOVERY_ATTEMPTED",
    }
    never_referenced = {kind.name for kind in CheckpointKind} - written - supported
    assert never_referenced == {"MEMORY_PROMOTE"}


# ---------------------------------------------------------------------------
# Candidate property 1: replay(history) is stable / idempotent
# ---------------------------------------------------------------------------


def test_fold_replay_is_idempotent() -> None:
    rng = random.Random(SEED)
    for _ in range(10):
        history = tuple(_random_checkpoint_history(rng, spend_rows=rng.randint(0, 4)))
        first = replay(history)
        assert replay(history) == first
        assert replay(history) == first  # no hidden per-call state


def test_fold_delivery_order_insensitive() -> None:
    rng = random.Random(SEED + 1)
    for _ in range(10):
        history = _random_checkpoint_history(rng, spend_rows=3)
        expected = replay(tuple(history))
        for _ in range(5):
            shuffled = list(history)
            rng.shuffle(shuffled)
            assert replay(tuple(shuffled)) == expected


def test_fold_hand_checked_arithmetic() -> None:
    history = (
        _checkpoint(0, CheckpointKind.TOOL_CALL_ABOUT_TO_FIRE, {"call_id": "c1"}),
        _checkpoint(1, CheckpointKind.TOOL_CALL_DONE, {"call_id": "c1"}),
        _checkpoint(2, CheckpointKind.TOOL_CALL_ABOUT_TO_FIRE, {"call_id": "c2"}),
        _checkpoint(3, CheckpointKind.WAVE_FAN_OUT, {"wave_id": "w1"}),
        _checkpoint(4, CheckpointKind.WAVE_COMPLETED, {"wave_id": "w1"}),
        _checkpoint(5, CheckpointKind.WAVE_FAN_OUT, {"wave_id": "w2"}),
        _checkpoint(6, CheckpointKind.WAVE_FAILED, {"wave_id": "w2"}),
        _checkpoint(7, CheckpointKind.APPROVAL_GATE_RAISED, {"gate_id": "g1"}),
        _checkpoint(8, CheckpointKind.APPROVAL_GATE_ANSWERED, {"gate_id": "g1"}),
        _checkpoint(9, CheckpointKind.APPROVAL_GATE_RAISED, {"gate_id": "g2"}),
        _checkpoint(10, CheckpointKind.SPEND_UPDATE, {"delta": 1.5}),
        _checkpoint(11, CheckpointKind.SPEND_UPDATE, {"delta": 0.25}),
    )
    assert replay(history) == ResumeState(
        open_tool_calls=frozenset({"c2"}),
        wave_status={"w1": "completed", "w2": "failed"},
        cumulative_spend=1.75,
        pending_approval_gates=frozenset({"g2"}),
    )


def test_task_level_markers_do_not_pollute_per_wave_status() -> None:
    """The #624 shape: task-level fan-out/completion markers (payload has
    ``state``, ``wave_ids`` plural) contribute no per-wave record, so a history
    that mixes both encodings still folds to the per-wave truth."""
    history = (
        _checkpoint(0, CheckpointKind.WAVE_FAN_OUT, {"wave_id": "w1"}),
        _checkpoint(
            1,
            CheckpointKind.WAVE_FAN_OUT,
            {"state": STATE_WAVES_PLANNED, "task_id": "task-1", "wave_ids": ["w1", "w2"]},
        ),
        _checkpoint(2, CheckpointKind.WAVE_COMPLETED, {"wave_id": "w1"}),
        _checkpoint(
            3,
            CheckpointKind.WAVE_COMPLETED,
            {"state": STATE_WAVES_COMPLETE, "task_id": "task-1", "results": []},
        ),
    )
    assert replay(history).wave_status == {"w1": "completed"}


# ---------------------------------------------------------------------------
# Candidate property 3 (fold half): duplicate-delivery fidelity
# ---------------------------------------------------------------------------


def test_duplicate_delivery_of_set_like_kinds_is_idempotent() -> None:
    """Delivering every row twice changes nothing the fold projects into sets:
    add/discard over one element absorbs the repeat."""
    history = (
        _checkpoint(0, CheckpointKind.TOOL_CALL_ABOUT_TO_FIRE, {"call_id": "c1"}),
        _checkpoint(1, CheckpointKind.WAVE_COMPLETED, {"wave_id": "w1"}),
        _checkpoint(2, CheckpointKind.APPROVAL_GATE_RAISED, {"gate_id": "g1"}),
    )
    single = replay(history)
    duplicated = replay(history + history)
    assert duplicated.open_tool_calls == single.open_tool_calls == frozenset({"c1"})
    assert duplicated.wave_status == single.wave_status == {"w1": "completed"}
    assert duplicated.pending_approval_gates == single.pending_approval_gates


def test_duplicate_spend_delivery_double_counts_recorded() -> None:
    """MEASURED FIDELITY CONSTRAINT (not a live defect at this head — the
    surface-scan test shows no production writer emits SPEND_UPDATE).

    The fold adds each row's delta, so a duplicated row (the same sequence
    delivered twice by a store that does not key-dedupe) double-counts spend.
    Any future replay-based spend assertion must dedupe by (task_id, sequence)
    before folding, or constrain its store contract to key uniqueness.
    """
    once = _checkpoint(0, CheckpointKind.SPEND_UPDATE, {"delta": 2.0})
    assert replay((once,)).cumulative_spend == pytest.approx(2.0)
    assert replay((once, once)).cumulative_spend == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Ensemble fixtures: the recovery boundary where production consumes the fold
# ---------------------------------------------------------------------------


@dataclass
class _Runner:
    """Deterministic wave runner: same wave id, same result, every run."""

    calls: list[str]

    async def __call__(self, wave: Any, task: WaveTask) -> WaveResult:
        self.calls.append(wave.id)
        index = int(wave.id.split("_")[1])
        return WaveResult(
            wave_id=wave.id,
            task_id=task.id,
            output=f"out::{wave.id}",
            metadata={"quality_score": 1.0 / (index + 1)},
        )


def _orchestrator(
    store: InMemoryCheckpointStore,
    runner: _Runner,
) -> tuple[WaveOrchestrator, list[tuple[str, dict[str, Any]]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    orchestrator = WaveOrchestrator(
        runner,
        checkpoint_store=store,
        config=SuperPlannerConfig(
            recipe_version="v1",
            code_registry_version="v1",
            max_recovery_attempts=3,
        ),
        emit=lambda event, **fields: events.append((event, fields)),
    )
    return orchestrator, events


def _task() -> WaveTask:
    return WaveTask(id="task-1", description="research fixture")


def _planned_marker(
    sequence: int, *, recipe_version: str = "v1", code_registry_version: str | None = None
) -> TaskCheckpoint:
    return _checkpoint(
        sequence,
        CheckpointKind.WAVE_FAN_OUT,
        {
            "state": STATE_WAVES_PLANNED,
            "task_id": "task-1",
            "wave_ids": ["wave_0", "wave_1", "wave_2"],
        },
        recipe_version=recipe_version,
        code_registry_version=code_registry_version,
    )


def _completed_marker(sequence: int, *, recipe_version: str = "v1") -> TaskCheckpoint:
    results = [
        WaveResult(
            wave_id=f"wave_{i}",
            task_id="task-1",
            output=f"out::wave_{i}",
            metadata={"quality_score": 1.0 / (i + 1)},
        )
        for i in range(3)
    ]
    return _checkpoint(
        sequence,
        CheckpointKind.WAVE_COMPLETED,
        {
            "state": STATE_WAVES_COMPLETE,
            "task_id": "task-1",
            "results": [asdict(result) for result in results],
        },
        recipe_version=recipe_version,
    )


async def _seed(store: InMemoryCheckpointStore, *checkpoints: TaskCheckpoint) -> None:
    for checkpoint in checkpoints:
        await store.save(checkpoint)


def _seed_sync(store: InMemoryCheckpointStore, *checkpoints: TaskCheckpoint) -> None:
    asyncio.run(_seed(store, *checkpoints))


def _load_sync(store: InMemoryCheckpointStore) -> tuple[TaskCheckpoint, ...]:
    return asyncio.run(store.load("task-1"))


def _fresh_baseline() -> tuple[WaveResult, list[str], InMemoryCheckpointStore]:
    store: InMemoryCheckpointStore = InMemoryCheckpointStore()
    runner = _Runner(calls=[])
    orchestrator, _ = _orchestrator(store, runner)
    winner = asyncio.run(orchestrator.execute(_task()))
    return winner, runner.calls, store


# ---------------------------------------------------------------------------
# Recovery decision is a pure function of the checkpoint history
# ---------------------------------------------------------------------------


def test_recovery_decision_is_pure_function_of_history() -> None:
    winner, _, _ = _fresh_baseline()
    recovered_results: list[WaveResult] = []
    event_logs: list[list[tuple[str, dict[str, Any]]]] = []
    for _ in range(2):
        # The identical durable history, a fresh orchestrator each time: the
        # recovery decision and recovered result must not depend on any
        # process-local state.
        store: InMemoryCheckpointStore = InMemoryCheckpointStore()
        _seed_sync(store, _planned_marker(0), _completed_marker(1))
        runner = _Runner(calls=[])
        orchestrator, events = _orchestrator(store, runner)
        recovered = asyncio.run(orchestrator.recover("task-1"))
        assert recovered is not None
        recovered_results.append(recovered)
        event_logs.append(events)
    assert recovered_results[0] == recovered_results[1] == winner
    assert event_logs[0] == event_logs[1]
    resumed = [entry for entry in event_logs[0] if entry[0] == EVENT_RECOVERY_RESUMED]
    assert resumed and resumed[0][1]["complete"] is True


def test_version_drift_refusal_is_stable_and_blocking() -> None:
    winner, _, _ = _fresh_baseline()
    drifted_store: InMemoryCheckpointStore = InMemoryCheckpointStore()
    _seed_sync(drifted_store, _planned_marker(0, recipe_version="v0"))
    refusal_logs: list[list[tuple[str, dict[str, Any]]]] = []
    for _ in range(2):
        runner = _Runner(calls=[])
        orchestrator, events = _orchestrator(drifted_store, runner)
        assert asyncio.run(orchestrator.recover("task-1")) is None
        assert runner.calls == []  # nothing reused, nothing re-run
        refusal_logs.append(events)
    assert refusal_logs[0] == refusal_logs[1]
    refusals = [entry for entry in refusal_logs[0] if entry[0] == EVENT_RECOVERY_REFUSED]
    assert refusals and refusals[0][1]["checkpoint_recipe_version"] == "v0"

    # Code-registry drift alone also blocks: the two version axes are
    # measured independently, so a recipe-only pass must not mask it.
    registry_drifted_store: InMemoryCheckpointStore = InMemoryCheckpointStore()
    _seed_sync(registry_drifted_store, _planned_marker(0, code_registry_version="v0"))
    runner = _Runner(calls=[])
    orchestrator, events = _orchestrator(registry_drifted_store, runner)
    assert asyncio.run(orchestrator.recover("task-1")) is None
    assert runner.calls == []
    refusals = [entry for entry in events if entry[0] == EVENT_RECOVERY_REFUSED]
    assert refusals and refusals[0][1]["checkpoint_code_registry_version"] == "v0"
    assert refusals[0][1]["checkpoint_recipe_version"] == "v1"

    # The identical history under the matching version recovers: the drift
    # check, not the fold, was the blocker.
    compatible_store: InMemoryCheckpointStore = InMemoryCheckpointStore()
    _seed_sync(compatible_store, _planned_marker(0), _completed_marker(1))
    newest = max(_load_sync(compatible_store), key=lambda c: c.sequence)
    assert version_compatible(
        newest, current_recipe_version="v1", current_code_registry_version="v1"
    )
    runner = _Runner(calls=[])
    orchestrator, _ = _orchestrator(compatible_store, runner)
    recovered = asyncio.run(orchestrator.recover("task-1"))
    assert recovered is not None and recovered == winner


# ---------------------------------------------------------------------------
# Candidate property 2 (ensemble boundary): checkpoint at different prefixes
# + suffix execution equals the full run
# ---------------------------------------------------------------------------


def test_crash_before_any_checkpoint_resume_equals_fresh_run() -> None:
    winner, base_calls, base_store = _fresh_baseline()

    empty_store: InMemoryCheckpointStore = InMemoryCheckpointStore()
    runner = _Runner(calls=[])
    orchestrator, _ = _orchestrator(empty_store, runner)
    resumed = asyncio.run(orchestrator.execute(_task()))

    assert resumed == winner
    assert runner.calls == base_calls
    assert replay(_load_sync(empty_store)) == replay(_load_sync(base_store))


def test_crash_after_fanout_resume_reruns_and_lands_on_fresh_run() -> None:
    winner, base_calls, base_store = _fresh_baseline()

    crashed: InMemoryCheckpointStore = InMemoryCheckpointStore()
    # Exactly what a process crashed right after fan-out leaves: the
    # task-level planned marker and nothing else.
    _seed_sync(crashed, _planned_marker(0))
    runner = _Runner(calls=[])
    orchestrator, events = _orchestrator(crashed, runner)
    resumed = asyncio.run(orchestrator.execute(_task()))

    # The waves re-ran (the crash lost their work) and the canonical outcome
    # equals the full replay's: per-wave results deterministic, comparator
    # deterministic.
    assert resumed == winner
    assert runner.calls == base_calls
    resumed_events = [entry for entry in events if entry[0] == EVENT_RECOVERY_RESUMED]
    assert resumed_events and resumed_events[0][1]["complete"] is False

    # The final fold over the segmented history (checkpoint + suffix) equals
    # the full-history fold: re-running did not duplicate canonical wave
    # state, and task-level markers carry no per-wave record (#624).
    empty_state = ResumeState(
        open_tool_calls=frozenset(),
        wave_status={},
        cumulative_spend=0.0,
        pending_approval_gates=frozenset(),
    )
    assert replay(_load_sync(crashed)) == empty_state
    assert replay(_load_sync(base_store)) == empty_state

    # The suffix run's completion is DURABLE, not just returned: the history
    # now carries the waves_complete marker, so a fresh orchestrator over the
    # same store recovers the winner with zero wave re-execution. Without
    # this, a resume that stopped writing its completion checkpoint entirely
    # would still pass — the next restart would silently re-run every wave.
    assert any(c.payload.get("state") == STATE_WAVES_COMPLETE for c in _load_sync(crashed))
    fresh_runner = _Runner(calls=[])
    fresh, fresh_events = _orchestrator(crashed, fresh_runner)
    assert asyncio.run(fresh.recover("task-1")) == winner
    assert fresh_runner.calls == []
    fresh_resumed = [entry for entry in fresh_events if entry[0] == EVENT_RECOVERY_RESUMED]
    assert fresh_resumed and fresh_resumed[0][1]["complete"] is True


def test_crash_after_completion_replays_without_rerun() -> None:
    winner, _, _ = _fresh_baseline()

    crashed: InMemoryCheckpointStore = InMemoryCheckpointStore()
    _seed_sync(crashed, _planned_marker(0), _completed_marker(1))
    runner = _Runner(calls=[])
    orchestrator, events = _orchestrator(crashed, runner)

    # Recovery alone replays the checkpoint to the canonical final state
    # without re-executing anything.
    recovered = asyncio.run(orchestrator.recover("task-1"))
    assert recovered == winner
    assert runner.calls == []

    # And execute() over the same store short-circuits the same way.
    assert asyncio.run(orchestrator.execute(_task())) == winner
    assert runner.calls == []
    resumed = [entry for entry in events if entry[0] == EVENT_RECOVERY_RESUMED]
    assert len(resumed) == 2
    assert all(entry[1]["complete"] is True for entry in resumed)


def test_repeated_recovery_is_deterministic_until_crash_loop() -> None:
    """MEASURED seam constraint: recovery's tally counts `RECOVERY_ATTEMPTED`
    rows without distinguishing a completed recovery from an interrupted one
    (the row is appended before the history is searched for completion), so
    repeated recovery of a task is not idempotent even when every recovery
    SUCCEEDS — the fourth call opens the durable breaker and the completed
    result becomes unreachable through `recover`. This is the issue's
    repeated-replay case failing at the ensemble boundary, not a crash loop:
    the breaker cannot tell them apart. Latent at this head — nothing in
    production calls `recover` yet, so no real workload can trip it — but
    recorded rather than locked in as expected behavior: if a caller ever
    lands, the tally must distinguish completed from interrupted recovery
    (routed to the ensemble owner). What IS pinned as sound: the breaker's
    decision is durable-history-derived and replay-stable — two orchestrators
    reading the same history reach the same verdict, identically, forever."""
    winner, _, _ = _fresh_baseline()

    store: InMemoryCheckpointStore = InMemoryCheckpointStore()
    _seed_sync(store, _completed_marker(0))
    runner = _Runner(calls=[])
    orchestrator, _ = _orchestrator(store, runner)

    # Recoveries 1-3 see 0, 1, 2 recorded attempts — inside the threshold.
    seen: list[WaveResult] = []
    for _ in range(3):
        recovered = asyncio.run(orchestrator.recover("task-1"))
        assert recovered is not None
        seen.append(recovered)
    assert seen == [winner, winner, winner]
    assert runner.calls == []  # never re-executed

    # The tally grew on every one of those SUCCESSFUL recoveries — that is
    # the constraint: reads are not free, each one records a "crash".
    assert sum(1 for c in _load_sync(store) if c.kind is CheckpointKind.RECOVERY_ATTEMPTED) == 3
    # ...and the task actually completed: the quarantine below fires over a
    # history that holds the waves_complete marker, which the tally ignores.
    assert any(c.payload.get("state") == STATE_WAVES_COMPLETE for c in _load_sync(store))

    # Recovery 4 opens the breaker: quarantined — and a second orchestrator
    # replaying the same store reaches the same verdict.
    second_runner = _Runner(calls=[])
    second, second_events = _orchestrator(store, second_runner)
    with pytest.raises(WaveRecoveryQuarantined):
        asyncio.run(orchestrator.recover("task-1"))
    with pytest.raises(WaveRecoveryQuarantined):
        asyncio.run(second.recover("task-1"))
    assert second_runner.calls == []
    quarantined = [entry for entry in second_events if entry[0] == EVENT_RECOVERY_QUARANTINED]
    assert quarantined and "3 time(s)" in quarantined[0][1]["reason"]


def test_history_without_completion_stays_unrecovered() -> None:
    """A history that never reached waves_complete must not yield a result:
    replay reconstructs what was left open, and the caller re-runs."""
    store: InMemoryCheckpointStore = InMemoryCheckpointStore()
    _seed_sync(store, _planned_marker(0))
    runner = _Runner(calls=[])
    orchestrator, _ = _orchestrator(store, runner)
    assert asyncio.run(orchestrator.recover("task-1")) is None
    assert runner.calls == []


# ---------------------------------------------------------------------------
# Candidate property 3 (event-loop half): duplicate delivery, restart halfway,
# repeated replay — canonical effects counted once
# ---------------------------------------------------------------------------


class _RecordingCaller:
    """Records (trigger_id, event_id) deliveries; fails on command."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        # Attempts that returned without raising: the committed effect.
        self.committed: list[tuple[str, int]] = []
        self.fail_times: dict[tuple[str, int], int] = {}

    async def __call__(self, trigger: TriggerDefinition, event: LoggedEvent) -> None:
        key = (trigger.trigger_id, event.id)
        self.calls.append(key)
        remaining = self.fail_times.get(key, 0)
        if remaining > 0:
            self.fail_times[key] = remaining - 1
            raise HandlerCallError("transient failure for research fixture")
        self.committed.append(key)


_EVENT_TYPES = [
    "task.created",
    "task.failed",
    "task.created",
    "task.failed",
    "task.created",
    "task.failed",
]


@dataclass
class _EventStack:
    log: InMemoryEventLog
    triggers: InMemoryTriggerStore
    invocations: InMemoryInvocationStore
    trigger: TriggerDefinition


def _fresh_event_stack() -> _EventStack:
    stack = _EventStack(
        log=InMemoryEventLog(),
        triggers=InMemoryTriggerStore(),
        invocations=InMemoryInvocationStore(),
        trigger=TriggerDefinition(name="tasks", event_pattern="task.*"),
    )
    return stack


async def _populate(stack: _EventStack) -> None:
    await stack.triggers.add(stack.trigger)
    for event_type in _EVENT_TYPES:
        await stack.log.append(event_type)


def _run_baseline() -> tuple[_RecordingCaller, int]:
    stack = _fresh_event_stack()
    asyncio.run(_populate(stack))
    caller = _RecordingCaller()
    cursor = asyncio.run(process_events(stack.log, stack.triggers, stack.invocations, caller))
    return caller, cursor


def test_restart_halfway_replay_equals_no_crash_baseline() -> None:
    baseline_caller, baseline_cursor = _run_baseline()
    # Canonical effects compared by event id: trigger ids are store-local
    # identity, minted per stack; the effect is the delivery itself.
    baseline_effects = sorted(eid for _, eid in baseline_caller.calls)
    assert len(baseline_effects) == len(_EVENT_TYPES)

    # The same history, but the handler dies once mid-batch: the process
    # "crashes" with that invocation RETRYING and the cursor held.
    stack = _fresh_event_stack()
    asyncio.run(_populate(stack))
    crash_caller = _RecordingCaller()
    crash_caller.fail_times[(stack.trigger.trigger_id, 3)] = 1
    crash_cursor = asyncio.run(
        process_events(stack.log, stack.triggers, stack.invocations, crash_caller)
    )
    assert crash_cursor == 2  # the unsettled event held the cursor
    assert crash_cursor < baseline_cursor

    # Restart: fresh process state, durable log + invocation rows kept, cursor
    # rebuilt from zero (the documented-safe restart). Canonical effects must
    # converge to the baseline exactly: every event delivered once IN TOTAL —
    # the crash tick's own successes (1, 2) plus the suffix (3..6) — with the
    # invocation rows proving exactly one successful application each.
    recovery_caller = _RecordingCaller()
    final_cursor = asyncio.run(
        process_events(stack.log, stack.triggers, stack.invocations, recovery_caller)
    )
    # Compare committed deliveries, not attempts: event 3's failed try sits in
    # `calls` but is not an effect, and committed ids must equal the baseline
    # without any dedup — the crash tick's successes (1, 2) plus the suffix
    # (3..6), each delivered exactly once.
    committed = sorted(eid for _, eid in crash_caller.committed + recovery_caller.committed)
    assert committed == baseline_effects
    assert final_cursor == baseline_cursor
    assert baseline_effects == sorted(set(baseline_effects))
    trigger_id = stack.trigger.trigger_id
    successes = 0
    for event_id in baseline_effects:
        invocation = asyncio.run(stack.invocations.get(trigger_id, event_id))
        assert invocation is not None and invocation.status is InvocationStatus.SUCCESS
        successes += 1
        expected_attempts = 2 if event_id == 3 else 1
        assert invocation.attempts == expected_attempts
    assert successes == len(_EVENT_TYPES)


def test_repeated_replay_from_zero_appends_no_effects() -> None:
    stack = _fresh_event_stack()
    asyncio.run(_populate(stack))
    caller = _RecordingCaller()
    cursor = asyncio.run(process_events(stack.log, stack.triggers, stack.invocations, caller))
    delivered = list(caller.calls)
    event_count = len(asyncio.run(stack.log.query(after_id=0, limit=1000)))

    for _ in range(3):
        assert (
            asyncio.run(
                process_events(stack.log, stack.triggers, stack.invocations, caller, after_id=0)
            )
            == cursor
        )
    assert caller.calls == delivered  # still exactly one delivery each
    assert len(asyncio.run(stack.log.query(after_id=0, limit=1000))) == event_count


def test_concurrent_duplicate_delivery_delivers_once() -> None:
    """Two workers replaying the same log concurrently: the claim dedupes, so
    the canonical effect (a successful handler delivery) happens once, even
    though the losing worker holds its cursor back."""
    stack = _fresh_event_stack()
    asyncio.run(_populate(stack))
    caller = _RecordingCaller()

    async def two_workers() -> tuple[int, int]:
        return await asyncio.gather(
            process_events(stack.log, stack.triggers, stack.invocations, caller),
            process_events(stack.log, stack.triggers, stack.invocations, caller),
        )

    asyncio.run(two_workers())
    assert sorted(caller.calls) == sorted(set(caller.calls))
    assert len(caller.calls) == len(_EVENT_TYPES)
    for key in caller.calls:
        invocation = asyncio.run(stack.invocations.get(*key))
        assert invocation is not None and invocation.status is InvocationStatus.SUCCESS


def test_permanent_failure_replay_appends_handler_failed_exactly_once() -> None:
    stack = _fresh_event_stack()
    asyncio.run(_populate(stack))
    caller = _RecordingCaller()
    caller.fail_times[(stack.trigger.trigger_id, 2)] = 10**6  # never succeeds

    async def scenario() -> None:
        await process_events(stack.log, stack.triggers, stack.invocations, caller, limit=3)
        # Repeated replays of the same history: the terminal invocation is
        # never re-claimed, so no further delivery and no duplicate
        # handler.failed fact.
        for _ in range(3):
            await process_events(stack.log, stack.triggers, stack.invocations, caller, limit=3)

    asyncio.run(scenario())
    failed = asyncio.run(stack.invocations.get(stack.trigger.trigger_id, 2))
    assert failed is not None and failed.status is InvocationStatus.FAILED
    assert failed.attempts == 3  # MAX_ATTEMPTS, never grown by replays
    handler_failed = [
        event
        for event in asyncio.run(stack.log.query(after_id=0, limit=1000))
        if event.event_type == HANDLER_FAILED_EVENT
    ]
    assert len(handler_failed) == 1


def test_cursor_respects_settled_prefix_and_suffix_replay_completes() -> None:
    """checkpoint(durable cursor) + suffix replay == full replay for the event
    loop: resuming from the cursor delivers exactly the unsettled suffix."""
    baseline_caller, baseline_cursor = _run_baseline()

    stack = _fresh_event_stack()
    asyncio.run(_populate(stack))
    caller = _RecordingCaller()
    caller.fail_times[(stack.trigger.trigger_id, 3)] = 1

    async def scenario() -> tuple[int, list[tuple[str, int]]]:
        batch = await process_events_batch(stack.log, stack.triggers, stack.invocations, caller)
        assert batch.holes == ()  # in-memory ids are contiguous
        suffix_caller = _RecordingCaller()
        cursor = await process_events(
            stack.log, stack.triggers, stack.invocations, suffix_caller, after_id=batch.cursor
        )
        return cursor, suffix_caller.committed

    final_cursor, suffix_deliveries = asyncio.run(scenario())
    assert final_cursor == baseline_cursor
    # Committed deliveries across the crashed tick and the suffix replay equal
    # the baseline exactly, no dedup: event 3's failed first try sits in
    # `caller.calls` but committed only once, in the suffix. The invocation
    # rows prove one successful application per event.
    committed = sorted(eid for _, eid in caller.committed + suffix_deliveries)
    assert committed == sorted(eid for _, eid in baseline_caller.committed)
    for event_id in sorted(eid for _, eid in baseline_caller.committed):
        invocation = asyncio.run(stack.invocations.get(stack.trigger.trigger_id, event_id))
        assert invocation is not None and invocation.status is InvocationStatus.SUCCESS


# ---------------------------------------------------------------------------
# Recovery-event identity (#462/#61): replay cannot mint a second fact
# ---------------------------------------------------------------------------


class _FixedRunLookup:
    def __init__(self, run: Run | None) -> None:
        self._run = run

    async def get_run(self, run_id: str) -> Run | None:
        return self._run


class _RecordingSink:
    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    async def emit(self, envelope: Any) -> None:
        self.envelopes.append(envelope)


def _research_run() -> Run:
    graph = Graph(
        graph_id="graph-1",
        workspace_id="workspace-1",
        project_id="project-1",
        name="one node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return Run(
        run_id="run-1",
        workspace_id="workspace-1",
        project_id="project-1",
        graph=GraphSnapshot.from_graph(graph),
        created_at=_t(0),
        updated_at=_t(0),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )


def _recovery_fact(*, status: AttemptStatus = AttemptStatus.CANCELLED) -> RecoveryDispositionEvent:
    attempt = Attempt(
        node_run_id="nr-1",
        ordinal=1,
        status=status,
        finished_at=_t(1) if status in TERMINAL_ATTEMPT_STATUSES else None,
    )
    return RecoveryDispositionEvent(
        run_id="run-1",
        node_run_id="nr-1",
        attempt_id="at-1",
        attempt_status=status.value,
        node_run_status=RunStatus.WAITING.value,
        cancellation_cause=CancellationCause.RECOVERED.value,
        disposition=disposition_of(attempt, CancellationCause.RECOVERED),
        error="lease expired",
        source="research",
    )


def test_recovery_event_identity_stable_under_replay() -> None:
    run = _research_run()
    sink = _RecordingSink()
    adapter = CanonicalRecoveryEventSink(runs=_FixedRunLookup(run), events=sink)

    async def emit_twice() -> None:
        await adapter.emit(_recovery_fact())
        await adapter.emit(_recovery_fact())

    asyncio.run(emit_twice())
    first, second = sink.envelopes
    assert first.event_id == second.event_id  # one canonical identity per fact
    assert first.type == RECOVERY_EVENT_TYPE
    assert first.payload == second.payload
    assert first.workspace_id == run.workspace_id

    # A different disposition is a different fact and mints a different id.
    other_sink = _RecordingSink()
    other = CanonicalRecoveryEventSink(runs=_FixedRunLookup(run), events=other_sink)
    asyncio.run(other.emit(_recovery_fact(status=AttemptStatus.FAILED)))
    assert other_sink.envelopes[0].event_id != first.event_id


def test_disposition_table_is_total_over_attempt_statuses() -> None:
    for status in AttemptStatus:
        attempt = Attempt(
            node_run_id="nr-1",
            ordinal=1,
            status=status,
            finished_at=_t(1) if status in TERMINAL_ATTEMPT_STATUSES else None,
        )
        if status is AttemptStatus.COMPLETED:
            assert disposition_of(attempt, CancellationCause.RECOVERED) == "accepted"
        elif status is AttemptStatus.CANCELLED:
            assert disposition_of(attempt, CancellationCause.REQUESTED) == "terminalized"
            assert disposition_of(attempt, CancellationCause.RECOVERED) == "recovered_and_parked"
        else:
            assert disposition_of(attempt, CancellationCause.REQUESTED) == "parked"


def test_recovery_event_unknown_run_refused() -> None:
    adapter = CanonicalRecoveryEventSink(runs=_FixedRunLookup(None), events=_RecordingSink())
    with pytest.raises(ValueError, match="unknown Run"):
        asyncio.run(adapter.emit(_recovery_fact()))


# ---------------------------------------------------------------------------
# Candidate property 4: terminal state never regresses after replay
# ---------------------------------------------------------------------------


def test_transition_tables_absorb_terminal_statuses() -> None:
    for status in TERMINAL_RUN_STATUSES:
        assert RUN_TRANSITIONS[status] == frozenset()
        with pytest.raises(ValueError, match="no legal transition path"):
            transition_path(status, RunStatus.RUNNING)
    for status in TERMINAL_ATTEMPT_STATUSES:
        assert ATTEMPT_TRANSITIONS[status] == frozenset()
    # The reconciler's escape hatch: every open status can still reach
    # CANCELLED, so replay/reconciliation can always close what a crash left.
    for status in RunStatus:
        if status not in TERMINAL_RUN_STATUSES:
            assert transition_path(status, RunStatus.CANCELLED)[-1] is RunStatus.CANCELLED
    for status in AttemptStatus:
        if status not in TERMINAL_ATTEMPT_STATUSES:
            assert AttemptStatus.CANCELLED in ATTEMPT_TRANSITIONS[status]


def test_terminal_attempt_refuses_every_revival() -> None:
    for terminal in sorted(TERMINAL_ATTEMPT_STATUSES, key=lambda s: s.value):
        attempt = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
        running = transition_attempt(attempt, AttemptStatus.RUNNING, at=_t(1))
        settled = transition_attempt(running, terminal, at=_t(2))
        assert settled.finished_at == _t(2)
        for revival in AttemptStatus:
            with pytest.raises(InvalidLifecycleTransition):
                transition_attempt(settled, revival, at=_t(3))
        # Recovery sweeps cannot touch it either.
        with pytest.raises(InvalidLifecycleTransition):
            reclaim_attempt(settled, at=_t(3))
        assert lease_is_expired(settled, now=_t(100)) is False


def test_terminal_run_refuses_completion_of_new_attempts() -> None:
    for terminal in sorted(TERMINAL_RUN_STATUSES, key=lambda s: s.value):
        with pytest.raises(InvalidLifecycleTransition):
            refuse_completion_under_terminal_run(terminal, "attempt-1")


def test_run_transition_out_of_terminal_is_impossible() -> None:
    run = _research_run()
    completed = transition_run(run, RunStatus.QUEUED, at=_t(1))
    completed = transition_run(completed, RunStatus.RUNNING, at=_t(2))
    completed = transition_run(completed, RunStatus.COMPLETED, at=_t(3), result={"ok": True})
    for revival in RunStatus:
        with pytest.raises(InvalidLifecycleTransition):
            transition_run(completed, revival, at=_t(4))


# ---------------------------------------------------------------------------
# Candidate property 2 (lifecycle half): midpoint checkpoint + suffix log
# equals full-log replay
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleStep:
    """One recorded durable transition; ``apply`` is a pure record -> record."""

    label: str
    apply: Callable[[Any], Any]


def _lease_for(record: Attempt) -> ExecutionLease:
    return ExecutionLease(
        node_run_id="nr-1",
        attempt_id=record.attempt_id,
        lease_epoch=1,
        holder="research-worker",
        fencing_token="fence-1",
        issued_at=_t(0),
        expires_at=_t(600),
    )


def _reclaim_after_lease_expiry(record: Attempt, at: datetime) -> Attempt:
    """Reclaim through the production gate: expiry first, then the sweep."""
    assert lease_is_expired(record, now=at), "reclaim must follow an expired lease"
    return reclaim_attempt(record, at=at)


def _walk_attempt_steps(rng: random.Random) -> list[LifecycleStep]:
    steps: list[LifecycleStep] = [
        LifecycleStep(
            "lease-attached",
            lambda record: record.model_copy(update={"execution_lease": _lease_for(record)}),
        )
    ]
    clock = 0
    current = AttemptStatus.CREATED
    while current not in TERMINAL_ATTEMPT_STATUSES and len(steps) < 8:
        targets = sorted(ATTEMPT_TRANSITIONS[current], key=lambda s: s.value)
        target = rng.choice(targets)
        clock += 1
        if current is AttemptStatus.RUNNING and rng.random() < 0.4:
            moment = _t(clock)
            steps.append(
                LifecycleStep(
                    "lease-renewed",
                    lambda record, at=moment: renew_attempt_lease(
                        record, fencing_token="fence-1", ttl=timedelta(seconds=600), at=at
                    ),
                )
            )
        if (
            target is AttemptStatus.CANCELLED
            and current is AttemptStatus.RUNNING
            and rng.random() < 0.5
        ):
            # Production sweeps reclaim only after lease_is_expired, so the
            # reclaim lands past the lease TTL (renewals extend expiry by at
            # most one 600s window from a tick <= this one) and the expiry
            # predicate is asserted before the step applies.
            moment = _t(600 + clock)
            steps.append(
                LifecycleStep(
                    "reclaimed",
                    lambda record, at=moment: _reclaim_after_lease_expiry(record, at),
                )
            )
            current = target
            continue
        error = (
            f"{target.value} during research walk"
            if target in {AttemptStatus.FAILED, AttemptStatus.TIMED_OUT}
            else None
        )
        moment = _t(clock)
        steps.append(
            LifecycleStep(
                f"->{target.value}",
                lambda record, t=target, at=moment, err=error: transition_attempt(
                    record, t, at=at, error=err
                ),
            )
        )
        current = target
    return steps


def _walk_run_steps(rng: random.Random) -> list[LifecycleStep]:
    steps: list[LifecycleStep] = []
    clock = 0
    current = RunStatus.CREATED
    while current not in TERMINAL_RUN_STATUSES and len(steps) < 8:
        targets = sorted(RUN_TRANSITIONS[current], key=lambda s: s.value)
        target = rng.choice(targets)
        clock += 1
        result = {"ok": True} if target is RunStatus.COMPLETED else None
        error = (
            f"{target.value} during research walk"
            if target in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}
            else None
        )
        moment = _t(clock)
        steps.append(
            LifecycleStep(
                f"->{target.value}",
                lambda record, t=target, at=moment, res=result, err=error: transition_run(
                    record, t, at=at, result=res, error=err
                ),
            )
        )
        current = target
    return steps


def _accepted_outcome_for(
    node_run: NodeRun, logical: RunStatus, at: datetime
) -> AcceptedNodeOutcome:
    result: dict[str, Any] = {"node": node_run.node_id, "seq": node_run.ordinal}
    attempt_result = AttemptResult(
        attempt_id=f"at-{node_run.node_id}-{node_run.ordinal}",
        node_run_id=node_run.node_run_id,
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        result=result,
        finished_at=at,
    )
    return AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=attempt_result,
        logical_status=logical,
        result=result,
        accepted_at=at,
    )


def _walk_node_run_steps(rng: random.Random, node_id: str) -> list[LifecycleStep]:
    steps: list[LifecycleStep] = []
    clock = 0
    current = RunStatus.CREATED
    while current not in TERMINAL_RUN_STATUSES and len(steps) < 8:
        targets = sorted(RUN_TRANSITIONS[current], key=lambda s: s.value)
        # MEASURED seam constraint: a WAITING record carrying an accepted
        # outcome cannot legally become PAUSED (the carried outcome's
        # logical_status no longer matches). Excluded here so the walk stays
        # on producible histories; pinned by the finding test below.
        has_accept_step = any(step.label.startswith("accept:") for step in steps)
        if has_accept_step and current is RunStatus.WAITING:
            targets = [t for t in targets if t is not RunStatus.PAUSED]
        target = rng.choice(targets)
        clock += 1
        if target in {RunStatus.COMPLETED, RunStatus.WAITING, RunStatus.PAUSED}:
            moment = _t(clock)

            def apply_accept(record: Any, t: RunStatus = target, at: datetime = moment) -> Any:
                outcome = _accepted_outcome_for(record, t, at)
                return transition_node_run(
                    record, t, at=at, result=outcome.result, accepted_outcome=outcome
                )

            steps.append(LifecycleStep(f"accept:{target.value}", apply_accept))
        else:
            error = (
                f"{target.value} during research walk"
                if target in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}
                else None
            )
            moment = _t(clock)
            steps.append(
                LifecycleStep(
                    f"->{target.value}",
                    lambda record, t=target, at=moment, err=error: transition_node_run(
                        record, t, at=at, error=err
                    ),
                )
            )
        current = target
    return steps


def _replay_equivalence(steps: list[LifecycleStep], seed_record: Any, split: int) -> None:
    """Full-log replay vs midpoint-checkpoint + suffix-log replay."""
    full = seed_record
    for step in steps:
        full = step.apply(full)
    checkpoint = seed_record
    for step in steps[:split]:
        checkpoint = step.apply(checkpoint)
    resumed = checkpoint
    for step in steps[split:]:
        resumed = step.apply(resumed)
    # The midpoint row carries its own durable timestamps; the suffix replay
    # must reconstruct identical observable state, bookkeeping included.
    assert resumed.model_dump() == full.model_dump()
    # And replaying from the checkpoint twice changes nothing.
    again = checkpoint
    for step in steps[split:]:
        again = step.apply(again)
    assert again.model_dump() == full.model_dump()


def test_midpoint_checkpoint_replay_equals_full_log_for_attempts() -> None:
    rng = random.Random(SEED + 2)
    for _ in range(8):
        steps = _walk_attempt_steps(rng)
        assert steps
        split = rng.randint(0, len(steps))
        seed = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
        _replay_equivalence(steps, seed, split)


def test_midpoint_checkpoint_replay_equals_full_log_for_runs() -> None:
    rng = random.Random(SEED + 3)
    for _ in range(8):
        steps = _walk_run_steps(rng)
        assert steps
        split = rng.randint(0, len(steps))
        _replay_equivalence(steps, _research_run(), split)


def test_midpoint_checkpoint_replay_equals_full_log_for_node_runs() -> None:
    rng = random.Random(SEED + 4)
    for i in range(8):
        node_id = f"node-{i}"
        steps = _walk_node_run_steps(rng, node_id)
        assert steps
        split = rng.randint(0, len(steps))
        seed = NodeRun(run_id="run-1", node_id=node_id, ordinal=1, created_at=_t(0))
        _replay_equivalence(steps, seed, split)


# ---------------------------------------------------------------------------
# Candidate property 5: equivalent durable histories -> equivalent state
# (within the ordering contracts), plus the measured seam findings
# ---------------------------------------------------------------------------


def test_waiting_record_with_accepted_outcome_cannot_pause_recorded() -> None:
    """MEASURED seam contract: the run table admits WAITING→PAUSED, but the
    record validator refuses the carried WAITING outcome on a PAUSED record —
    the replay state space is (status, has-accepted-outcome), not status
    alone. Not reachable from production writers at this head (the reconciler
    pause path short-circuits WAITING records), but any replay harness that
    samples transitions naively generates histories no store can hold. Pinned
    so the constraint is measured once, not rediscovered per harness."""
    node_run = NodeRun(run_id="run-1", node_id="node-1", ordinal=1, created_at=_t(0))
    node_run = transition_node_run(node_run, RunStatus.QUEUED, at=_t(1))
    node_run = transition_node_run(node_run, RunStatus.RUNNING, at=_t(2))
    outcome = _accepted_outcome_for(node_run, RunStatus.WAITING, _t(3))
    node_run = transition_node_run(
        node_run, RunStatus.WAITING, at=_t(3), result=outcome.result, accepted_outcome=outcome
    )
    assert node_run.accepted_outcome is not None
    with pytest.raises(ValidationError, match="accepted logical outcome"):
        transition_node_run(node_run, RunStatus.PAUSED, at=_t(4))


def _node_history(node_id: str, final: RunStatus, *, ordinal: int = 1) -> list[NodeRun]:
    record = NodeRun(run_id="run-1", node_id=node_id, ordinal=ordinal, created_at=_t(0))
    records = [record]
    steps = [RunStatus.QUEUED, RunStatus.RUNNING, final]
    for i, target in enumerate(steps, start=1):
        if target is RunStatus.COMPLETED:
            outcome = _accepted_outcome_for(record, target, _t(i))
            record = transition_node_run(
                record, target, at=_t(i), result=outcome.result, accepted_outcome=outcome
            )
        else:
            error = (
                f"{target.value} during research walk" if target in TERMINAL_RUN_STATUSES else None
            )
            record = transition_node_run(record, target, at=_t(i), error=error)
        records.append(record)
    return records


def test_node_run_projection_is_order_independent() -> None:
    """One final record per node identity: `latest_node_runs` picks the newest
    ordinal per node, so distinct identities project identically under any
    delivery order — and a re-execution (next Run ordinal) wins over the older
    record for the same node under every ordering too. Ordinals here are store
    -valid: canonical writers allocate them GLOBALLY within one Run
    (`MAX(ordinal)+1` under the Run row lock, backstopped by
    `UNIQUE (run_id, ordinal)`), so coexisting NodeRuns never share one."""
    # Store-valid global ordinals: a=1, b=2, c=3 under run-1.
    done = _node_history("a", RunStatus.COMPLETED, ordinal=1)[-1]
    failed = _node_history("b", RunStatus.FAILED, ordinal=2)[-1]
    running = NodeRun(run_id="run-1", node_id="c", ordinal=3, created_at=_t(0))

    mixed = [done, failed, running]
    reference = latest_node_runs(list(mixed))
    rng = random.Random(SEED + 5)
    for _ in range(6):
        shuffled = list(mixed)
        rng.shuffle(shuffled)
        projected = latest_node_runs(shuffled)
        assert {k: v.model_dump() for k, v in projected.items()} == {
            k: v.model_dump() for k, v in reference.items()
        }
        # The completion verdict reads the same projection either way, and
        # fails for the named reason: b's newest record is terminal-not-
        # completed, which is exactly what the fence refuses.
        with pytest.raises(UnearnedRunCompletion, match="node 'b'"):
            check_completion_is_earned(RunStatus.COMPLETED, shuffled)

    # A re-execution records a NEW NodeRun for the failed node with the Run's
    # next global ordinal (4); the newest ordinal is the one that counts, so
    # completion is now earned under every ordering of the longer history.
    # (The version chain collapses to its final record first — several rows
    # per identity+ordinal would be the degenerate case the tie test below
    # pins.)
    retried = [_node_history("b", RunStatus.COMPLETED, ordinal=4)[-1]]
    repaired = [done, failed, running, *retried]
    rng2 = random.Random(SEED + 6)
    for _ in range(3):
        shuffled = list(repaired)
        rng2.shuffle(shuffled)
        latest = latest_node_runs(shuffled)
        assert latest["b"].ordinal == 4
        check_completion_is_earned(RunStatus.COMPLETED, shuffled)  # must not raise


def test_equal_ordinal_projection_tie_keeps_input_order_recorded() -> None:
    """MEASURED degenerate case: two records claiming the same node AND the
    same ordinal violate the store contract (one row per identity+ordinal);
    if a store leaks both anyway, the projection keeps whichever came first,
    so reconstruction becomes order-dependent. Replay harnesses must dedupe
    by identity+ordinal before projecting — recorded so the boundary of the
    equivalence property ("where ordering contracts permit") is exact."""
    first = _node_history("a", RunStatus.COMPLETED)[-1]
    second = _node_history("a", RunStatus.FAILED)[-1]
    assert latest_node_runs([first, second])["a"].status is RunStatus.COMPLETED
    assert latest_node_runs([second, first])["a"].status is RunStatus.FAILED


def test_equivalent_interleavings_reconstruct_equivalent_state() -> None:
    """Ordering contract: per-identity sequence fixed, cross-identity order
    free. Two interleavings of the same per-node durable histories must
    reconstruct equivalent observable state and the same completion verdict."""

    def a_steps() -> list[LifecycleStep]:
        return [
            LifecycleStep("q", lambda r: transition_node_run(r, RunStatus.QUEUED, at=_t(1))),
            LifecycleStep("r", lambda r: transition_node_run(r, RunStatus.RUNNING, at=_t(2))),
            LifecycleStep(
                "c",
                lambda r: transition_node_run(
                    r,
                    RunStatus.COMPLETED,
                    at=_t(3),
                    result={"node": "a", "seq": 1},
                    accepted_outcome=_accepted_outcome_for(r, RunStatus.COMPLETED, _t(3)),
                ),
            ),
        ]

    def b_steps() -> list[LifecycleStep]:
        return [
            LifecycleStep("q", lambda r: transition_node_run(r, RunStatus.QUEUED, at=_t(10))),
            LifecycleStep("r", lambda r: transition_node_run(r, RunStatus.RUNNING, at=_t(11))),
            LifecycleStep(
                "f",
                lambda r: transition_node_run(
                    r, RunStatus.FAILED, at=_t(12), error="failed during research walk"
                ),
            ),
        ]

    def build(node_id: str, ordinal: int, steps: list[LifecycleStep]) -> NodeRun:
        # Identity pinned per node so two independent replays of the same
        # history are comparable field-for-field. Ordinals are store-valid:
        # global per Run (UNIQUE (run_id, ordinal)), so a=1 and b=2.
        record = NodeRun(
            node_run_id=f"nr-{node_id}",
            run_id="run-1",
            node_id=node_id,
            ordinal=ordinal,
            created_at=_t(0),
        )
        for step in steps:
            record = step.apply(record)
        return record

    interleave_1 = [build("a", 1, a_steps()), build("b", 2, b_steps())]
    interleave_2 = [build("b", 2, b_steps()), build("a", 1, a_steps())]

    projection_1 = {k: v.model_dump() for k, v in latest_node_runs(interleave_1).items()}
    projection_2 = {k: v.model_dump() for k, v in latest_node_runs(interleave_2).items()}
    assert projection_1 == projection_2
    for records in (interleave_1, interleave_2):
        with pytest.raises(UnearnedRunCompletion, match="node 'b'"):
            check_completion_is_earned(RunStatus.COMPLETED, records)


def _open_node_run_at(target: RunStatus) -> NodeRun:
    """A non-terminal NodeRun walked to ``target`` through legal moves."""
    record = NodeRun(run_id="run-1", node_id="n", ordinal=1, created_at=_t(0))
    if target is RunStatus.CREATED:
        return record
    record = transition_node_run(record, RunStatus.QUEUED, at=_t(1))
    if target is RunStatus.QUEUED:
        return record
    record = transition_node_run(record, RunStatus.RUNNING, at=_t(2))
    if target is RunStatus.RUNNING:
        return record
    if target is RunStatus.WAITING:
        return transition_node_run(record, RunStatus.WAITING, at=_t(3), error="parked")
    if target is RunStatus.PAUSED:
        return transition_node_run(record, RunStatus.PAUSED, at=_t(3), error="awaiting human")
    raise AssertionError(f"unexpected open target {target}")


def test_open_node_run_cascade_is_deterministic_and_not_idempotent() -> None:
    """The cascade is a one-way durable transition, not a set difference:
    settling an already-settled record raises, so cascade loops must guard on
    the store's read. PAUSED is INCLUDED because the canonical stores cascade
    *every* non-terminal NodeRun when the Run terminalizes — the Run-locked
    sweep selects open rows regardless of status. A human wait's protection
    lives one level up, in `check_completion_is_earned` (COMPLETED is refused
    over a pause); it is not a cascade exemption."""
    for status in (
        RunStatus.CREATED,
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.WAITING,
        RunStatus.PAUSED,
    ):
        settled = settle_open_node_run(_open_node_run_at(status), RunStatus.FAILED, at=_t(9))
        assert settled.status is RunStatus.CANCELLED
        assert settled.error == "cancelled because its Run terminalized as failed"
        with pytest.raises(InvalidLifecycleTransition):
            settle_open_node_run(settled, RunStatus.FAILED, at=_t(10))

    # A paused node's *accepted outcome* is superseded by the cascade, not
    # carried: the record validator refuses a CANCELLED NodeRun whose
    # acceptance still read paused, so the sweep must clear it — the pause's
    # evidence survives on the Attempt, where it was written. (The carried
    # acceptance shapes the record: result and error must both project it.)
    running = _open_node_run_at(RunStatus.RUNNING)
    acceptance = _accepted_outcome_for(running, RunStatus.PAUSED, _t(3))
    paused = transition_node_run(
        running,
        RunStatus.PAUSED,
        at=_t(3),
        result=acceptance.result,
        accepted_outcome=acceptance,
    )
    assert paused.accepted_outcome is not None
    settled = settle_open_node_run(paused, RunStatus.FAILED, at=_t(9))
    assert settled.status is RunStatus.CANCELLED
    assert settled.accepted_outcome is None


# ---------------------------------------------------------------------------
# Workload measurement: ties the research note's runtime quote to an exact,
# deterministic workload (never to a wall-clock bound).
# ---------------------------------------------------------------------------


def test_measured_workload_shape_is_stable() -> None:
    """The note quotes runtime for THIS workload; the workload size is a
    frozen constant so the quote stays meaningful across machines."""
    rng = random.Random(SEED)
    histories = [_random_checkpoint_history(rng, spend_rows=3) for _ in range(10)]
    fold_replays = 0
    for history in histories:
        for _ in range(6):  # 1 + 5 shuffles, as the order-insensitivity test does
            shuffled = list(history)
            rng.shuffle(shuffled)
            replay(tuple(shuffled))
            fold_replays += 1
    assert len(histories) == 10
    assert fold_replays == 60
    # Informational only: measure (but never assert a bound on) the duration.
    started = time.perf_counter()
    replay(tuple(histories[0]))
    assert time.perf_counter() - started >= 0.0
