"""PostgreSQL persistence for versioned CreativeBriefs (#774).

Same raw-SQL-over-``sqlalchemy.text()`` pattern as ``stores.py``. The store is
append-only: CreativeBriefs are immutable by version, so there is an insert
and reads, and no update — an update would rewrite the exact provenance a
Run/artifact must be able to cite. Scope is enforced here because here is
where it is known: every operation takes the caller's ``workspace_id``
keyword-only, and a write additionally verifies the named Project is
registered to that Workspace in the canonical spine, which is what makes a
cross-Workspace CreativeBrief structurally impossible rather than merely
discouraged.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from maistro_design.brief import (
    BriefVersionConflictError,
    CreativeBrief,
    CrossWorkspaceReferenceError,
)
from maistro_design.types import DesignScopeError


def _row_dict(row: Any) -> dict[str, Any]:
    """Materialize mapping-compatible database rows without assuming ``dict(row)`` works."""
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return dict(mapping)


_INSERT_SQL = text("""
    INSERT INTO design_creative_briefs
    (brief_id, lineage_id, version, supersedes_brief_id, workspace_id, project_id,
     goal_id, goal_revision, payload, created_by, created_at)
    VALUES (:brief_id, :lineage_id, :version, :supersedes_brief_id, :workspace_id,
            :project_id, :goal_id, :goal_revision, CAST(:payload AS jsonb),
            :created_by, :created_at)
""")

_SELECT_COLUMNS = """
    brief_id, lineage_id, version, supersedes_brief_id, workspace_id, project_id,
    goal_id, goal_revision, payload, created_by, created_at
"""

# Read statements are module-level constants: the table and column list are
# literals, the caller-supplied values are bound parameters (:name), and no
# user input ever reaches the SQL text. Keeping the statements here (instead of
# formatting them per call) is also what keeps them plain strings for the
# security scanner's no-dynamic-SQL rule, matching ``stores.py``.
_SELECT_FROM = "SELECT " + _SELECT_COLUMNS + " FROM design_creative_briefs "
_GET_SQL = text(_SELECT_FROM + "WHERE brief_id = :brief_id AND workspace_id = :workspace_id")
_LATEST_SQL = text(
    _SELECT_FROM + "WHERE lineage_id = :lineage_id AND workspace_id = :workspace_id "
    "ORDER BY version DESC LIMIT 1"
)
_VERSIONS_SQL = text(
    _SELECT_FROM + "WHERE lineage_id = :lineage_id AND workspace_id = :workspace_id "
    "ORDER BY version ASC"
)


def _coerce_brief(row: Any) -> CreativeBrief:
    """Materialize one database row back into its immutable CreativeBrief."""
    d = _row_dict(row)
    payload = d["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return CreativeBrief.model_validate(payload)


class PgCreativeBriefStore:
    """PostgreSQL implementation of the CreativeBrief persistence contract."""

    def __init__(self, session_factory: Any) -> None:
        """Initialize with an AsyncSession factory."""
        self.session_factory = session_factory

    async def create(self, brief: CreativeBrief) -> CreativeBrief:
        """Persist one brief version immutably.

        Refuses a brief that names no Workspace scope, a Project that is not a
        registered canonical Project, and a Project registered to a different
        Workspace than the brief claims — the last is the cross-Workspace
        reference the contract rejects structurally. A concurrent writer that
        minted the same ``(lineage_id, version)`` first loses the unique
        constraint and surfaces as :class:`BriefVersionConflictError`; version
        identity is first-writer-wins, never last-writer-overwrites.
        """
        if not brief.workspace_id:
            raise DesignScopeError("a creative brief is written within a Workspace scope")

        async with self.session_factory() as session:
            project_row = (
                await session.execute(
                    text(
                        "SELECT workspace_id FROM canonical_projects WHERE project_id = :project_id"
                    ),
                    {"project_id": brief.project_id},
                )
            ).fetchone()
            if project_row is None:
                msg = (
                    f"creative brief references project {brief.project_id!r}, "
                    "which is not a registered canonical Project"
                )
                raise CrossWorkspaceReferenceError(msg)
            registered_workspace = str(_row_dict(project_row)["workspace_id"])
            if registered_workspace != brief.workspace_id:
                msg = (
                    f"creative brief claims workspace {brief.workspace_id!r} but project "
                    f"{brief.project_id!r} is registered to workspace "
                    f"{registered_workspace!r}"
                )
                raise CrossWorkspaceReferenceError(msg)

            payload = json.dumps(brief.model_dump(mode="json"))
            try:
                await session.execute(
                    _INSERT_SQL,
                    {
                        "brief_id": brief.brief_id,
                        "lineage_id": brief.lineage_id,
                        "version": brief.version,
                        "supersedes_brief_id": brief.supersedes_brief_id,
                        "workspace_id": brief.workspace_id,
                        "project_id": brief.project_id,
                        "goal_id": brief.goal_id,
                        "goal_revision": brief.goal_revision,
                        "payload": payload,
                        "created_by": brief.created_by,
                        "created_at": brief.created_at,
                    },
                )
            except IntegrityError as exc:
                lowered = str(exc).lower()
                if (
                    "uq_design_creative_briefs_lineage_version" in lowered
                    or "unique constraint" in lowered
                ):
                    msg = (
                        f"creative brief lineage {brief.lineage_id!r} already has "
                        f"version {brief.version}"
                    )
                    raise BriefVersionConflictError(msg) from exc
                raise
            await session.commit()
        return brief

    async def get(self, brief_id: str, *, workspace_id: str) -> CreativeBrief | None:
        """Read one brief version within ``workspace_id``.

        A brief in another Workspace reads as absent rather than forbidden:
        whether one exists elsewhere is itself scoped information.
        """
        if not workspace_id:
            raise DesignScopeError("a creative brief is read within a Workspace scope")
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    _GET_SQL,
                    {"brief_id": brief_id, "workspace_id": workspace_id},
                )
            ).fetchone()
            return _coerce_brief(row) if row is not None else None

    async def latest(self, lineage_id: str, *, workspace_id: str) -> CreativeBrief | None:
        """Read the newest committed version of a lineage within the Workspace.

        Newly eligible work consumes this version (#774 redirect semantics);
        dependency-aware invalidation is #775's and locks are #780's.
        """
        if not workspace_id:
            raise DesignScopeError("a creative brief is read within a Workspace scope")
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    _LATEST_SQL,
                    {"lineage_id": lineage_id, "workspace_id": workspace_id},
                )
            ).fetchone()
            return _coerce_brief(row) if row is not None else None

    async def list_versions(self, lineage_id: str, *, workspace_id: str) -> list[CreativeBrief]:
        """Read every committed version of a lineage, oldest first.

        This is the provenance surface: historical artifacts resolve the exact
        version they consumed here, and a redirect never erases or rewrites
        what they read.
        """
        if not workspace_id:
            raise DesignScopeError("a creative brief is read within a Workspace scope")
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    _VERSIONS_SQL,
                    {"lineage_id": lineage_id, "workspace_id": workspace_id},
                )
            ).fetchall()
            return [_coerce_brief(row) for row in rows]
