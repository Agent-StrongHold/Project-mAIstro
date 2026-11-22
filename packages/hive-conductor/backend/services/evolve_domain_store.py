"""Durable Evolve domain snapshot and publication ledger (#1064).

Evolve's population/tournament are domain state the Evolve package owns, but
before this store every idempotency key the canonical adapter wrote — battle
publication identities and finalize cycle markers — lived only in the
process's in-memory ``PopulationStore``/``EloTournament``. A genuinely new
process (a restart, a second replica) had no durable population/tournament to
reconstruct, so recovery could only refuse (``EvolveRecoveryBlocked``). This
module is the durable half the recovery contract names: a versioned domain
snapshot plus an ordered effect-publication journal, linked to canonical
Run/NodeRun identities.

Two logical records over two tables (or their sqlite/memory twins):

* **Snapshot** (``evolve_domain_snapshots``): the full serialized domain at a
  publication boundary, keyed by ``(workspace_id, run_id, kind)``. ``kind``
  is ``admission`` (the pre-cycle state ``run_canonical_evolution_cycle``
  saves before the Run's first mutation — the compensation reference) or
  ``committed`` (the post-finalize state saved when finalize commits). The
  snapshot embeds the tournament's ``last_battle_seq`` (the journal head at
  capture) so a restore replays exactly the journal rows published after the
  snapshot and none of the ones it already carries.
* **Publication** (``evolve_domain_publications``): one row per durably
  published domain effect, keyed by
  ``(workspace_id, effect_kind, node_run_id, benchmark)``. ``effect_kind``
  is ``battle`` (one row per (NodeRun, benchmark) battle — the primary key
  *is* the exactly-once fence: two concurrent publishers race on
  ``INSERT ... ON CONFLICT``, exactly one inserts) or ``finalize`` (one row
  per finalize NodeRun whose payload is the marker state machine:
  ``in_progress`` → ``committed{output}``/``faulted``).

Ownership stays where the issue puts it: this is Evolve-owned durable state
composable with the canonical spine, not a second execution authority. The
canonical Run/NodeRun/Attempt records remain the only execution truth; this
ledger answers exactly one question — *has this logical NodeRun already
published this domain effect, and what did the domain look like when it did?*
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from maistro.runs.evidence_json import decode_payload

#: Runtime bootstrap DDL for the PostgreSQL backends. The migration chain
#: (``alembic/versions/069_evolve_domain_publications.py``) owns ``CREATE
#: TABLE`` for real deployments and carries byte-identical DDL; this constant
#: is what ``ensure_schema`` runs on standalone pools (tests, dev runs), the
#: same pairing the delegation/event stores use.
POSTGRES_EVOLVE_DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS evolve_domain_snapshots (
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    payload JSONB NOT NULL,
    seq BIGSERIAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, run_id, kind)
);
CREATE TABLE IF NOT EXISTS evolve_domain_publications (
    workspace_id TEXT NOT NULL,
    effect_kind TEXT NOT NULL,
    node_run_id TEXT NOT NULL,
    benchmark TEXT NOT NULL DEFAULT '',
    attempt_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    seq BIGSERIAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, effect_kind, node_run_id, benchmark)
);
CREATE INDEX IF NOT EXISTS ix_evolve_domain_snapshots_ws_seq
    ON evolve_domain_snapshots (workspace_id, seq);
CREATE INDEX IF NOT EXISTS ix_evolve_domain_publications_ws_kind_seq
    ON evolve_domain_publications (workspace_id, effect_kind, seq);
"""

_SNAPSHOT_KIND_ADMISSION = "admission"
_SNAPSHOT_KIND_COMMITTED = "committed"
_EFFECT_BATTLE = "battle"
_EFFECT_FINALIZE = "finalize"


class EvolveDomainSnapshot(BaseModel):
    """One versioned serialization of the Evolve domain at a boundary."""

    version: int = 1
    workspace_id: str
    run_id: str
    kind: str  # admission | committed
    membership_ids: list[str] = Field(default_factory=list)
    membership_hash: str = ""
    completed_cycles: int = 0
    # One PipelineGenome.model_dump_json() per genome.
    genomes: list[str] = Field(default_factory=list)
    tournament: dict[str, Any] = Field(default_factory=dict)
    cycle_markers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Journal head at capture: a restore replays battle publications with
    # seq strictly greater than this, never the ones this snapshot carries.
    last_battle_seq: int = 0


class EvolveDomainPublication(BaseModel):
    """One durably published domain effect (battle or finalize marker)."""

    effect_kind: str
    node_run_id: str
    benchmark: str = ""
    attempt_id: str = ""
    run_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    # Journal order; 0 until the store assigns it.
    sequence: int = 0


