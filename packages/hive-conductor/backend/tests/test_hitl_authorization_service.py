"""Service-level refusal semantics of the HITL Workspace/Project door (#1110).

The route tests prove the door refuses over HTTP; these prove the authorization
service itself resolves every refusal from canonical state. Each test names the
canonical condition it denies, so removing a check in
`services/hitl_authorization.py` fails the matching test here rather than being
masked by a route-level stub.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
from services.hitl_authorization import (
    HITL_ANSWER,
    HITL_CANCEL,
    HITL_INSPECT,
    HitlAuthorizationDenied,
    authorize_project,
    authorized_project_ids,
)
from services.workspace_authority import create_workspace, set_member

from maistro.projects.scope import Project, ProjectMembership, ProjectNotFound


class _FakeProjectStore:
    """A Project store whose every refusal shape is deterministic.

    The in-memory canonical store returns ``None`` for a missing Project and
    never returns a membership row from another Workspace, so the two store
    failure shapes the service must translate into refusals -- a raising
    ``get`` and a foreign-Workspace membership row -- are manufactured here
    rather than left untested.
    """

    def __init__(
        self,
        *,
        project: Project | None = None,
        memberships: Iterable[ProjectMembership] = (),
        raise_on_get: bool = False,
        raise_on_root: bool = False,
    ) -> None:
        self._project = project
        self._memberships = list(memberships)
        self._raise_on_get = raise_on_get
        self._raise_on_root = raise_on_root

    async def get(self, project_id: str) -> Project | None:
        if self._raise_on_get:
            raise ProjectNotFound(project_id)
        if self._project is None or self._project.project_id != project_id:
            return None
        return self._project

    async def lineage(self, project_id: str) -> list[Project]:
        if self._project is None or self._project.project_id != project_id:
            return []
        return [self._project]

    async def memberships_for(
        self, project_id: str, *, principal_id: str | None = None
    ) -> list[ProjectMembership]:
        if principal_id is None:
            return list(self._memberships)
        return [
            membership
            for membership in self._memberships
            if membership.principal_id == principal_id
        ]

    async def root_for_workspace(self, workspace_id: str) -> Project:
        if self._raise_on_root or self._project is None:
            raise KeyError(workspace_id)
        return self._project

    async def list_children(self, project_id: str) -> list[Project]:
        return []


class _StubContainer:
    def __init__(self, project_store: Any) -> None:
        self.project_scope_store = project_store


class _StubAgentPort:
    def __init__(self, container: _StubContainer) -> None:
        self.container = container


class _StubEngine:
    def __init__(self, project_store: Any) -> None:
        self._agent_port = _StubAgentPort(_StubContainer(project_store))


def _bind_engine_project_store(monkeypatch: pytest.MonkeyPatch, store: Any | None) -> None:
    """Serve ``store`` as the embedded Container's project store."""
    import services.engine as engine

    if store is None:
        monkeypatch.setattr(
            engine, "get_engine", lambda: pytest.fail("engine must not be consulted")
        )
        return
    monkeypatch.setattr(engine, "get_engine", lambda: _StubEngine(store))


