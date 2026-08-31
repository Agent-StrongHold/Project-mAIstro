"""PostgreSQL persistence for DesignProject and DesignOutput artifacts.

Uses raw SQL via sqlalchemy.text() — same pattern as canvas/store.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from maistro.observability.correlation import observed_provenance
from maistro_design.trust import TrustTier
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignOutput,
    DesignProject,
    DesignProjectNotFoundError,
    DesignScopeError,
    DiscoveryResult,
    OutputFormat,
)


def _row_dict(row: Any) -> dict[str, Any]:
    """Materialize mapping-compatible database rows without assuming ``dict(row)`` works."""
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return dict(mapping)


def _coerce_design_project(row: Any, outputs: list[DesignOutput] | None = None) -> DesignProject:
    """Coerce database row to DesignProject dataclass."""
    d = _row_dict(row)
    discovery_data = d.get("discovery_json")
    discovery: DiscoveryResult | None = None
    if discovery_data:
        if isinstance(discovery_data, str):
            discovery_data = json.loads(discovery_data)
        discovery = DiscoveryResult(
            skill_slug=discovery_data.get("skill_slug", ""),
            responses=discovery_data.get("responses", {}),
            design_system_slug=discovery_data.get("design_system_slug", "default"),
            trust_tier=TrustTier(discovery_data.get("trust_tier", "t3")),
            created_at=datetime.fromisoformat(discovery_data["created_at"])
            if "created_at" in discovery_data
            else datetime.now(UTC),
        )

    return DesignProject(
        id=str(d["id"]),
        name=d["name"],
        skill_slug=d["skill_slug"],
        design_system_slug=d["design_system_slug"],
        org_id=d["org_id"],
        team_id=d.get("team_id"),
        trust_tier=TrustTier(d.get("trust_tier", "t3")),
        canvas_id=d.get("canvas_id"),
        outputs=outputs or [],
        discovery=discovery,
        created_at=d.get("created_at", datetime.now(UTC)),
        updated_at=d.get("updated_at", datetime.now(UTC)),
    )


def _coerce_design_output(row: Any) -> DesignOutput:
    """Coerce database row to DesignOutput dataclass."""
    d = _row_dict(row)
    metadata = d.get("metadata_json") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    return DesignOutput(
        root=ArtifactNode(
            key="root",
            kind=ArtifactKind.FILE,
            format=OutputFormat(d["format"]),
            value=d["content"],
        ),
        url=d.get("url"),
        trust_tier=TrustTier(d.get("trust_tier", "t3")),
        metadata=metadata,
        run_id=d.get("run_id") or "",
        node_run_id=d.get("node_run_id") or "",
        attempt_id=d.get("attempt_id") or "",
    )


class PgDesignProjectStore:
    """PostgreSQL implementation of DesignProjectStore protocol.

    Scope is enforced here because here is where it is known. `org` is a soft
    axis (ADR-068): no table resolves it to an owner, so the database cannot
    answer "may this caller see this project" and the store must. Migration 003
    looked like it did — it declared a foreign key to an `orgs` table nothing
    populates — which is why the real gap went unnoticed while the fake one
    blocked every write (#326, ADR-083026-cdcb).
    """

    def __init__(self, session_factory: Any) -> None:
        """Initialize with AsyncSession factory."""
        self.session_factory = session_factory

    async def create(self, project: DesignProject) -> DesignProject:
        """Create a new design project and persist its outputs.

        Refuses a project that names no scope. The `CHECK` added in migration
        024 refuses it too; this raises the domain error rather than letting an
        `IntegrityError` cross the service boundary unclassified.
        """
        if not project.org_id:
            raise DesignScopeError("a design project must name the scope it belongs to")
        project_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        discovery_json: str | None = None
        if project.discovery:
            discovery_json = json.dumps(
                {
                    "skill_slug": project.discovery.skill_slug,
                    "responses": project.discovery.responses,
                    "design_system_slug": project.discovery.design_system_slug,
                    "trust_tier": project.discovery.trust_tier.value,
                    "created_at": project.discovery.created_at.isoformat(),
                }
            )

        async with self.session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO design_projects
                    (id, name, skill_slug, design_system_slug, org_id, team_id,
                     trust_tier, canvas_id, discovery_json, created_at, updated_at)
                    VALUES (:id, :name, :skill_slug, :design_system_slug, :org_id,
                            :team_id, :trust_tier, :canvas_id, :discovery_json::jsonb,
                            :created_at, :updated_at)
                """),
                {
                    "id": project_id,
                    "name": project.name,
                    "skill_slug": project.skill_slug,
                    "design_system_slug": project.design_system_slug,
                    "org_id": project.org_id,
                    "team_id": project.team_id,
                    "trust_tier": project.trust_tier.value,
                    "canvas_id": project.canvas_id,
                    "discovery_json": discovery_json,
                    "created_at": now,
                    "updated_at": now,
                },
            )

            for output in project.outputs:
                metadata_json = json.dumps(output.metadata) if output.metadata else None
                # Per output, not per project: outputs of one project can be
                # produced by different Attempts -- a refinement pass is a
                # second Attempt over the same project (#709).
                provenance = observed_provenance(
                    run_id=output.run_id,
                    node_run_id=output.node_run_id,
                    attempt_id=output.attempt_id,
                )
                await session.execute(
                    text("""
                        INSERT INTO design_outputs
                        (project_id, format, content, url, trust_tier, metadata_json, created_at,
                         run_id, node_run_id, attempt_id)
                        VALUES (:project_id, :format, :content, :url, :trust_tier, :metadata_json::jsonb, :created_at,
                                :run_id, :node_run_id, :attempt_id)
                    """),
                    {
                        "project_id": project_id,
                        "format": output.format.value if output.format is not None else None,
                        "content": output.content,
                        "url": output.url,
                        "trust_tier": output.trust_tier.value,
                        "metadata_json": metadata_json,
                        "created_at": now,
                        # NULL rather than "": an artifact produced outside any
                        # execution names no producer, which is different from
                        # naming one whose id is empty (#709).
                        "run_id": provenance.run_id or None,
                        "node_run_id": provenance.node_run_id or None,
                        "attempt_id": provenance.attempt_id or None,
                    },
                )

            await session.commit()

        persisted_project = project
        persisted_project.id = project_id
        persisted_project.created_at = now
        persisted_project.updated_at = now
        return persisted_project

    async def get(self, project_id: str, *, org_id: str) -> DesignProject | None:
        """Retrieve a design project by ID within `org_id`, including its outputs.

        A project in another scope reads as absent rather than forbidden. Whether
        one exists elsewhere is itself scoped information, and a 403 would answer
        the question a 404 refuses to.
        """
        if not org_id:
            raise DesignScopeError("a design project is read within a scope")
        async with self.session_factory() as session:
            row = await session.execute(
                text("SELECT * FROM design_projects WHERE id = :id AND org_id = :org_id"),
                {"id": project_id, "org_id": org_id},
            )
            project_row = row.fetchone()
            if not project_row:
                return None

            output_rows = await session.execute(
                text("SELECT * FROM design_outputs WHERE project_id = :project_id"),
                {"project_id": project_id},
            )
            outputs = [_coerce_design_output(row) for row in output_rows.fetchall()]

            return _coerce_design_project(project_row, outputs)

    async def list_by_skill(self, skill_slug: str, org_id: str) -> list[DesignProject]:
        """List all projects for a skill in an org."""
        if not org_id:
            raise DesignScopeError("design projects are listed within a scope")
        async with self.session_factory() as session:
            rows = await session.execute(
                text("""
                    SELECT * FROM design_projects
                    WHERE skill_slug = :skill_slug AND org_id = :org_id
                    ORDER BY created_at DESC
                """),
                {"skill_slug": skill_slug, "org_id": org_id},
            )
            projects = []
            for project_row in rows.fetchall():
                project_id = str(_row_dict(project_row)["id"])
                output_rows = await session.execute(
                    text("SELECT * FROM design_outputs WHERE project_id = :project_id"),
                    {"project_id": project_id},
                )
                outputs = [_coerce_design_output(row) for row in output_rows.fetchall()]
                projects.append(_coerce_design_project(project_row, outputs))

            return projects

    async def list_by_org(self, org_id: str) -> list[DesignProject]:
        """List all projects in an org."""
        if not org_id:
            raise DesignScopeError("design projects are listed within a scope")
        async with self.session_factory() as session:
            rows = await session.execute(
                text("""
                    SELECT * FROM design_projects
                    WHERE org_id = :org_id
                    ORDER BY created_at DESC
                """),
                {"org_id": org_id},
            )
            projects = []
            for project_row in rows.fetchall():
                project_id = str(_row_dict(project_row)["id"])
                output_rows = await session.execute(
                    text("SELECT * FROM design_outputs WHERE project_id = :project_id"),
                    {"project_id": project_id},
                )
                outputs = [_coerce_design_output(row) for row in output_rows.fetchall()]
                projects.append(_coerce_design_project(project_row, outputs))

            return projects

    async def update(self, project: DesignProject, *, org_id: str) -> DesignProject:
        """Update a design project within `org_id`, the **caller's** scope.

        `org_id` is a separate argument and not `project.org_id`, which is the
        whole point: `project` is a mutable object the caller supplies, so
        taking the scope from it means the predicate is `id = <what they sent>
        AND org_id = <what they sent>` — a caller who knows a victim's project
        id and org id passes it, and the check enforces nothing (Codex, #326).
        `get` and `delete` already took the scope separately; this did not.

        A payload whose own `org_id` disagrees is refused rather than silently
        rescoped: moving a project between scopes is not an edit.

        Raises `DesignProjectNotFoundError` when nothing matched — the row is in
        another scope, or gone. Both are "not yours to edit", and reporting a
        silent success for either is what let a scoped surface behave as an
        unscoped one.
        """
        if not org_id:
            raise DesignScopeError("a design project is updated within a scope")
        if project.org_id and project.org_id != org_id:
            raise DesignScopeError(
                f"design project {project.id} carries scope {project.org_id!r}; "
                "an update cannot move it to another"
            )
        now = datetime.now(UTC)

        discovery_json: str | None = None
        if project.discovery:
            discovery_json = json.dumps(
                {
                    "skill_slug": project.discovery.skill_slug,
                    "responses": project.discovery.responses,
                    "design_system_slug": project.discovery.design_system_slug,
                    "trust_tier": project.discovery.trust_tier.value,
                    "created_at": project.discovery.created_at.isoformat(),
                }
            )

        async with self.session_factory() as session:
            result = await session.execute(
                text("""
                    UPDATE design_projects
                    SET name = :name, trust_tier = :trust_tier,
                        canvas_id = :canvas_id, discovery_json = :discovery_json::jsonb,
                        updated_at = :updated_at
                    WHERE id = :id AND org_id = :org_id
                """),
                {
                    "id": project.id,
                    "org_id": org_id,
                    "name": project.name,
                    "trust_tier": project.trust_tier.value,
                    "canvas_id": project.canvas_id,
                    "discovery_json": discovery_json,
                    "updated_at": now,
                },
            )
            if result.rowcount == 0:
                raise DesignProjectNotFoundError(
                    f"design project {project.id} is not in scope {org_id!r}"
                )
            await session.commit()

        project.updated_at = now
        return project

    async def delete(self, project_id: str, *, org_id: str) -> None:
        """Delete a design project within `org_id` (cascades to outputs)."""
        if not org_id:
            raise DesignScopeError("a design project is deleted within a scope")
        async with self.session_factory() as session:
            await session.execute(
                text("DELETE FROM design_projects WHERE id = :id AND org_id = :org_id"),
                {"id": project_id, "org_id": org_id},
            )
            await session.commit()