@runtime_checkable
class EvolveDomainStore(Protocol):
    """The durable seam the canonical Evolve adapter writes through."""

    @property
    def backend(self) -> str:
        """``postgres`` | ``sqlite`` | ``memory`` — for honest observability."""
        ...

    async def ensure_schema(self) -> None: ...

    async def save_snapshot(self, snapshot: EvolveDomainSnapshot) -> None: ...

    async def latest_snapshot(
        self, workspace_id: str, *, kind: str | None = None
    ) -> EvolveDomainSnapshot | None: ...

    async def record_battle_publication(
        self, workspace_id: str, publication: EvolveDomainPublication
    ) -> bool:
        """Insert-if-absent; True when THIS call won the insert (effect is ours)."""
        ...

    async def find_battle_publication(
        self, workspace_id: str, node_run_id: str, benchmark: str
    ) -> EvolveDomainPublication | None: ...

    async def list_battle_publications(
        self, workspace_id: str, *, after_seq: int = 0
    ) -> list[EvolveDomainPublication]: ...

    async def battle_journal_head(self, workspace_id: str) -> int:
        """The current journal sequence head (0 when empty) — snapshot capture uses it."""
        ...

    async def upsert_finalize_marker(
        self, workspace_id: str, node_run_id: str, payload: dict[str, Any], *, run_id: str
    ) -> None: ...

    async def get_finalize_marker(
        self, workspace_id: str, node_run_id: str
    ) -> EvolveDomainPublication | None: ...

    async def list_finalize_markers(self, workspace_id: str) -> list[EvolveDomainPublication]: ...


class InMemoryEvolveDomainStore:
    """Process-local twin. Honest about being non-durable: ``backend == "memory"``."""

    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str, str], EvolveDomainSnapshot] = {}
        self._snap_seq = 0
        self._publications: dict[tuple[str, str, str, str], EvolveDomainPublication] = {}
        self._pub_seq = 0
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        return "memory"

    async def ensure_schema(self) -> None:
        return None

    async def save_snapshot(self, snapshot: EvolveDomainSnapshot) -> None:
        with self._lock:
            self._snap_seq += 1
            stored = snapshot.model_copy(deep=True)
            stored.last_battle_seq = snapshot.last_battle_seq
            self._snapshots[(snapshot.workspace_id, snapshot.run_id, snapshot.kind)] = stored

    async def latest_snapshot(
        self, workspace_id: str, *, kind: str | None = None
    ) -> EvolveDomainSnapshot | None:
        with self._lock:
            candidates = [s for (ws, _r, k), s in self._snapshots.items() if ws == workspace_id]
            if kind is not None:
                candidates = [s for s in candidates if s.kind == kind]
            if not candidates:
                return None
            return candidates[-1].model_copy(deep=True)

    async def record_battle_publication(
        self, workspace_id: str, publication: EvolveDomainPublication
    ) -> bool:
        key = (workspace_id, _EFFECT_BATTLE, publication.node_run_id, publication.benchmark)
        with self._lock:
            if key in self._publications:
                return False
            self._pub_seq += 1
            stored = publication.model_copy(
                deep=True, update={"effect_kind": _EFFECT_BATTLE, "sequence": self._pub_seq}
            )
            self._publications[key] = stored
            return True

    async def find_battle_publication(
        self, workspace_id: str, node_run_id: str, benchmark: str
    ) -> EvolveDomainPublication | None:
        with self._lock:
            found = self._publications.get((workspace_id, _EFFECT_BATTLE, node_run_id, benchmark))
            return found.model_copy(deep=True) if found else None

    async def list_battle_publications(
        self, workspace_id: str, *, after_seq: int = 0
    ) -> list[EvolveDomainPublication]:
        with self._lock:
            rows = [
                p
                for (ws, kind, _nr, _b), p in self._publications.items()
                if ws == workspace_id and kind == _EFFECT_BATTLE and p.sequence > after_seq
            ]
            return sorted(rows, key=lambda p: p.sequence)

    async def battle_journal_head(self, workspace_id: str) -> int:
        with self._lock:
            rows = [
                p.sequence
                for (ws, kind, _nr, _b), p in self._publications.items()
                if ws == workspace_id and kind == _EFFECT_BATTLE
            ]
            return max(rows, default=0)

    async def upsert_finalize_marker(
        self, workspace_id: str, node_run_id: str, payload: dict[str, Any], *, run_id: str
    ) -> None:
        key = (workspace_id, _EFFECT_FINALIZE, node_run_id, "")
        with self._lock:
            existing = self._publications.get(key)
            sequence = existing.sequence if existing else None
            if sequence is None:
                self._pub_seq += 1
                sequence = self._pub_seq
            self._publications[key] = EvolveDomainPublication(
                effect_kind=_EFFECT_FINALIZE,
                node_run_id=node_run_id,
                benchmark="",
                attempt_id="",
                run_id=run_id,
                payload=dict(payload),
                sequence=sequence,
            )

    async def get_finalize_marker(
        self, workspace_id: str, node_run_id: str
    ) -> EvolveDomainPublication | None:
        with self._lock:
            found = self._publications.get((workspace_id, _EFFECT_FINALIZE, node_run_id, ""))
            return found.model_copy(deep=True) if found else None

    async def list_finalize_markers(self, workspace_id: str) -> list[EvolveDomainPublication]:
        with self._lock:
            rows = [
                p
                for (ws, kind, _nr, _b), p in self._publications.items()
                if ws == workspace_id and kind == _EFFECT_FINALIZE
            ]
            return sorted(rows, key=lambda p: p.sequence)


