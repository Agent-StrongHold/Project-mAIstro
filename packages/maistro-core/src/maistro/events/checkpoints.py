"""Canonical checkpoint contract and durable persistence. **Superseded.**

Checkpoints here are immutable execution snapshots scoped to one canonical Run.
They carry opaque resumable state plus compatibility metadata and the canonical
IDs needed to create a replacement Attempt after recovery.

**Nothing in this repository constructs one.** No production module imports this
module, the container wires none of these stores, and `canonical_checkpoints`
appears in no revision under `alembic/versions`, so that table exists in no
PostgreSQL deployment and has no twin. The store is SQLite-only and creates its
own schema.

**`DurableRunRecord` is the canonical checkpoint of a graph execution**, not this
`Checkpoint` (ADR-083026-ebcb). That is the record `resume_durable_graph` reads,
`CanonicalDurableRunStore` binds to canonical Run identity, and
`GraphContinuationStore` persists with a real PostgreSQL twin. `container.py`
already says so where it wires them: "a `DurableRunRecord` is a checkpoint of one
graph execution and a `Run` is the execution's canonical identity".

Kept rather than deleted because the schema-versioning and content-hash rules
below are what a later consolidation would want to reuse, and discarding a
specified contract is a larger decision than the one that superseded it. Read
this as a design that lost, not as a description of what runs: no checkpoint row
here exists anywhere, and nothing recovers from one.

A third vocabulary exists and is genuinely reached: ADR-056's `TaskCheckpoint`
in `maistro.tasks.checkpoint`, keyed by `task_id` and versioned by recipe rather
than by canonical id, used from `orchestrator/waves/ensemble.py`.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import uuid4

from maistro.events.envelope import EventEnvelope

if TYPE_CHECKING:
    import aiosqlite

CHECKPOINT_SCHEMA_VERSION = 1
SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS = frozenset({CHECKPOINT_SCHEMA_VERSION})


def _state_hash(state: dict[str, Any]) -> str:
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_versions(schema_version: int, event_sequence: int | None) -> None:
    if schema_version < 1:
        raise ValueError("schema_version must be positive")
    if event_sequence is not None and event_sequence < 1:
        raise ValueError("event_sequence must be positive when present")


def _checkpoint_state_hash(
    state: dict[str, Any],
    state_locator: str,
    supplied_hash: str,
) -> str:
    has_locator = bool(state_locator.strip())
    if not state and not has_locator:
        raise ValueError("checkpoint requires inline state or state_locator")
    if supplied_hash:
        return supplied_hash
    if state:
        return _state_hash(state)
    raise ValueError("external checkpoint state requires state_hash")


class CheckpointError(RuntimeError):
    """Base error for canonical checkpoint persistence and resume."""


class CheckpointNotFoundError(CheckpointError):
    """A resume reference points to a checkpoint that does not exist."""


class CheckpointVersionError(CheckpointError):
    """A checkpoint cannot be resumed by the requested compatibility set."""


@dataclass(frozen=True)
class CheckpointRef:
    """Stable resume reference persisted on an Attempt or recovery record."""

    checkpoint_id: str
    schema_version: int = CHECKPOINT_SCHEMA_VERSION


@dataclass(frozen=True)
class Checkpoint:
    """Immutable resumability fact for one canonical Run.

    State may be stored inline, referenced through ``state_locator``, or both. A
    content hash is always retained. ``executable_version`` identifies the runtime
    or executable contract that must be compatible before resume.
    """

    workspace_id: str
    project_id: str
    run_id: str
    executable_version: str
    state: dict[str, Any] = field(default_factory=dict)
    checkpoint_id: str = field(default_factory=lambda: uuid4().hex)
    schema_version: int = CHECKPOINT_SCHEMA_VERSION
    sequence: int | None = None
    event_sequence: int | None = None
    node_run_id: str = ""
    attempt_id: str = ""
    previous_checkpoint_id: str = ""
    reason: str = ""
    state_locator: str = ""
    state_hash: str = ""
    graph_id: str = ""
    graph_snapshot_hash: str = ""
    created_at: float = field(default_factory=time.time)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("workspace_id", self.workspace_id)
        _require_text("project_id", self.project_id)
        _require_text("run_id", self.run_id)
        _require_text("executable_version", self.executable_version)
        _validate_versions(self.schema_version, self.event_sequence)
        detached_state = copy.deepcopy(self.state)
        detached_provenance = copy.deepcopy(self.provenance)
        resolved_hash = _checkpoint_state_hash(
            detached_state,
            self.state_locator,
            self.state_hash,
        )
        object.__setattr__(self, "state", detached_state)
        object.__setattr__(self, "provenance", detached_provenance)
        object.__setattr__(self, "state_hash", resolved_hash)

    @property
    def ref(self) -> CheckpointRef:
        """Return the stable resume reference for this checkpoint."""
        return CheckpointRef(
            checkpoint_id=self.checkpoint_id,
            schema_version=self.schema_version,
        )


def checkpoint_created_event(checkpoint: Checkpoint) -> EventEnvelope:
    """Project a persisted checkpoint into its correlated canonical Event."""
    return EventEnvelope(
        type="checkpoint.created",
        workspace_id=checkpoint.workspace_id,
        project_id=checkpoint.project_id,
        run_id=checkpoint.run_id,
        node_run_id=checkpoint.node_run_id,
        attempt_id=checkpoint.attempt_id,
        source="checkpoint",
        provenance=dict(checkpoint.provenance),
        payload={
            "checkpoint_id": checkpoint.checkpoint_id,
            "checkpoint_sequence": checkpoint.sequence,
            "schema_version": checkpoint.schema_version,
            "event_sequence": checkpoint.event_sequence,
            "executable_version": checkpoint.executable_version,
            "state_locator": checkpoint.state_locator,
            "state_hash": checkpoint.state_hash,
            "graph_id": checkpoint.graph_id,
            "graph_snapshot_hash": checkpoint.graph_snapshot_hash,
            "previous_checkpoint_id": checkpoint.previous_checkpoint_id,
            "reason": checkpoint.reason,
        },
    )


@runtime_checkable
class CheckpointStore(Protocol):
    """Append-only persistence for canonical Checkpoint snapshots.

    Not `maistro.orchestrator.waves.ensemble.CheckpointStore`, which shares this
    name and no methods: that one is `save`/`load`/`next_sequence` over ADR-056
    `TaskCheckpoint`s keyed by `task_id`, and it is the one that actually runs.
    This one is `append`/`get`/`latest`/`list_run` over Run-keyed snapshots, and
    nothing constructs it (#729).
    """

    async def append(self, checkpoint: Checkpoint) -> Checkpoint:
        """Persist a checkpoint idempotently and assign its Run sequence."""
        ...

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Return one checkpoint by stable ID."""
        ...

    async def latest(self, run_id: str) -> Checkpoint | None:
        """Return the most recent checkpoint for a Run."""
        ...

    async def list_run(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[Checkpoint]:
        """Return Run checkpoints in ascending sequence order."""
        ...


async def resolve_checkpoint(
    store: CheckpointStore,
    ref: CheckpointRef,
    *,
    supported_schema_versions: frozenset[int] = SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS,
    supported_executable_versions: frozenset[str] | None = None,
) -> Checkpoint:
    """Resolve a resume reference and reject incompatible state/executable versions."""
    if ref.schema_version not in supported_schema_versions:
        raise CheckpointVersionError(
            f"checkpoint schema version {ref.schema_version} is not supported"
        )
    checkpoint = await store.get(ref.checkpoint_id)
    if checkpoint is None:
        raise CheckpointNotFoundError(ref.checkpoint_id)
    if checkpoint.schema_version != ref.schema_version:
        raise CheckpointVersionError(
            "resume reference schema version does not match persisted checkpoint"
        )
    if (
        supported_executable_versions is not None
        and checkpoint.executable_version not in supported_executable_versions
    ):
        raise CheckpointVersionError(
            f"checkpoint executable version {checkpoint.executable_version} is not supported"
        )
    return checkpoint


class InMemoryCheckpointStore:
    """Concurrency-safe in-memory CheckpointStore."""

    def __init__(self) -> None:
        self._checkpoints_by_id: dict[str, Checkpoint] = {}
        self._runs: dict[str, list[Checkpoint]] = {}
        self._lock = asyncio.Lock()

    async def append(self, checkpoint: Checkpoint) -> Checkpoint:
        async with self._lock:
            existing = self._checkpoints_by_id.get(checkpoint.checkpoint_id)
            if existing is not None:
                return existing
            if checkpoint.sequence is not None:
                raise ValueError("sequence is store-assigned and must be None on append")

            run = self._runs.setdefault(checkpoint.run_id, [])
            persisted = replace(
                checkpoint,
                sequence=len(run) + 1,
                state=copy.deepcopy(checkpoint.state),
                provenance=copy.deepcopy(checkpoint.provenance),
            )
            run.append(persisted)
            self._checkpoints_by_id[persisted.checkpoint_id] = persisted
            return persisted

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        return self._checkpoints_by_id.get(checkpoint_id)

    async def latest(self, run_id: str) -> Checkpoint | None:
        run = self._runs.get(run_id, [])
        return run[-1] if run else None

    async def list_run(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[Checkpoint]:
        if limit < 1:
            return []
        return [
            checkpoint
            for checkpoint in self._runs.get(run_id, [])
            if checkpoint.sequence is not None and checkpoint.sequence > after_sequence
        ][:limit]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    created_at REAL NOT NULL,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    node_run_id TEXT NOT NULL DEFAULT '',
    attempt_id TEXT NOT NULL DEFAULT '',
    event_sequence INTEGER,
    previous_checkpoint_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    executable_version TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{}',
    state_locator TEXT NOT NULL DEFAULT '',
    state_hash TEXT NOT NULL,
    graph_id TEXT NOT NULL DEFAULT '',
    graph_snapshot_hash TEXT NOT NULL DEFAULT '',
    provenance TEXT NOT NULL DEFAULT '{}',
    UNIQUE(run_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_canonical_checkpoint_run
    ON canonical_checkpoints (run_id, sequence);
"""


class SqliteCheckpointStore:
    """SQLite implementation of the canonical CheckpointStore contract."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def append(self, checkpoint: Checkpoint) -> Checkpoint:
        async with self._lock:
            if checkpoint.sequence is not None:
                raise ValueError("sequence is store-assigned and must be None on append")

            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self._conn.execute(
                    "SELECT * FROM canonical_checkpoints WHERE checkpoint_id = ?",
                    (checkpoint.checkpoint_id,),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    await self._conn.commit()
                    return self._row_to_checkpoint(tuple(existing))

                cursor = await self._conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 "
                    "FROM canonical_checkpoints WHERE run_id = ?",
                    (checkpoint.run_id,),
                )
                row = await cursor.fetchone()
                sequence = int(row[0]) if row is not None else 1
                persisted = replace(
                    checkpoint,
                    sequence=sequence,
                    state=copy.deepcopy(checkpoint.state),
                    provenance=copy.deepcopy(checkpoint.provenance),
                )
                await self._conn.execute(
                    """INSERT INTO canonical_checkpoints (
                        checkpoint_id, run_id, sequence, schema_version, created_at,
                        workspace_id, project_id, node_run_id, attempt_id, event_sequence,
                        previous_checkpoint_id, reason, executable_version, state,
                        state_locator, state_hash, graph_id, graph_snapshot_hash, provenance
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        persisted.checkpoint_id,
                        persisted.run_id,
                        persisted.sequence,
                        persisted.schema_version,
                        persisted.created_at,
                        persisted.workspace_id,
                        persisted.project_id,
                        persisted.node_run_id,
                        persisted.attempt_id,
                        persisted.event_sequence,
                        persisted.previous_checkpoint_id,
                        persisted.reason,
                        persisted.executable_version,
                        json.dumps(persisted.state),
                        persisted.state_locator,
                        persisted.state_hash,
                        persisted.graph_id,
                        persisted.graph_snapshot_hash,
                        json.dumps(persisted.provenance),
                    ),
                )
                await self._conn.commit()
                return persisted
            except Exception:
                await self._conn.rollback()
                raise

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        cursor = await self._conn.execute(
            "SELECT * FROM canonical_checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_checkpoint(tuple(row)) if row is not None else None

    async def latest(self, run_id: str) -> Checkpoint | None:
        cursor = await self._conn.execute(
            """SELECT * FROM canonical_checkpoints
               WHERE run_id = ? ORDER BY sequence DESC LIMIT 1""",
            (run_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_checkpoint(tuple(row)) if row is not None else None

    async def list_run(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[Checkpoint]:
        if limit < 1:
            return []
        cursor = await self._conn.execute(
            """SELECT * FROM canonical_checkpoints
               WHERE run_id = ? AND sequence > ?
               ORDER BY sequence ASC LIMIT ?""",
            (run_id, after_sequence, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_checkpoint(tuple(row)) for row in rows]

    @staticmethod
    def _row_to_checkpoint(row: tuple[Any, ...]) -> Checkpoint:
        return Checkpoint(
            checkpoint_id=row[0],
            run_id=row[1],
            sequence=row[2],
            schema_version=row[3],
            created_at=row[4],
            workspace_id=row[5],
            project_id=row[6],
            node_run_id=row[7],
            attempt_id=row[8],
            event_sequence=row[9],
            previous_checkpoint_id=row[10],
            reason=row[11],
            executable_version=row[12],
            state=json.loads(row[13]),
            state_locator=row[14],
            state_hash=row[15],
            graph_id=row[16],
            graph_snapshot_hash=row[17],
            provenance=json.loads(row[18]),
        )
