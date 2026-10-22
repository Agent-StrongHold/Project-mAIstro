"""Admission identity: authenticated vs acting principal binding (#1152).

Reads are covered by the Workspace-membership seam (tests/runs/
test_store_boundary.py and the cross-backend conformance suite in
tests/workspaces/test_store_boundary_scope_conformance.py). This module pins
the admission half: accounting attribution derives from the authenticated or
delegated acting principal resolved at admission, and a delegated execution
records its initiating and acting identities explicitly.
"""

from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.access import RunAuthorization
from maistro.runs.store import InMemoryRunStore
from maistro.security.sentinel.authz_types import Principal
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


async def _project(projects: InMemoryProjectScopeStore, workspace_id: str, name: str):
    try:
        root = await projects.root_for_workspace(workspace_id)
    except KeyError:
        root = await projects.create_root(workspace_id)
    return await projects.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name=name,
    )


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="inspection",
        nodes=[Node(node_id="node", node_type="agent")],
    )


@pytest.mark.asyncio
async def test_admission_binds_accounting_to_authenticated_and_acting_principals() -> None:
    projects = InMemoryProjectScopeStore()
    project = await _project(projects, "workspace-a", "first")
    store = InMemoryRunStore(project_store=projects)
    authorization = RunAuthorization(
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        authenticated_principal=Principal(id="operator", kind="human"),
        acting_principal=Principal(id="agent", kind="agent", owner="operator"),
    )

    run = await store.create_run(
        _graph(project.workspace_id, project.project_id),
        authorization=authorization,
        actor_principal_id="agent",
        provenance={"user_id": "forged-metadata"},
    )

    assert run.initiating_principal_id == "operator"
    assert run.acting_principal_id == "agent"
    assert run.actor_principal_id == "agent"
    assert run.accounting_principal_id == "agent"
    # Provenance is a record, never an identity source: the forged metadata
    # stays readable as provenance but cannot become the accounting identity.
    assert run.provenance["user_id"] == "forged-metadata"
    with pytest.raises(ValueError, match="does not match"):
        await store.create_run(
            _graph(project.workspace_id, project.project_id),
            authorization=authorization,
            actor_principal_id="forged",
        )


@pytest.mark.asyncio
async def test_delegation_requires_owned_acting_principal() -> None:
    projects = InMemoryProjectScopeStore()
    project = await _project(projects, "workspace-a", "first")
    store = InMemoryRunStore(project_store=projects)

    with pytest.raises(ValueError, match="authenticated or owned"):
        await store.create_run(
            _graph(project.workspace_id, project.project_id),
            authorization=RunAuthorization(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                authenticated_principal=Principal(id="operator", kind="human"),
                acting_principal=Principal(id="other", kind="human"),
            ),
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )


@pytest.mark.asyncio
async def test_delegated_authorization_must_match_the_graph_scope() -> None:
    """A delegation minted in one Workspace cannot admit work in another."""
    projects = InMemoryProjectScopeStore()
    first = await _project(projects, "workspace-a", "first")
    second = await _project(projects, "workspace-b", "second")
    store = InMemoryRunStore(project_store=projects)

    with pytest.raises(ValueError, match="scope must match"):
        await store.create_run(
            _graph(second.workspace_id, second.project_id),
            authorization=RunAuthorization(
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                authenticated_principal=Principal(id="operator", kind="human"),
            ),
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )


@pytest.mark.asyncio
async def test_two_workspaces_delegate_without_cross_visibility() -> None:
    """Two principals in two Workspaces: each delegation stays in its scope."""
    projects = InMemoryProjectScopeStore()
    alpha = await _project(projects, "workspace-alpha", "alpha-work")
    beta = await _project(projects, "workspace-beta", "beta-work")
    store = InMemoryRunStore(project_store=projects)

    run_alpha = await store.create_run(
        _graph(alpha.workspace_id, alpha.project_id),
        authorization=RunAuthorization(
            workspace_id=alpha.workspace_id,
            project_id=alpha.project_id,
            authenticated_principal=Principal(id="op-alpha", kind="human"),
            acting_principal=Principal(id="agent-alpha", kind="agent", owner="op-alpha"),
        ),
    )
    run_beta = await store.create_run(
        _graph(beta.workspace_id, beta.project_id),
        authorization=RunAuthorization(
            workspace_id=beta.workspace_id,
            project_id=beta.project_id,
            authenticated_principal=Principal(id="op-beta", kind="human"),
            acting_principal=Principal(id="agent-beta", kind="agent", owner="op-beta"),
        ),
    )

    assert run_alpha.initiating_principal_id == "op-alpha"
    assert run_alpha.acting_principal_id == "agent-alpha"
    assert run_alpha.accounting_principal_id == "agent-alpha"
    assert run_beta.initiating_principal_id == "op-beta"
    assert run_beta.acting_principal_id == "agent-beta"
    # No Workspace's admission can project the other's identities.
    assert run_alpha.acting_principal_id != run_beta.acting_principal_id
    assert run_alpha.initiating_principal_id != run_beta.initiating_principal_id