class PgEvolveDomainStore:
    """asyncpg-backed durable store; the production fence for multi-replica recovery."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @property
    def backend(self) -> str:
        return "postgres"

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(POSTGRES_EVOLVE_DOMAIN_SCHEMA)

    async def save_snapshot(self, snapshot: EvolveDomainSnapshot) -> None:
        await self._pool.execute(
            """
            INSERT INTO evolve_domain_snapshots
                (workspace_id, run_id, kind, version, payload)
            VALUES ($1, $2, $3, $4, $5::text::jsonb)
            ON CONFLICT (workspace_id, run_id, kind) DO UPDATE
                SET version = EXCLUDED.version, payload = EXCLUDED.payload,
                    created_at = now()
            """,
            snapshot.workspace_id,
            snapshot.run_id,
            snapshot.kind,
            snapshot.version,
            json.dumps(snapshot.model_dump()),
        )

    async def latest_snapshot(
        self, workspace_id: str, *, kind: str | None = None
    ) -> EvolveDomainSnapshot | None:
        query = """
            SELECT payload FROM evolve_domain_snapshots
            WHERE workspace_id = $1 {kind}
            ORDER BY seq DESC LIMIT 1
        """
        if kind is None:
            row = await self._pool.fetchrow(query.format(kind=""), workspace_id)
        else:
            row = await self._pool.fetchrow(query.format(kind="AND kind = $2"), workspace_id, kind)
        if row is None:
            return None
        return EvolveDomainSnapshot.model_validate(decode_payload(row["payload"]))

    async def record_battle_publication(
        self, workspace_id: str, publication: EvolveDomainPublication
    ) -> bool:
        # ON CONFLICT DO NOTHING + RETURNING: the insert wins iff the row is
        # new. This single statement is the multi-replica exactly-once fence —
        # two workers racing to publish the same (NodeRun, benchmark) battle
        # cannot both insert.
        row = await self._pool.fetchrow(
            """
            INSERT INTO evolve_domain_publications
                (workspace_id, effect_kind, node_run_id, benchmark, attempt_id, run_id, payload)
            VALUES ($1, 'battle', $2, $3, $4, $5, $6::text::jsonb)
            ON CONFLICT (workspace_id, effect_kind, node_run_id, benchmark) DO NOTHING
            RETURNING seq
            """,
            workspace_id,
            publication.node_run_id,
            publication.benchmark,
            publication.attempt_id,
            publication.run_id,
            json.dumps(publication.payload),
        )
        return row is not None

    async def find_battle_publication(
        self, workspace_id: str, node_run_id: str, benchmark: str
    ) -> EvolveDomainPublication | None:
        row = await self._pool.fetchrow(
            """
            SELECT seq, attempt_id, run_id, payload
            FROM evolve_domain_publications
            WHERE workspace_id = $1 AND effect_kind = 'battle'
              AND node_run_id = $2 AND benchmark = $3
            """,
            workspace_id,
            node_run_id,
            benchmark,
        )
        if row is None:
            return None
        return EvolveDomainPublication(
            effect_kind=_EFFECT_BATTLE,
            node_run_id=node_run_id,
            benchmark=benchmark,
            attempt_id=row["attempt_id"],
            run_id=row["run_id"],
            payload=decode_payload(row["payload"]),
            sequence=int(row["seq"]),
        )

    async def list_battle_publications(
        self, workspace_id: str, *, after_seq: int = 0
    ) -> list[EvolveDomainPublication]:
        rows = await self._pool.fetch(
            """
            SELECT seq, node_run_id, benchmark, attempt_id, run_id, payload
            FROM evolve_domain_publications
            WHERE workspace_id = $1 AND effect_kind = 'battle' AND seq > $2
            ORDER BY seq ASC
            """,
            workspace_id,
            after_seq,
        )
        return [
            EvolveDomainPublication(
                effect_kind=_EFFECT_BATTLE,
                node_run_id=row["node_run_id"],
                benchmark=row["benchmark"],
                attempt_id=row["attempt_id"],
                run_id=row["run_id"],
                payload=decode_payload(row["payload"]),
                sequence=int(row["seq"]),
            )
            for row in rows
        ]

    async def battle_journal_head(self, workspace_id: str) -> int:
        row = await self._pool.fetchrow(
            """
            SELECT seq FROM evolve_domain_publications
            WHERE workspace_id = $1 AND effect_kind = 'battle'
            ORDER BY seq DESC LIMIT 1
            """,
            workspace_id,
        )
        return int(row["seq"]) if row else 0

    async def upsert_finalize_marker(
        self, workspace_id: str, node_run_id: str, payload: dict[str, Any], *, run_id: str
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO evolve_domain_publications
                (workspace_id, effect_kind, node_run_id, benchmark, attempt_id, run_id, payload)
            VALUES ($1, 'finalize', $2, '', '', $3, $4::text::jsonb)
            ON CONFLICT (workspace_id, effect_kind, node_run_id, benchmark) DO UPDATE
                SET payload = EXCLUDED.payload, attempt_id = EXCLUDED.attempt_id,
                    run_id = EXCLUDED.run_id, created_at = now()
            """,
            workspace_id,
            node_run_id,
            run_id,
            json.dumps(payload),
        )

    async def get_finalize_marker(
        self, workspace_id: str, node_run_id: str
    ) -> EvolveDomainPublication | None:
        row = await self._pool.fetchrow(
            """
            SELECT seq, attempt_id, run_id, payload
            FROM evolve_domain_publications
            WHERE workspace_id = $1 AND effect_kind = 'finalize' AND node_run_id = $2
            """,
            workspace_id,
            node_run_id,
        )
        if row is None:
            return None
        return EvolveDomainPublication(
            effect_kind=_EFFECT_FINALIZE,
            node_run_id=node_run_id,
            benchmark="",
            attempt_id=row["attempt_id"],
            run_id=row["run_id"],
            payload=decode_payload(row["payload"]),
            sequence=int(row["seq"]),
        )

    async def list_finalize_markers(self, workspace_id: str) -> list[EvolveDomainPublication]:
        rows = await self._pool.fetch(
            """
            SELECT seq, node_run_id, attempt_id, run_id, payload
            FROM evolve_domain_publications
            WHERE workspace_id = $1 AND effect_kind = 'finalize'
            ORDER BY seq ASC
            """,
            workspace_id,
        )
        return [
            EvolveDomainPublication(
                effect_kind=_EFFECT_FINALIZE,
                node_run_id=row["node_run_id"],
                benchmark="",
                attempt_id=row["attempt_id"],
                run_id=row["run_id"],
                payload=decode_payload(row["payload"]),
                sequence=int(row["seq"]),
            )
            for row in rows
        ]