async def _new_workspace(member_user: str | None = None) -> Any:
    workspace = await create_workspace(
        creator_user_id="hitl-auth-owner",
        name=f"HITL auth service {member_user or 'owner'}",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    if member_user is not None:
        await set_member(workspace.id, user_id=member_user, role="editor")
    return workspace


async def test_unknown_permission_is_rejected_before_any_scope_read() -> None:
    """A permission outside the HITL vocabulary is a caller bug, not a denial."""
    with pytest.raises(ValueError, match="unknown HITL permission"):
        await authorize_project(
            principal_id="hitl-auth-owner",
            workspace_id="ws-never-read",
            project_id="project-never-read",
            permission="hitl.everything",
        )


async def test_a_principal_outside_the_workspace_is_denied() -> None:
    """Membership in the Run's Workspace is the entry condition, not a detail."""
    workspace = await _new_workspace()

    with pytest.raises(HitlAuthorizationDenied, match="canonical HITL scope"):
        await authorize_project(
            principal_id="stranger",
            workspace_id=workspace.id,
            project_id="project-unknown",
            permission=HITL_INSPECT,
        )


async def test_a_project_from_another_workspace_is_denied() -> None:
    """Project and Run must share a Workspace before any grant is read."""
    from services.workspace_authority import canonical_store_for_tests

    member_workspace = await _new_workspace()
    other_workspace = await _new_workspace()
    projects = canonical_store_for_tests().project_store
    other_root = await projects.root_for_workspace(other_workspace.id)

    with pytest.raises(HitlAuthorizationDenied, match="outside the Run Workspace"):
        await authorize_project(
            principal_id="hitl-auth-owner",
            workspace_id=member_workspace.id,
            project_id=other_root.project_id,
            permission=HITL_ANSWER,
        )


async def test_a_store_that_raises_for_a_missing_project_is_denied(monkeypatch) -> None:
    """A raising store read becomes the same refusal as an absent Project."""
    workspace = await _new_workspace()
    project = Project(
        project_id="project-raises",
        workspace_id=workspace.id,
        name="Raises",
        parent_project_id="parent-raises",
    )
    _bind_engine_project_store(monkeypatch, _FakeProjectStore(project=project, raise_on_get=True))

    with pytest.raises(HitlAuthorizationDenied, match="not a canonical scope"):
        await authorize_project(
            principal_id="hitl-auth-owner",
            workspace_id=workspace.id,
            project_id="project-raises",
            permission=HITL_CANCEL,
        )


async def test_a_membership_row_from_a_foreign_workspace_is_ignored(monkeypatch) -> None:
    """Only this Workspace's membership rows can carry Project authority.

    A store returning a row stamped with another Workspace must not grant
    anything here: the row is filtered before the resolver ever sees it, so
    settlement authority cannot arrive from outside the Run's Workspace.
    The principal is a Workspace editor, whose own role settles nothing, so
    the foreign row is the only thing that could authorize this call.
    """
    workspace = await _new_workspace(member_user="hitl-auth-editor")
    project = Project(
        project_id="project-foreign-row",
        workspace_id=workspace.id,
        name="Foreign row",
        parent_project_id="parent-foreign-row",
    )
    foreign_row = ProjectMembership(
        workspace_id="ws-foreign",
        project_id=project.project_id,
        principal_id="hitl-auth-editor",
        grants={HITL_ANSWER, HITL_CANCEL},
    )
    _bind_engine_project_store(
        monkeypatch, _FakeProjectStore(project=project, memberships=[foreign_row])
    )

    with pytest.raises(HitlAuthorizationDenied):
        await authorize_project(
            principal_id="hitl-auth-editor",
            workspace_id=workspace.id,
            project_id=project.project_id,
            permission=HITL_ANSWER,
        )


async def test_an_authorized_explicit_project_is_returned_as_the_scope() -> None:
    """An explicit authorized `project_id` selects exactly that Project."""
    from services.workspace_authority import canonical_store_for_tests

    workspace = await _new_workspace()
    projects = canonical_store_for_tests().project_store
    root = await projects.root_for_workspace(workspace.id)

    assert await authorized_project_ids(
        principal_id="hitl-auth-owner",
        workspace_id=workspace.id,
        project_id=root.project_id,
        permission=HITL_INSPECT,
    ) == [root.project_id]


async def test_a_denied_explicit_project_yields_no_scope_to_query() -> None:
    """A denied `project_id` becomes no Projects, never a store query."""
    from services.workspace_authority import canonical_store_for_tests

    workspace = await _new_workspace(member_user="hitl-auth-editor")
    projects = canonical_store_for_tests().project_store
    root = await projects.root_for_workspace(workspace.id)

    # An editor holds no Project grant, and settling requires owner-or-grant.
    assert (
        await authorized_project_ids(
            principal_id="hitl-auth-editor",
            workspace_id=workspace.id,
            project_id=root.project_id,
            permission=HITL_CANCEL,
        )
        == []
    )


async def test_a_workspace_without_a_project_root_yields_no_scope(monkeypatch) -> None:
    """A Workspace whose Project tree cannot be resolved inspects nothing."""
    workspace = await _new_workspace()
    _bind_engine_project_store(monkeypatch, _FakeProjectStore(raise_on_root=True))

    assert (
        await authorized_project_ids(
            principal_id="hitl-auth-owner",
            workspace_id=workspace.id,
            permission=HITL_INSPECT,
        )
        == []
    )


async def test_a_missing_project_store_denies_rather_than_defaulting_open(monkeypatch) -> None:
    """No canonical Project store means the capability is unavailable."""
    import services.engine as engine
    import services.workspace_authority as workspace_authority

    workspace = await _new_workspace()
    real_store = workspace_authority.canonical_store_for_tests()
    monkeypatch.setattr(engine, "get_engine", lambda: (_ for _ in ()).throw(RuntimeError("down")))

    class _NoProjectStore:
        """The real Workspace authority, with its Project pairing removed."""

        project_store = None

        async def get_membership(self, workspace_id: str, *, user_id: str) -> Any:
            return await real_store.get_membership(workspace_id, user_id=user_id)

    monkeypatch.setattr(
        workspace_authority,
        "canonical_store_for_tests",
        lambda: _NoProjectStore(),
    )

    with pytest.raises(HitlAuthorizationDenied, match="canonical HITL scope is unavailable"):
        await authorize_project(
            principal_id="hitl-auth-owner",
            workspace_id=workspace.id,
            project_id="project-any",
            permission=HITL_INSPECT,
        )
    assert (
        await authorized_project_ids(
            principal_id="hitl-auth-owner",
            workspace_id=workspace.id,
            permission=HITL_INSPECT,
        )
        == []
    )
