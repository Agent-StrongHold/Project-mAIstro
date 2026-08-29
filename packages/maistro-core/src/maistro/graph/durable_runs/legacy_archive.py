"""Read a durable graph run written before the store convergence (#44).

The convergence moved Run, NodeRun and Attempt identity into the canonical
`RunStore`, and `CanonicalDurableRunStore` refuses a record whose Run the spine
has never seen -- deliberately, because minting one would be inventing an
identity for a caller that skipped the store. That refusal is right for new
work and wrong for old rows: every graph run persisted before #565 has ids the
spine never saw, so after the convergence there is no reader for them at all.

This is that reader. It opens a pre-convergence database read-only and returns
what the record says happened -- the Run, its NodeRuns and Attempts in
persistence order, and the traversal history beside them.

**Reproducible, not resumable.** The distinction is the whole design. A
resumable projection would have to write these identities onto the spine, and
the spine allocates identity itself: `create_run`, `create_node_run` and
`create_attempt` take no id. Replaying an archived record through them would
either mint different ids -- so the archive and the spine would disagree about
the same execution -- or require an id-preserving write path, which is the
second system of record this issue exists to remove. So the archive answers
questions about the past and refuses to become the present.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maistro.runs.model import Attempt, NodeRun, Run, RunStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

#: The table the pre-convergence SQLite store wrote to.
#:
#: Named for readers and for the tests, and deliberately *not* interpolated
#: into the statements below. A table name cannot be a bind parameter, so
#: using the constant in a query means building the SQL by string
#: construction -- bandit B608, which this repository runs at a strict zero
#: baseline. The scanner is right to be blunt: a query assembled by
#: f-string is one refactor away from assembling one out of something a
#: caller supplied.
LEGACY_TABLE = "durable_graph_runs"


class LegacyRunNotResumable(RuntimeError):
    """Raised rather than silently giving an archived run a new identity."""


@dataclass(frozen=True)
class ArchivedGraphRun:
    """One pre-convergence durable graph run, as it was persisted.

    Frozen because it is history. Nothing here is a live handle: the Run is not
    on the spine, the NodeRuns cannot be transitioned, and the Attempts cannot
    be redispatched.
    """

    run: Run
    node_runs: tuple[NodeRun, ...]
    attempts: tuple[Attempt, ...]
    graph_state: dict[str, Any]
    traversal_checkpoints: tuple[dict[str, Any], ...]
    traversal_commits: tuple[dict[str, Any], ...]
    version: int

    @property
    def run_id(self) -> str:
        return self.run.run_id

    def attempts_for(self, node_run_id: str) -> tuple[Attempt, ...]:
        """Every Attempt recorded under one archived NodeRun, in order."""
        return tuple(item for item in self.attempts if item.node_run_id == node_run_id)

    def resume(self) -> None:
        """Always refuses, by name, so the reason survives the call site."""
        raise LegacyRunNotResumable(
            f"run {self.run_id!r} was persisted before the canonical store convergence; "
            "its Run, NodeRun and Attempt identities were never admitted to the spine, "
            "so it can be read but not resumed"
        )


class LegacyGraphRunArchive:
    """Read-only reader over a pre-convergence durable-graph database.

    Opened through a `file:...?mode=ro` URI rather than by trusting this class
    not to write: the guarantee that reading history cannot alter it should be
    the database's, not a reviewer's.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        if not self._path.exists():
            raise FileNotFoundError(f"no such durable-run archive: {self._path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def list_run_ids(self) -> list[str]:
        """Every archived run, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id FROM durable_graph_runs ORDER BY created_at ASC, run_id ASC"
            ).fetchall()
        return [str(row["run_id"]) for row in rows]

    def get(self, run_id: str) -> ArchivedGraphRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM durable_graph_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return _reproduce(json.loads(row["record_json"]))

    def list_by_status(self, status: RunStatus) -> list[ArchivedGraphRun]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record_json FROM durable_graph_runs WHERE status = ? "
                "ORDER BY created_at ASC, run_id ASC",
                (status.value,),
            ).fetchall()
        return [_reproduce(json.loads(row["record_json"])) for row in rows]


def _reproduce(payload: dict[str, Any]) -> ArchivedGraphRun:
    """Rebuild one archived record from its stored JSON.

    Validated through the canonical models rather than returned as raw JSON:
    the claim criterion 5 makes is that these executions remain *reproducible*,
    and a dict nobody can turn back into a `Run` does not establish that. It
    would also hide the failure that matters most here -- a model change that
    makes old records unloadable -- behind a dict that still parses.
    """
    return ArchivedGraphRun(
        run=Run.model_validate(payload["run"]),
        node_runs=tuple(NodeRun.model_validate(item) for item in _seq(payload, "node_runs")),
        attempts=tuple(Attempt.model_validate(item) for item in _seq(payload, "attempts")),
        graph_state=dict(payload.get("graph_state") or {}),
        traversal_checkpoints=tuple(_seq(payload, "traversal_checkpoints")),
        traversal_commits=tuple(_seq(payload, "traversal_commits")),
        version=int(payload.get("version", 0)),
    )


def _seq(payload: dict[str, Any], key: str) -> Sequence[dict[str, Any]]:
    value = payload.get(key) or ()
    if not isinstance(value, list | tuple):
        raise ValueError(f"archived record field {key!r} is not a sequence")
    return value


__all__ = [
    "LEGACY_TABLE",
    "ArchivedGraphRun",
    "LegacyGraphRunArchive",
    "LegacyRunNotResumable",
]