class SqliteEvolveDomainStore:
    """File-backed twin for non-PostgreSQL deployments. Same fence: a PK insert race."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        return "sqlite"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    async def ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evolve_domain_snapshots (
                    workspace_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    version INT NOT NULL DEFAULT 1,
                    payload TEXT NOT NULL,
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (workspace_id, run_id, kind)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evolve_domain_publications (
                    workspace_id TEXT NOT NULL,
                    effect_kind TEXT NOT NULL,
                    node_run_id TEXT NOT NULL,
                    benchmark TEXT NOT NULL DEFAULT '',
                    attempt_id TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (workspace_id, effect_kind, node_run_id, benchmark)
                )
                """
            )

    async def save_snapshot(self, snapshot: EvolveDomainSnapshot) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evolve_domain_snapshots (workspace_id, run_id, kind, version, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (workspace_id, run_id, kind) DO UPDATE
                    SET version = excluded.version, payload = excluded.payload,
                        created_at = CURRENT_TIMESTAMP
                """,
                (
                    snapshot.workspace_id,
                    snapshot.run_id,
                    snapshot.kind,
                    snapshot.version,
                    snapshot.model_dump_json(),
                ),
            )

    async def latest_snapshot(
        self, workspace_id: str, *, kind: str | None = None
    ) -> EvolveDomainSnapshot | None:
        query = "SELECT payload FROM evolve_domain_snapshots WHERE workspace_id = ? {kind} ORDER BY seq DESC LIMIT 1"
        params: list[Any] = [workspace_id]
        if kind is not None:
            query = query.format(kind="AND kind = ?")
            params.append(kind)
        else:
            query = query.format(kind="")
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return EvolveDomainSnapshot.model_validate_json(row["payload"]) if row else None

    def _publication_from_row(self, row: sqlite3.Row, effect_kind: str) -> EvolveDomainPublication:
        return EvolveDomainPublication(
            effect_kind=effect_kind,
            node_run_id=row["node_run_id"],
            benchmark=row["benchmark"],
            attempt_id=row["attempt_id"],
            run_id=row["run_id"],
            payload=json.loads(row["payload"]),
            sequence=int(row["seq"]),
        )

    async def record_battle_publication(
        self, workspace_id: str, publication: EvolveDomainPublication
    ) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO evolve_domain_publications
                    (workspace_id, effect_kind, node_run_id, benchmark, attempt_id, run_id, payload)
                VALUES (?, 'battle', ?, ?, ?, ?, ?)
                ON CONFLICT (workspace_id, effect_kind, node_run_id, benchmark) DO NOTHING
                """,
                (
                    workspace_id,
                    publication.node_run_id,
                    publication.benchmark,
                    publication.attempt_id,
                    publication.run_id,
                    json.dumps(publication.payload),
                ),
            )
            return cursor.rowcount > 0

    async def find_battle_publication(
        self, workspace_id: str, node_run_id: str, benchmark: str
    ) -> EvolveDomainPublication | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM evolve_domain_publications
                WHERE workspace_id = ? AND effect_kind = 'battle'
                  AND node_run_id = ? AND benchmark = ?
                """,
                (workspace_id, node_run_id, benchmark),
            ).fetchone()
        return self._publication_from_row(row, _EFFECT_BATTLE) if row else None

    async def list_battle_publications(
        self, workspace_id: str, *, after_seq: int = 0
    ) -> list[EvolveDomainPublication]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM evolve_domain_publications
                WHERE workspace_id = ? AND effect_kind = 'battle' AND seq > ?
                ORDER BY seq ASC
                """,
                (workspace_id, after_seq),
            ).fetchall()
        return [self._publication_from_row(row, _EFFECT_BATTLE) for row in rows]

    async def battle_journal_head(self, workspace_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT seq FROM evolve_domain_publications
                WHERE workspace_id = ? AND effect_kind = 'battle'
                ORDER BY seq DESC LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        return int(row["seq"]) if row else 0

    async def upsert_finalize_marker(
        self, workspace_id: str, node_run_id: str, payload: dict[str, Any], *, run_id: str
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evolve_domain_publications
                    (workspace_id, effect_kind, node_run_id, benchmark, attempt_id, run_id, payload)
                VALUES (?, 'finalize', ?, '', '', ?, ?)
                ON CONFLICT (workspace_id, effect_kind, node_run_id, benchmark) DO UPDATE
                    SET payload = excluded.payload, attempt_id = excluded.attempt_id,
                        run_id = excluded.run_id, created_at = CURRENT_TIMESTAMP
                """,
                (workspace_id, node_run_id, run_id, json.dumps(payload)),
            )

    async def get_finalize_marker(
        self, workspace_id: str, node_run_id: str
    ) -> EvolveDomainPublication | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM evolve_domain_publications
                WHERE workspace_id = ? AND effect_kind = 'finalize' AND node_run_id = ?
                """,
                (workspace_id, node_run_id),
            ).fetchone()
        return self._publication_from_row(row, _EFFECT_FINALIZE) if row else None

    async def list_finalize_markers(self, workspace_id: str) -> list[EvolveDomainPublication]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM evolve_domain_publications
                WHERE workspace_id = ? AND effect_kind = 'finalize'
                ORDER BY seq ASC
                """,
                (workspace_id,),
            ).fetchall()
        return [self._publication_from_row(row, _EFFECT_FINALIZE) for row in rows]


__all__ = [
    "POSTGRES_EVOLVE_DOMAIN_SCHEMA",
    "EvolveDomainPublication",
    "EvolveDomainSnapshot",
    "EvolveDomainStore",
    "InMemoryEvolveDomainStore",
    "PgEvolveDomainStore",
    "SqliteEvolveDomainStore",
]
