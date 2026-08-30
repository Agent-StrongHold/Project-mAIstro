"""Contract tests for canonical checkpoints and resume references."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.events.checkpoints import (
    CHECKPOINT_SCHEMA_VERSION,
    Checkpoint,
    CheckpointNotFoundError,
    CheckpointRef,
    CheckpointVersionError,
    InMemoryRunCheckpointStore,
    RunCheckpointStore,
    SqliteRunCheckpointStore,
    checkpoint_created_event,
    resolve_checkpoint,
)


@pytest.fixture(params=["memory", "sqlite"])
async def checkpoint_store(
    request: pytest.FixtureRequest,
) -> AsyncIterator[RunCheckpointStore]:
    if request.param == "memory":
        yield InMemoryRunCheckpointStore()
        return
    conn = await aiosqlite.connect(":memory:")
    store = SqliteRunCheckpointStore(conn)
    await store.ensure_schema()
    yield store
    await conn.close()


def _checkpoint(**overrides: object) -> Checkpoint:
    values: dict[str, object] = {
        "workspace_id": "ws-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "executable_version": "runtime-v1",
        "state": {"cursor": "node-2", "answer": 42},
    }
    values.update(overrides)
    return Checkpoint(**values)  # type: ignore[arg-type]


def test_checkpoint_requires_scope_and_executable() -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        _checkpoint(workspace_id="")
    with pytest.raises(ValueError, match="project_id"):
        _checkpoint(project_id="")
    with pytest.raises(ValueError, match="run_id"):
        _checkpoint(run_id="")
    with pytest.raises(ValueError, match="executable_version"):
        _checkpoint(executable_version="")


def test_checkpoint_requires_state_or_locator() -> None:
    with pytest.raises(ValueError, match="inline state or state_locator"):
        _checkpoint(state={})
    with pytest.raises(ValueError, match="requires state_hash"):
        _checkpoint(state={}, state_locator="artifact://checkpoint/1")


def test_inline_state_gets_stable_hash() -> None:
    state = {"b": 2, "a": 1}
    checkpoint = _checkpoint(state=state)
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    assert checkpoint.state_hash == hashlib.sha256(encoded).hexdigest()


def test_external_state_retains_identity() -> None:
    checkpoint = _checkpoint(
        state={},
        state_locator="artifact://checkpoint/1",
        state_hash="sha256:abc123",
    )
    assert checkpoint.state_locator == "artifact://checkpoint/1"
    assert checkpoint.state_hash == "sha256:abc123"


def test_checkpoint_ref_preserves_schema_version() -> None:
    checkpoint = _checkpoint(checkpoint_id="cp-1", schema_version=3)
    expected = CheckpointRef(checkpoint_id="cp-1", schema_version=3)
    assert checkpoint.ref == expected


def test_checkpoint_created_event_preserves_correlation() -> None:
    checkpoint = _checkpoint(
        checkpoint_id="cp-event",
        sequence=4,
        event_sequence=17,
        node_run_id="node-run-1",
        attempt_id="attempt-2",
        graph_id="graph-1",
        graph_snapshot_hash="graph-sha",
        reason="provider-yield",
        provenance={"runtime": "python"},
    )
    event = checkpoint_created_event(checkpoint)
    assert event.type == "checkpoint.created"
    assert event.workspace_id == "ws-1"
    assert event.project_id == "project-1"
    assert event.run_id == "run-1"
    assert event.node_run_id == "node-run-1"
    assert event.attempt_id == "attempt-2"
    assert event.payload["checkpoint_id"] == "cp-event"
    assert event.payload["checkpoint_sequence"] == 4
    assert event.payload["event_sequence"] == 17
    assert event.payload["graph_snapshot_hash"] == "graph-sha"


class TestCheckpointStoreContract:
    async def test_assigns_sequence_per_run(self, checkpoint_store: RunCheckpointStore) -> None:
        first = await checkpoint_store.append(_checkpoint(checkpoint_id="cp-1"))
        second = await checkpoint_store.append(_checkpoint(checkpoint_id="cp-2"))
        other = _checkpoint(checkpoint_id="cp-other", run_id="run-2")
        persisted_other = await checkpoint_store.append(other)
        assert first.sequence == 1
        assert second.sequence == 2
        assert persisted_other.sequence == 1

    async def test_append_is_idempotent(self, checkpoint_store: RunCheckpointStore) -> None:
        checkpoint = _checkpoint(checkpoint_id="stable")
        first = await checkpoint_store.append(checkpoint)
        duplicate = await checkpoint_store.append(checkpoint)
        history = await checkpoint_store.list_run("run-1")
        assert duplicate == first
        assert [item.checkpoint_id for item in history] == ["stable"]

    async def test_rejects_caller_sequence(self, checkpoint_store: RunCheckpointStore) -> None:
        with pytest.raises(ValueError, match="store-assigned"):
            await checkpoint_store.append(_checkpoint(sequence=7))

    async def test_round_trips_metadata(self, checkpoint_store: RunCheckpointStore) -> None:
        checkpoint = _checkpoint(
            checkpoint_id="cp-roundtrip",
            node_run_id="node-run-1",
            attempt_id="attempt-2",
            event_sequence=17,
            previous_checkpoint_id="cp-previous",
            reason="provider-yield",
            state_locator="artifact://checkpoint/roundtrip",
            graph_id="graph-1",
            graph_snapshot_hash="graph-sha",
            provenance={"runtime": "python"},
        )
        persisted = await checkpoint_store.append(checkpoint)
        loaded = await checkpoint_store.get("cp-roundtrip")
        assert loaded == persisted
        assert loaded is not None
        assert loaded.event_sequence == 17
        assert loaded.executable_version == "runtime-v1"
        assert loaded.graph_snapshot_hash == "graph-sha"
        assert loaded.state_hash == checkpoint.state_hash

    async def test_latest_and_cursor_reads(self, checkpoint_store: RunCheckpointStore) -> None:
        for index in range(5):
            checkpoint = _checkpoint(checkpoint_id=f"cp-{index}")
            await checkpoint_store.append(checkpoint)
        latest = await checkpoint_store.latest("run-1")
        page = await checkpoint_store.list_run("run-1", after_sequence=2, limit=2)
        assert latest is not None
        assert latest.sequence == 5
        assert [item.sequence for item in page] == [3, 4]
        assert await checkpoint_store.list_run("run-1", limit=0) == []

    async def test_concurrent_sequences(self, checkpoint_store: RunCheckpointStore) -> None:
        checkpoints = [_checkpoint(checkpoint_id=f"cp-{i}") for i in range(20)]
        calls = [checkpoint_store.append(item) for item in checkpoints]
        persisted = await asyncio.gather(*calls)
        sequences = [item.sequence for item in persisted if item.sequence is not None]
        assert sorted(sequences) == list(range(1, 21))

    async def test_rejects_schema_incompatibility(
        self,
        checkpoint_store: RunCheckpointStore,
    ) -> None:
        persisted = await checkpoint_store.append(_checkpoint(checkpoint_id="cp-resume"))
        resolved = await resolve_checkpoint(checkpoint_store, persisted.ref)
        assert resolved == persisted
        bad_version = CHECKPOINT_SCHEMA_VERSION + 1
        bad_ref = CheckpointRef("cp-resume", schema_version=bad_version)
        with pytest.raises(CheckpointVersionError, match="not supported"):
            await resolve_checkpoint(checkpoint_store, bad_ref)

    async def test_rejects_reference_version_mismatch(
        self,
        checkpoint_store: RunCheckpointStore,
    ) -> None:
        checkpoint = _checkpoint(checkpoint_id="cp-versioned", schema_version=2)
        await checkpoint_store.append(checkpoint)
        ref = CheckpointRef("cp-versioned", schema_version=1)
        with pytest.raises(CheckpointVersionError, match="does not match"):
            await resolve_checkpoint(
                checkpoint_store,
                ref,
                supported_schema_versions=frozenset({1, 2}),
            )

    async def test_rejects_executable_incompatibility(
        self,
        checkpoint_store: RunCheckpointStore,
    ) -> None:
        checkpoint = _checkpoint(
            checkpoint_id="cp-runtime",
            executable_version="runtime-v2",
        )
        persisted = await checkpoint_store.append(checkpoint)
        supported = frozenset({"runtime-v1"})
        with pytest.raises(CheckpointVersionError, match="executable version"):
            await resolve_checkpoint(
                checkpoint_store,
                persisted.ref,
                supported_executable_versions=supported,
            )

    async def test_requires_existing_checkpoint(
        self,
        checkpoint_store: RunCheckpointStore,
    ) -> None:
        with pytest.raises(CheckpointNotFoundError):
            await resolve_checkpoint(checkpoint_store, CheckpointRef("missing"))
