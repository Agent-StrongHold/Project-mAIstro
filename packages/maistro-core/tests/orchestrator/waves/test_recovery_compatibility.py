"""Recovery checks the versions the checkpoint recorded (#624).

ADR-056 gave `TaskCheckpoint` a `recipe_version` and a `code_registry_version`,
and gave `maistro.tasks.recovery` a `version_compatible` to compare them and a
`CrashLoopPolicy` to stop a task that keeps crashing. Recovery called neither.
An upgraded deployment resumed results produced by code that no longer existed
and reported them as its own; a task that crashed during recovery was recovered
again on every restart, forever.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.orchestrator.waves.ensemble import (
    EVENT_RECOVERY_QUARANTINED,
    EVENT_RECOVERY_REFUSED,
    EVENT_RECOVERY_RESUMED,
    InMemoryCheckpointStore,
    SuperPlannerConfig,
    Wave,
    WaveOrchestrator,
    WaveRecoveryQuarantined,
    WaveResult,
    WaveTask,
)
from maistro.tasks.checkpoint import CheckpointKind

VERSION_A = SuperPlannerConfig(recipe_version="1", code_registry_version="a")


def _task(task_id: str = "task-1") -> WaveTask:
    return WaveTask(id=task_id, description="solve it", context={})


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def fields(self, name: str) -> dict[str, Any]:
        matches = [f for n, f in self.events if n == name]
        assert matches, f"{name} not emitted; got {[n for n, _ in self.events]}"
        return matches[0]

    def names(self) -> list[str]:
        return [n for n, _ in self.events]


async def _runner(wave: Wave, task: WaveTask) -> WaveResult:
    return WaveResult(
        wave_id=wave.id, task_id=task.id, output="fresh", metadata={"quality_score": 1.0}
    )


async def _completed_under(config: SuperPlannerConfig) -> InMemoryCheckpointStore:
    """A store holding one task's checkpoints, run to completion under `config`."""
    store = InMemoryCheckpointStore()
    await WaveOrchestrator(_runner, checkpoint_store=store, config=config).execute(_task())
    return store


@pytest.mark.ac("SPEC-256/AC-1")
@pytest.mark.ac("SPEC-256/AC-6")
async def test_a_checkpoint_from_another_recipe_version_is_not_resumed() -> None:
    store = await _completed_under(VERSION_A)
    recorder = _Recorder()

    result = await WaveOrchestrator(
        _runner,
        checkpoint_store=store,
        config=SuperPlannerConfig(recipe_version="2", code_registry_version="a"),
        emit=recorder,
    ).execute(_task())

    assert result.output == "fresh"
    fields = recorder.fields(EVENT_RECOVERY_REFUSED)
    assert fields["checkpoint_recipe_version"] == "1"
    assert fields["current_recipe_version"] == "2"


@pytest.mark.ac("SPEC-256/AC-2")
async def test_a_checkpoint_from_another_code_registry_version_is_not_resumed() -> None:
    store = await _completed_under(VERSION_A)
    recorder = _Recorder()

    await WaveOrchestrator(
        _runner,
        checkpoint_store=store,
        config=SuperPlannerConfig(recipe_version="1", code_registry_version="b"),
        emit=recorder,
    ).execute(_task())

    fields = recorder.fields(EVENT_RECOVERY_REFUSED)
    assert fields["checkpoint_code_registry_version"] == "a"
    assert fields["current_code_registry_version"] == "b"


@pytest.mark.ac("SPEC-256/AC-3")
async def test_a_matching_checkpoint_still_recovers() -> None:
    """The other side. A check that refused everything would satisfy both tests
    above while deleting recovery."""
    store = await _completed_under(VERSION_A)
    recorder = _Recorder()

    async def _fail(wave: Wave, task: WaveTask) -> WaveResult:
        raise AssertionError("a recovered task must not re-run its waves")

    result = await WaveOrchestrator(
        _fail, checkpoint_store=store, config=VERSION_A, emit=recorder
    ).execute(_task())

    # `_fail` would have raised had a wave re-run, so reaching a result at all
    # is the claim; the event says recovery, not a fresh execution, produced it.
    assert result.output == "fresh"
    assert recorder.fields(EVENT_RECOVERY_RESUMED)["complete"] is True


