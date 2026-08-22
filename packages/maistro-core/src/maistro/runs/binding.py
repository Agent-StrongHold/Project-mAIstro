"""The Workspace/Project that directly-submitted work is filed in (#41, #131).

Extracted from `maistro.tasks.admission` when chat became a second entry point
needing the same three lines. The rule it encodes is the one worth not
duplicating: the Project a submission lands in is a *binding* configured at
wiring time, never something inferred from a field on the request. Inferring it
would file work in the wrong tenant's Project, which is the failure the scope
tree exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.projects.scope_store import ProjectScopeStore


class ProjectBinding:
    """One Workspace, and the Project inside it that admitted work is filed in."""

    def __init__(
        self,
        *,
        workspace_id: str,
        project_id: str | None = None,
        project_store: ProjectScopeStore | None = None,
    ) -> None:
        if not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        if project_id is None and project_store is None:
            raise ValueError(
                "a Project binding needs either an explicit project_id or a project_store "
                "to resolve the Workspace's Root Project"
            )
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._projects = project_store

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    async def project_id(self) -> str:
        """The bound Project, resolving the Workspace's Root Project once if needed."""
        if self._project_id is not None:
            return self._project_id
        if self._projects is None:  # pragma: no cover - guarded in __init__
            raise RuntimeError("Project binding has no project_store to resolve a Project")
        root = await self._projects.root_for_workspace(self._workspace_id)
        # Cached: a Workspace's Root Project is created once and never moves, so
        # re-resolving it on every submission is a store round-trip for an answer
        # that cannot have changed.
        self._project_id = root.project_id
        return self._project_id


__all__ = ["ProjectBinding"]
