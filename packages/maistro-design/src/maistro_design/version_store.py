"""Durable persistence for versioned creative artifact state (#780).

PostgreSQL store (raw SQL via sqlalchemy.text(), same pattern as
`maistro_design.stores`) for four projections of one creative project:

* `design_artifact_versions` — append-only change/version ledger. There is no
  update path for content or provenance: a version row is written once and
  first-writer-wins on (project, lineage, version). The only mutation is the
  narrow review transition draft → accepted/rejected, which changes no content.
* `design_artifact_locks` — explicit user locks; release records who and when.
* `design_project_guidance` — durable user guidance; superseded rows remain
  readable (invalidation by supersession, never deletion).
* `design_branch_controls` — one control-mode row per branch, naming the
  canonical Run it is attached to (a projection, not a second lifecycle).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from maistro_design.versions import (
    ArtifactLock,
    ArtifactVersion,
    ArtifactVersionExistsError,
    ArtifactVersionNotFoundError,
    BranchControl,
    ChangeKind,
    ChangeOrigin,
    ControlMode,
    GuidanceRecord,
    LockScope,
    VersionState,
    VersionStateError,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_datetime(value: Any) -> datetime:
    """Parse a timestamp the way the backends store it (pg returns datetime)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return datetime.fromisoformat(str(value))


def _as_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _as_json_dict(value: Any) -> dict[str, str]:
    if not value:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    return {str(k): str(v) for k, v in dict(value).items()}


def _coerce_version(row: Any) -> ArtifactVersion:
    d = row._mapping if hasattr(row, "_mapping") else row
    d = dict(d)
    return ArtifactVersion(
        org_id=d["org_id"],
        project_id=str(d["project_id"]),
        lineage_id=d["lineage_id"],
        version=int(d["version"]),
        kind=ChangeKind(d["kind"]),
        origin=ChangeOrigin(d["origin"]),
        title=d.get("title") or "",
        format=d.get("format"),
        content=d.get("content") or "",
        url=d.get("url"),
        trust_tier=d.get("trust_tier") or "t3",
        state=VersionState(d.get("state") or VersionState.DRAFT.value),
        parent_version=_as_int(d.get("parent_version")),
        fork_lineage_id=d.get("fork_lineage_id"),
        fork_version=_as_int(d.get("fork_version")),
        brief_ref=d.get("brief_ref"),
        decision_inputs=_as_json_dict(d.get("decision_inputs_json")),
        author=d.get("author") or "",
        run_id=d.get("run_id") or "",
        node_run_id=d.get("node_run_id") or "",
        attempt_id=d.get("attempt_id") or "",
        content_sha=d.get("content_sha") or "",
        created_at=_as_datetime(d["created_at"]) if d.get("created_at") else _utcnow(),
    )


def _coerce_lock(row: Any) -> ArtifactLock:
    d = dict(row._mapping if hasattr(row, "_mapping") else row)
    released_at = d.get("released_at")
    return ArtifactLock(
        org_id=d["org_id"],
        project_id=str(d["project_id"]),
        lineage_id=d["lineage_id"],
        scope=LockScope(d["scope"]),
        lock_id=d["lock_id"],
        version=_as_int(d.get("version")),
        address=d.get("address"),
        decision_ref=d.get("decision_ref"),
        decision_digest=d.get("decision_digest"),
        reason=d.get("reason") or "",
        created_by=d.get("created_by") or "",
        created_at=_as_datetime(d["created_at"]) if d.get("created_at") else _utcnow(),
        released_at=_as_datetime(released_at) if released_at else None,
        released_by=d.get("released_by"),
    )


def _coerce_guidance(row: Any) -> GuidanceRecord:
    d = dict(row._mapping if hasattr(row, "_mapping") else row)
    return GuidanceRecord(
        org_id=d["org_id"],
        project_id=str(d["project_id"]),
        text=d.get("text") or "",
        guidance_id=d["guidance_id"],
        lineage_id=d.get("lineage_id"),
        author=d.get("author") or "",
        run_id=d.get("run_id") or "",
        created_at=_as_datetime(d["created_at"]) if d.get("created_at") else _utcnow(),
        active=bool(d.get("active", True)),
        superseded_by=d.get("superseded_by"),
    )