@pytest.mark.ac("SPEC-256/AC-4")
@pytest.mark.ac("SPEC-256/AC-6")
async def test_repeated_recovery_quarantines_the_task() -> None:
    store = await _completed_under(VERSION_A)
    config = SuperPlannerConfig(
        recipe_version="1", code_registry_version="a", max_recovery_attempts=2
    )
    recorder = _Recorder()
    orchestrator = WaveOrchestrator(_runner, checkpoint_store=store, config=config, emit=recorder)

    await orchestrator.execute(_task())
    await orchestrator.execute(_task())

    with pytest.raises(WaveRecoveryQuarantined) as raised:
        await orchestrator.execute(_task())

    assert "the limit is 2" in str(raised.value)
    assert EVENT_RECOVERY_QUARANTINED in recorder.names()


@pytest.mark.ac("SPEC-256/AC-4")
async def test_a_task_with_no_checkpoints_is_not_quarantined() -> None:
    """ "Nothing to recover" and "stop recovering this" call for opposite
    actions; a quarantine that fired on an empty store would refuse fresh work.
    """
    result = await WaveOrchestrator(
        _runner, checkpoint_store=InMemoryCheckpointStore(), config=VERSION_A
    ).execute(_task())

    assert result.output == "fresh"


@pytest.mark.ac("SPEC-256/AC-5")
async def test_an_interruption_before_completion_reports_what_was_left_open() -> None:
    """Previously invisible: with no `waves_complete` checkpoint, recovery read
    nothing and re-ran silently, so an open tool call or a raised approval gate
    left by the interrupted run was neither reconstructed nor reported."""
    store = InMemoryCheckpointStore()
    await store.save(
        _checkpoint(store, 0, CheckpointKind.TOOL_CALL_ABOUT_TO_FIRE, {"call_id": "c1"})
    )
    await store.save(_checkpoint(store, 1, CheckpointKind.APPROVAL_GATE_RAISED, {"gate_id": "g1"}))
    await store.save(_checkpoint(store, 2, CheckpointKind.SPEND_UPDATE, {"delta": 2.5}))
    recorder = _Recorder()

    await WaveOrchestrator(
        _runner, checkpoint_store=store, config=VERSION_A, emit=recorder
    ).execute(_task())

    fields = recorder.fields(EVENT_RECOVERY_RESUMED)
    assert fields["complete"] is False
    assert fields["open_tool_calls"] == 1
    assert fields["pending_approval_gates"] == 1
    assert fields["cumulative_spend"] == 2.5


@pytest.mark.ac("SPEC-256/AC-5")
async def test_the_ensemble_s_own_checkpoints_can_be_folded() -> None:
    """The fold and the writer shipped without being run against each other:
    `replay` read `payload["wave_id"]` and the ensemble writes `wave_ids` on its
    task-level markers, so folding a real run raised KeyError."""
    store = await _completed_under(VERSION_A)
    recorder = _Recorder()

    await WaveOrchestrator(
        _runner, checkpoint_store=store, config=VERSION_A, emit=recorder
    ).execute(_task())

    assert recorder.fields(EVENT_RECOVERY_RESUMED)["waves_recorded"] == 0


def _checkpoint(
    store: InMemoryCheckpointStore, sequence: int, kind: CheckpointKind, payload: dict[str, Any]
) -> Any:
    from datetime import UTC, datetime

    from maistro.tasks.checkpoint import TaskCheckpoint

    return TaskCheckpoint(
        task_id="task-1",
        sequence=sequence,
        kind=kind,
        payload=payload,
        recipe_version="1",
        code_registry_version="a",
        created_at=datetime.now(UTC),
    )
