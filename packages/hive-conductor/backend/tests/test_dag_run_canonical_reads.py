"""Canonical-spine-configured reads over the DAG-Run inspection door.

`services.dag_run_inspection` has two execution shapes: standalone (no
canonical spine configured — the compatibility projection path) and
spine-configured, where canonical Run state is the only lifecycle and
existence truth. The standalone half and the *refusals* of the configured
half are pinned in test_dag_run_scope.py; this file pins the configured
half's serving side, which the #1036 canonical Run inspection substrate
shipped: the list endpoint's canonical listing, the detail record built from
a projection row overlaid with canonical lifecycle, the by-id authorization
answer, and the batch companion — plus the configured-spine refusal for a
canonical id the store never saw.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_AUTHED_USER_ID = "user"  # the session conftest seeds


async def _seed_run_async(run_id: str, *, workspace_id: str = "", user_id: str = "") -> None:
    """Put one run row into the projection, carrying scope (scope-suite pattern)."""
    from services.dag_run_store import get_dag_run_store

    store = get_dag_run_store()
    await store.start_run(run_id=run_id, user_id=user_id, workspace_id=workspace_id)


async def test_configured_spine_serves_reads_from_canonical_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a spine configured, every read answers from canonical Run truth.

    A Run inside the caller's canonical Workspace is listed, inspectable, and
    batch-visible through the canonical store, its projection row overlaid
    with canonical lifecycle; a canonical id the store never saw is refused
    even though the caller's universe is non-empty.
    """
    import services.engine as engine_mod
    from services import dag_run_inspection as inspection

    from maistro.graph.definitions import Graph, Node
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("caller-workspace")
    runs = InMemoryRunStore(project_store=projects)
    run = await runs.create_run(
        Graph(
            graph_id="mine-graph",
            workspace_id="caller-workspace",
            project_id=root.project_id,
            name="My graph",
            nodes=[Node(node_id="only", node_type="probe", name="Only")],
        )
    )
    # The projection row exists (keyed by the canonical Run id) and carries
    # the caller's scope — the shape the shipped write path produces.
    await _seed_run_async(run.run_id, workspace_id="caller-workspace")

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_store=runs),
    )

    async def _caller_views(_user_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(id="caller-workspace")]

    monkeypatch.setattr(inspection, "list_views_for_user", _caller_views)

    # List: canonical Runs in the caller's universe, newest first.
    listed = await inspection.list_visible_runs(_AUTHED_USER_ID)
    assert [row["id"] for row in listed] == [run.run_id]

    # Detail: the record is the projection row overlaid with canonical
    # lifecycle truth — status/workspace/project come from the Run.
    detail = await inspection.visible_run_detail(_AUTHED_USER_ID, run.run_id)
    assert detail is not None
    assert detail["canonical_run_id"] == run.run_id
    assert detail["workspace_id"] == "caller-workspace"
    assert detail["status"] == run.status.value

    # By-id authorization and the batch companion agree with the list.
    assert await inspection.can_inspect_run(_AUTHED_USER_ID, run.run_id) is True
    assert await inspection.visible_run_ids(_AUTHED_USER_ID, [run.run_id]) == {run.run_id}

    # A canonical id the spine never saw is refused — even though the store
    # is configured and the caller has Workspaces.
    assert await inspection.can_inspect_run(_AUTHED_USER_ID, "canonical-never-was") is False


async def test_configured_spine_list_hides_runs_outside_the_callers_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical listing filters by the caller's Workspace universe — a
    foreign canonical Run is absent from the list even though it is the most
    recent Run in the store, and a projection row cannot add it back."""
    import services.engine as engine_mod
    from services import dag_run_inspection as inspection

    from maistro.graph.definitions import Graph, Node
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore

    projects = InMemoryProjectScopeStore()
    foreign_project = await projects.create_root("foreign-workspace")
    mine_project = await projects.create_root("caller-workspace")
    runs = InMemoryRunStore(project_store=projects)

    async def _add(graph_id: str, workspace_id: str, project_id: str) -> None:
        await runs.create_run(
            Graph(
                graph_id=graph_id,
                workspace_id=workspace_id,
                project_id=project_id,
                name=graph_id,
                nodes=[Node(node_id="only", node_type="probe", name="Only")],
            )
        )

    await _add("mine-graph", "caller-workspace", mine_project.project_id)
    await _add("foreign-graph", "foreign-workspace", foreign_project.project_id)
    # A foreign projection row must not resurrect the foreign Run for this
    # observer.
    await _seed_run_async("foreign-projection", workspace_id="caller-workspace")

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_store=runs),
    )

    async def _caller_views(_user_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(id="caller-workspace")]

    monkeypatch.setattr(inspection, "list_views_for_user", _caller_views)

    listed = await inspection.list_visible_runs(_AUTHED_USER_ID)
    listed_ids = {row["id"] for row in listed}
    assert "foreign-graph" not in listed_ids
    # The seeded projection row names a canonical Run the store never saw
    # under that id: it is absent too, not surfaced as a projection-only run.
    assert "foreign-projection" not in listed_ids
    assert listed_ids  # the caller's own Run is still served
    assert await inspection.visible_run_detail(_AUTHED_USER_ID, "foreign-projection") is None