def _coerce_control(row: Any) -> BranchControl:
    d = dict(row._mapping if hasattr(row, "_mapping") else row)
    return BranchControl(
        org_id=d["org_id"],
        project_id=str(d["project_id"]),
        lineage_id=d["lineage_id"],
        mode=ControlMode(d["mode"]),
        run_id=d.get("run_id"),
        updated_by=d.get("updated_by") or "",
        updated_at=_as_datetime(d["updated_at"]) if d.get("updated_at") else _utcnow(),
    )


_VERSION_COLUMNS = """
    id, org_id, project_id, lineage_id, version, kind, origin, title, format,
    content, url, trust_tier, state, parent_version, fork_lineage_id,
    fork_version, brief_ref, decision_inputs_json, author,
    run_id, node_run_id, attempt_id, content_sha, created_at
"""


class ArtifactVersionStore(Protocol):
    """Persistence boundary for versioned creative artifact state."""

    async def append_version(self, version: ArtifactVersion) -> ArtifactVersion: ...

    async def get_version(
        self, org_id: str, project_id: str, lineage_id: str, version: int
    ) -> ArtifactVersion | None: ...

    async def versions(
        self, org_id: str, project_id: str, lineage_id: str
    ) -> list[ArtifactVersion]: ...

    async def tip(
        self, org_id: str, project_id: str, lineage_id: str
    ) -> ArtifactVersion | None: ...

    async def set_version_state(
        self,
        org_id: str,
        project_id: str,
        lineage_id: str,
        version: int,
        state: VersionState,
    ) -> ArtifactVersion: ...

    async def add_lock(self, lock: ArtifactLock) -> ArtifactLock: ...

    async def release_lock(
        self, org_id: str, project_id: str, lock_id: str, released_by: str
    ) -> ArtifactLock: ...

    async def active_locks(
        self, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[ArtifactLock]: ...

    async def add_guidance(self, guidance: GuidanceRecord) -> GuidanceRecord: ...

    async def supersede_guidance(
        self, org_id: str, project_id: str, guidance_id: str, by_guidance_id: str
    ) -> GuidanceRecord: ...

    async def active_guidance(
        self, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[GuidanceRecord]: ...

    async def guidance_history(
        self, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[GuidanceRecord]: ...

    async def set_control(self, control: BranchControl) -> BranchControl: ...

    async def get_control(
        self, org_id: str, project_id: str, lineage_id: str
    ) -> BranchControl | None: ...


class PgArtifactVersionStore:
    """PostgreSQL (and SQLite-compatible) `ArtifactVersionStore`."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    # ── versions ──────────────────────────────────────────────────────────

    async def append_version(self, version: ArtifactVersion) -> ArtifactVersion:
        """Write a version row once. First writer wins on (project, lineage, version).

        The unique constraint is the race backstop: two concurrent writers
        produce one row and one `ArtifactVersionExistsError` — a supersession
        conflict, surfaced rather than silently double-written.
        """
        existing = await self.get_version(
            version.org_id, version.project_id, version.lineage_id, version.version
        )
        if existing is not None:
            raise ArtifactVersionExistsError(
                f"version {version.version} of lineage {version.lineage_id!r} "
                f"already exists in project {version.project_id!r}"
            )
        try:
            await self._execute(
                f"""
                INSERT INTO design_artifact_versions
                ({_VERSION_COLUMNS})
                VALUES (:id, :org_id, :project_id, :lineage_id, :version, :kind, :origin,
                        :title, :format, :content, :url, :trust_tier, :state,
                        :parent_version, :fork_lineage_id, :fork_version, :brief_ref,
                        :decision_inputs_json, :author,
                        :run_id, :node_run_id, :attempt_id, :content_sha, :created_at)
                """,
                {
                    "id": str(uuid.uuid4()),
                    "org_id": version.org_id,
                    "project_id": version.project_id,
                    "lineage_id": version.lineage_id,
                    "version": version.version,
                    "kind": version.kind.value,
                    "origin": version.origin.value,
                    "title": version.title,
                    "format": version.format,
                    "content": version.content,
                    "url": version.url,
                    "trust_tier": version.trust_tier,
                    "state": version.state.value,
                    "parent_version": version.parent_version,
                    "fork_lineage_id": version.fork_lineage_id,
                    "fork_version": version.fork_version,
                    "brief_ref": version.brief_ref,
                    "decision_inputs_json": (
                        json.dumps(version.decision_inputs) if version.decision_inputs else None
                    ),
                    "author": version.author,
                    "run_id": version.run_id or None,
                    "node_run_id": version.node_run_id or None,
                    "attempt_id": version.attempt_id or None,
                    "content_sha": version.content_sha,
                    "created_at": version.created_at,
                },
            )
        except IntegrityError as error:
            raise ArtifactVersionExistsError(
                f"version {version.version} of lineage {version.lineage_id!r} "
                f"already exists in project {version.project_id!r}"
            ) from error
        return version

    async def get_version(
        self, org_id: str, project_id: str, lineage_id: str, version: int
    ) -> ArtifactVersion | None:
        row = await self._fetch_one(
            f"SELECT {_VERSION_COLUMNS} FROM design_artifact_versions "
            "WHERE org_id = :org_id AND project_id = :project_id "
            "AND lineage_id = :lineage_id AND version = :version",
            {
                "org_id": org_id,
                "project_id": project_id,
                "lineage_id": lineage_id,
                "version": version,
            },
        )
        return _coerce_version(row) if row is not None else None

    async def versions(
        self, org_id: str, project_id: str, lineage_id: str
    ) -> list[ArtifactVersion]:
        rows = await self._fetch_all(
            f"SELECT {_VERSION_COLUMNS} FROM design_artifact_versions "
            "WHERE org_id = :org_id AND project_id = :project_id "
            "AND lineage_id = :lineage_id ORDER BY version ASC",
            {"org_id": org_id, "project_id": project_id, "lineage_id": lineage_id},
        )
        return [_coerce_version(row) for row in rows]

    async def tip(self, org_id: str, project_id: str, lineage_id: str) -> ArtifactVersion | None:
        """The newest version no other version descends from.

        Forks make the parent graph a DAG, so "highest version with no
        children" — not "highest version" — is the branch tip.
        """
        row = await self._fetch_one(
            f"SELECT {_VERSION_COLUMNS} FROM design_artifact_versions AS v "
            "WHERE v.org_id = :org_id AND v.project_id = :project_id "
            "AND v.lineage_id = :lineage_id "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM design_artifact_versions AS c "
            "  WHERE c.org_id = v.org_id AND c.project_id = v.project_id "
            "  AND c.lineage_id = v.lineage_id AND c.parent_version = v.version"
            ") ORDER BY v.version DESC LIMIT 1",
            {"org_id": org_id, "project_id": project_id, "lineage_id": lineage_id},
        )
        return _coerce_version(row) if row is not None else None

    async def set_version_state(
        self,
        org_id: str,
        project_id: str,
        lineage_id: str,
        version: int,
        state: VersionState,
    ) -> ArtifactVersion:
        """Transition a version's review state: draft → accepted/rejected only.

        Content and provenance are untouched — this is the one mutation a
        version row allows, and a version that already left draft is terminal.
        """
        if state is VersionState.DRAFT:
            raise VersionStateError("a version cannot return to draft")
        result = await self._execute(
            "UPDATE design_artifact_versions SET state = :state "
            "WHERE org_id = :org_id AND project_id = :project_id "
            "AND lineage_id = :lineage_id AND version = :version "
            "AND state = :draft",
            {
                "state": state.value,
                "draft": VersionState.DRAFT.value,
                "org_id": org_id,
                "project_id": project_id,
                "lineage_id": lineage_id,
                "version": version,
            },
        )
        if getattr(result, "rowcount", 0) != 1:
            raise ArtifactVersionNotFoundError(
                f"version {version} of lineage {lineage_id!r} in project {project_id!r} "
                "is absent or not in draft"
            )
        found = await self.get_version(org_id, project_id, lineage_id, version)
        assert found is not None  # the UPDATE above just matched it
        return found

    # ── locks ─────────────────────────────────────────────────────────────

    async def add_lock(self, lock: ArtifactLock) -> ArtifactLock:
        await self._execute(
            """
            INSERT INTO design_artifact_locks
            (lock_id, org_id, project_id, lineage_id, scope, version, address,
             decision_ref, decision_digest, reason, created_by, created_at,
             released_at, released_by)
            VALUES (:lock_id, :org_id, :project_id, :lineage_id, :scope, :version,
                    :address, :decision_ref, :decision_digest, :reason,
                    :created_by, :created_at, NULL, NULL)
            """,
            {
                "lock_id": lock.lock_id,
                "org_id": lock.org_id,
                "project_id": lock.project_id,
                "lineage_id": lock.lineage_id,
                "scope": lock.scope.value,
                "version": lock.version,
                "address": lock.address,
                "decision_ref": lock.decision_ref,
                "decision_digest": lock.decision_digest,
                "reason": lock.reason,
                "created_by": lock.created_by,
                "created_at": lock.created_at,
            },
        )
        return lock

    async def release_lock(
        self, org_id: str, project_id: str, lock_id: str, released_by: str
    ) -> ArtifactLock:
        result = await self._execute(
            "UPDATE design_artifact_locks SET released_at = :released_at, "
            "released_by = :released_by "
            "WHERE org_id = :org_id AND project_id = :project_id "
            "AND lock_id = :lock_id AND released_at IS NULL",
            {
                "released_at": _utcnow(),
                "released_by": released_by,
                "org_id": org_id,
                "project_id": project_id,
                "lock_id": lock_id,
            },
        )
        if getattr(result, "rowcount", 0) != 1:
            raise ArtifactVersionNotFoundError(
                f"active lock {lock_id!r} not found in project {project_id!r}"
            )
        for lock in await self.lock_history(org_id, project_id, lock_id=lock_id):
            return lock
        raise ArtifactVersionNotFoundError(f"lock {lock_id!r} vanished after release")

    async def lock_history(
        self, org_id: str, project_id: str, *, lock_id: str | None = None
    ) -> list[ArtifactLock]:
        clause = "" if lock_id is None else " AND lock_id = :lock_id"
        rows = await self._fetch_all(
            "SELECT * FROM design_artifact_locks "
            "WHERE org_id = :org_id AND project_id = :project_id" + clause,
            {"org_id": org_id, "project_id": project_id, "lock_id": lock_id},
        )
        return [_coerce_lock(row) for row in rows]

    async def active_locks(
        self, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[ArtifactLock]:
        clause = "" if lineage_id is None else " AND lineage_id = :lineage_id"
        rows = await self._fetch_all(
            "SELECT * FROM design_artifact_locks "
            "WHERE org_id = :org_id AND project_id = :project_id "
            "AND released_at IS NULL" + clause,
            {"org_id": org_id, "project_id": project_id, "lineage_id": lineage_id},
        )
        return [_coerce_lock(row) for row in rows]

    # ── guidance ──────────────────────────────────────────────────────────

    async def add_guidance(self, guidance: GuidanceRecord) -> GuidanceRecord:
        await self._execute(
            """
            INSERT INTO design_project_guidance
            (guidance_id, org_id, project_id, lineage_id, text, author, run_id,
             created_at, active, superseded_by)
            VALUES (:guidance_id, :org_id, :project_id, :lineage_id, :text,
                    :author, :run_id, :created_at, :active, NULL)
            """,
            {
                "guidance_id": guidance.guidance_id,
                "org_id": guidance.org_id,
                "project_id": guidance.project_id,
                "lineage_id": guidance.lineage_id,
                "text": guidance.text,
                "author": guidance.author,
                "run_id": guidance.run_id or None,
                "created_at": guidance.created_at,
                "active": guidance.active,
            },
        )
        return guidance

    async def supersede_guidance(
        self, org_id: str, project_id: str, guidance_id: str, by_guidance_id: str
    ) -> GuidanceRecord:
        result = await self._execute(
            "UPDATE design_project_guidance SET active = FALSE, "
            "superseded_by = :by_guidance_id "
            "WHERE org_id = :org_id AND project_id = :project_id "
            "AND guidance_id = :guidance_id AND active = TRUE",
            {
                "by_guidance_id": by_guidance_id,
                "org_id": org_id,
                "project_id": project_id,
                "guidance_id": guidance_id,
            },
        )
        if getattr(result, "rowcount", 0) != 1:
            raise ArtifactVersionNotFoundError(
                f"active guidance {guidance_id!r} not found in project {project_id!r}"
            )
        rows = await self.guidance_history(org_id, project_id)
        for record in rows:
            if record.guidance_id == guidance_id:
                return record
        raise ArtifactVersionNotFoundError(f"guidance {guidance_id!r} vanished after supersede")

    async def guidance_history(
        self, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[GuidanceRecord]:
        clause = "" if lineage_id is None else " AND (lineage_id = :lineage_id)"
        rows = await self._fetch_all(
            "SELECT * FROM design_project_guidance "
            "WHERE org_id = :org_id AND project_id = :project_id" + clause,
            {"org_id": org_id, "project_id": project_id, "lineage_id": lineage_id},
        )
        return [_coerce_guidance(row) for row in rows]

    async def active_guidance(
        self, org_id: str, project_id: str, lineage_id: str | None = None
    ) -> list[GuidanceRecord]:
        """Active guidance for a lineage: its own plus project-wide, oldest first."""
        clause = " AND (lineage_id IS NULL OR lineage_id = :lineage_id)" if lineage_id else ""
        params: dict[str, Any] = {"org_id": org_id, "project_id": project_id}
        if lineage_id:
            params["lineage_id"] = lineage_id
        rows = await self._fetch_all(
            "SELECT * FROM design_project_guidance "
            "WHERE org_id = :org_id AND project_id = :project_id AND active = TRUE"
            + clause
            + " ORDER BY created_at ASC, guidance_id ASC",
            params,
        )
        return [_coerce_guidance(row) for row in rows]

    # ── branch control ────────────────────────────────────────────────────

    async def set_control(self, control: BranchControl) -> BranchControl:
        existing = await self.get_control(control.org_id, control.project_id, control.lineage_id)
        if existing is None:
            await self._execute(
                """
                INSERT INTO design_branch_controls
                (control_id, org_id, project_id, lineage_id, mode, run_id,
                 updated_by, updated_at)
                VALUES (:control_id, :org_id, :project_id, :lineage_id, :mode,
                        :run_id, :updated_by, :updated_at)
                """,
                {
                    "control_id": str(uuid.uuid4()),
                    "org_id": control.org_id,
                    "project_id": control.project_id,
                    "lineage_id": control.lineage_id,
                    "mode": control.mode.value,
                    "run_id": control.run_id,
                    "updated_by": control.updated_by,
                    "updated_at": control.updated_at,
                },
            )
        else:
            await self._execute(
                """
                UPDATE design_branch_controls
                SET mode = :mode, run_id = :run_id, updated_by = :updated_by,
                    updated_at = :updated_at
                WHERE org_id = :org_id AND project_id = :project_id
                  AND lineage_id = :lineage_id
                """,
                {
                    "mode": control.mode.value,
                    "run_id": control.run_id,
                    "updated_by": control.updated_by,
                    "updated_at": control.updated_at,
                    "org_id": control.org_id,
                    "project_id": control.project_id,
                    "lineage_id": control.lineage_id,
                },
            )
        return control

    async def get_control(
        self, org_id: str, project_id: str, lineage_id: str
    ) -> BranchControl | None:
        row = await self._fetch_one(
            "SELECT * FROM design_branch_controls "
            "WHERE org_id = :org_id AND project_id = :project_id "
            "AND lineage_id = :lineage_id",
            {"org_id": org_id, "project_id": project_id, "lineage_id": lineage_id},
        )
        return _coerce_control(row) if row is not None else None

    # ── session plumbing ──────────────────────────────────────────────────

    async def _execute(self, statement: str, params: dict[str, Any]) -> Any:
        async with self.session_factory() as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def _fetch_one(self, statement: str, params: dict[str, Any]) -> Any:
        async with self.session_factory() as session:
            result = await session.execute(text(statement), params)
            return result.fetchone()

    async def _fetch_all(self, statement: str, params: dict[str, Any]) -> list[Any]:
        async with self.session_factory() as session:
            result = await session.execute(text(statement), params)
            return list(result.fetchall())
