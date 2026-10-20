"""Canonical Run inspection/control composition for the Conductor (#1036).

Developed against the merged canonical seam set: the Conductor reads run
truth through its projection page plus the scoped canonical overlay
(`ScopedRunReader`), and by canonical id a Run with no projection row at
all is answered directly from the canonical spine -- inspectable and
controllable by the same id any producer's Run carries. A bridge-less
standalone keeps only presentation reads with no terminal authority
(ADR-082826-d9f5).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from maistro.identity import Principal

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]

_USER_ID = "canonical-inspection-user"
_FOREIGN_USER = "observer-elsewhere"

_ROW_ID = "dag-producer-e2e"
_STANDALONE_ROW_ID = "dag-standalone-e2e"


class _ScopedRequest:
    """Just what the dag-runs handlers read off a request: `state.principal`."""

    def __init__(self, user_id: str) -> None:
        self.state = SimpleNamespace(principal=Principal(user_id=user_id, username=user_id))


async def _owned_workspace() -> Any:
    from services.workspace_authority import create_workspace

    return await create_workspace(
        creator_user_id=_USER_ID,
        name="Canonical Inspection",
        persona_template_id="pm_fleet",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )


def _point_engine_at(
    monkeypatch: pytest.MonkeyPatch,
    store: Any,
    reader: Any,
) -> None:
    import services.engine as engine_mod

    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )


async def test_canonical_event_inspection_reads_past_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.dag_run_inspection import _canonical_events

    class EventPageStore:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        async def list_stream(
            self, stream_id: str, *, after_sequence: int = 0, limit: int = 100
        ) -> list[Any]:
            assert stream_id == "workspace:workspace-1"
            self.calls.append((after_sequence, limit))
            start = after_sequence + 1
            end = min(start + limit, 1002)
            return [
                SimpleNamespace(
                    sequence=sequence,
                    run_id="target-run" if sequence == 1001 else "other-run",
                    to_dict=lambda sequence=sequence: {"sequence": sequence},
                )
                for sequence in range(start, end)
            ]

    events = EventPageStore()
    run = SimpleNamespace(workspace_id="workspace-1")
    reader = SimpleNamespace(get_run=lambda *_args, **_kwargs: _async_value(run))
    engine = SimpleNamespace(
        run_reader=reader,
        agent_port=SimpleNamespace(
            container=SimpleNamespace(capability_effects=SimpleNamespace(event_store=events))
        ),
    )
    import services.engine as engine_mod

    monkeypatch.setattr(engine_mod, "_singleton", engine)
    assert await _canonical_events("target-run", "user-1", workspace_id="workspace-1") == [
        {"sequence": 1001}
    ]
    assert events.calls == [(sequence, 100) for sequence in range(0, 1100, 100)]


async def _async_value(value: Any) -> Any:
    return value


async def test_a_projectionless_canonical_run_is_inspectable_and_controllable_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-product producer -> canonical spine -> Conductor observer (#1036).

    A Run created through the real canonical producer seam
    (`RunExecutionService.create_run` over a real scoped `InMemoryRunStore` --
    the same handoff surface Builders/schedule/Evolve adapters use) that never
    recorded a Conductor projection row is still inspectable and controllable
    by its canonical id: detail answers from the Run itself, the cancel route
    cancels through the canonical spine without writing a projection row, and
    a foreign observer gets the identical non-disclosing refusal a missing id
    gets. Recent-list discovery uses the canonical scoped store capability
    added for Goal inspection, rather than requiring a projection row.
    """
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_inspection import (
        can_inspect_run,
        list_visible_runs,
        visible_run_detail,
        visible_run_ids,
    )
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.runs import InMemoryRunStore, RunExecutionService, RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader
    from maistro.runtime import PythonExecutionRuntime

    view = await _owned_workspace()
    workspaces = canonical_store_for_tests()
    projects = workspaces.project_store
    store = InMemoryRunStore(project_store=projects)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

    root = await projects.root_for_workspace(view.id)
    project = await projects.create(
        workspace_id=view.id,
        parent_project_id=root.project_id,
        name="Cross-product",
    )
    graph = Graph(
        workspace_id=view.id,
        project_id=project.project_id,
        name="producer",
        nodes=[Node(node_id="node-1", node_type="agent", name="Producer node")],
    )
    run = await service.create_run(
        graph,
        actor_principal_id=_USER_ID,
        provenance={"producer": "non-conductor product adapter"},
    )

    # The producer never recorded a Conductor projection row, and nothing in
    # this test creates one: every answer below comes from the canonical seam.
    assert get_dag_run_store().get_run(run.run_id) is None

    _point_engine_at(monkeypatch, store, ScopedRunReader(store, workspaces, projects))

    # By canonical id, the Run itself is the answer: canonical identity,
    # lifecycle truth, and the caller's scope -- no projection row required.
    detail = await visible_run_detail(_USER_ID, run.run_id)
    assert detail is not None
    assert detail["id"] == detail["canonical_run_id"] == run.run_id
    assert detail["status"] == "created"
    assert detail["workspace_id"] == view.id
    assert detail["result"] is None
    assert detail["finished_at"] is None
    # No event history is fabricated for a run this store never recorded:
    # the projection event-history gap is named, not filled (#1036).
    assert detail["events"] == []
    assert await can_inspect_run(_USER_ID, run.run_id)
    assert await visible_run_ids(_USER_ID, [run.run_id, "no-such-run"]) == {run.run_id}

    # Control delegates through the canonical seam by the same id (#1169
    # authority): the fence lands on the canonical Run, and the projection
    # store never gains a row for it -- cancellation is not a projection edit.
    response = await cancel_route(run.run_id, _ScopedRequest(_USER_ID))
    assert response == {"run_id": run.run_id, "status": "cancelled", "cancelled": True}
    cancelled = await store.get_run(run.run_id)
    assert cancelled is not None and cancelled.status is RunStatus.CANCELLED
    assert cancelled.finished_at is not None
    assert get_dag_run_store().get_run(run.run_id) is None

    # Discovery and detail now agree without creating a projection row.
    listed = await list_visible_runs(_USER_ID, limit=25)
    assert [row["id"] for row in listed] == [run.run_id]
    assert listed[0]["status"] == "cancelled"
    assert get_dag_run_store().get_run(run.run_id) is None

    # Foreign and random ids get the identical non-disclosing refusal --
    # detail, stream admission and the batch verdict reader all agree.
    assert await visible_run_detail(_FOREIGN_USER, run.run_id) is None
    assert await visible_run_detail(_USER_ID, "no-such-run") is None
    assert not await can_inspect_run(_FOREIGN_USER, run.run_id)
    assert not await can_inspect_run(_USER_ID, "no-such-run")
    assert await visible_run_ids(_FOREIGN_USER, [run.run_id]) == set()


async def test_a_stale_projection_row_overlays_canonical_truth_and_stays_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The projection page overlays canonical lifecycle truth (#1877).

    When a Conductor projection row exists and names a canonical Run the
    caller may read, list and detail serve the Run's status/result -- not
    the row's stale "running" -- with the NodeRun/Attempt evidence filed in
    the same spine, and an observer outside the producing Workspace sees
    nothing. The row here plays its real role: presentation history the
    canonical Run overrides, never the discovery mechanism for another
    producer's Run (that is the projectionless by-id test above).
    """
    from services.dag_run_inspection import list_visible_runs, visible_run_detail
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.runs import AttemptStatus, InMemoryRunStore, RunExecutionService, RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader
    from maistro.runtime import PythonExecutionRuntime

    view = await _owned_workspace()
    workspaces = canonical_store_for_tests()
    projects = workspaces.project_store
    store = InMemoryRunStore(project_store=projects)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

    root = await projects.root_for_workspace(view.id)
    project = await projects.create(
        workspace_id=view.id,
        parent_project_id=root.project_id,
        name="Cross-product",
    )
    graph = Graph(
        workspace_id=view.id,
        project_id=project.project_id,
        name="producer",
        nodes=[Node(node_id="node-1", node_type="agent", name="Producer node")],
    )
    run = await service.create_run(
        graph,
        actor_principal_id=_USER_ID,
        provenance={"producer": "non-conductor product adapter"},
    )

    async def executor(work_item: Any, context: Any) -> dict[str, Any]:
        return {"work": work_item, "context": context}

    node_run, attempt = await service.execute_node(
        run.run_id,
        "node-1",
        "payload",
        {"run_id": run.run_id},
        executor=executor,
        executor_id="producer",
    )
    assert node_run.status is RunStatus.COMPLETED
    assert attempt.status is AttemptStatus.COMPLETED

    # The producer seam itself settles the Run through the shared lifecycle
    # (status completed, physical result recorded); the projection row still
    # says "running" until canonical truth is overlaid onto it.

    reader = ScopedRunReader(store, workspaces, projects)
    _point_engine_at(monkeypatch, store, reader)
    await get_dag_run_store().start_run(
        run_id=_ROW_ID,
        user_id=_USER_ID,
        workspace_id=view.id,
        canonical_run_id=run.run_id,
    )

    listed = {row["id"]: row for row in await list_visible_runs(_USER_ID, limit=25)}
    assert listed[_ROW_ID]["canonical_run_id"] == run.run_id
    # Canonical lifecycle truth, not the projection row's stale "running".
    assert listed[_ROW_ID]["status"] == "completed"

    detail = await visible_run_detail(_USER_ID, _ROW_ID)
    assert detail is not None
    assert detail["canonical_run_id"] == run.run_id
    assert detail["status"] == "completed"
    assert detail["result"]["work"] == "payload"

    # The NodeRun/Attempt evidence lives in the same canonical spine, filed
    # under the same run id the inspection answer names.
    node_runs = await store.list_node_runs(run.run_id)
    assert [nr.node_run_id for nr in node_runs] == [node_run.node_run_id]
    attempts = await store.list_attempts(node_run.node_run_id)
    assert [a.attempt_id for a in attempts] == [attempt.attempt_id]

    # An observer outside the producing Workspace sees nothing: cross-product
    # inspection is scoped by the canonical boundary, not by producer identity.
    foreign_listed = await list_visible_runs(_FOREIGN_USER, limit=25)
    assert all(row["id"] != _ROW_ID for row in foreign_listed)
    assert await visible_run_detail(_FOREIGN_USER, _ROW_ID) is None


async def test_standalone_projection_is_presentation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closeout of the ADR-082826-d9f5 standalone compatibility path.

    With no canonical bridge wired, the retained projection may serve scoped
    reads (list/detail inside the caller's Workspace universe), but nothing
    on the path can terminalize a run: the cancel route refuses with 503 and
    the projection row it points at is left exactly as it was.
    """
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_inspection import list_visible_runs, visible_run_detail
    from services.dag_run_store import get_dag_run_store

    view = await _owned_workspace()
    # No Container bound: no canonical store and no reader -- the standalone
    # deployment shape, not an error.
    _point_engine_at(monkeypatch, None, None)
    await get_dag_run_store().start_run(
        run_id=_STANDALONE_ROW_ID,
        user_id=_USER_ID,
        workspace_id=view.id,
    )

    listed = {row["id"]: row for row in await list_visible_runs(_USER_ID, limit=25)}
    assert listed[_STANDALONE_ROW_ID]["workspace_id"] == view.id

    detail = await visible_run_detail(_USER_ID, _STANDALONE_ROW_ID)
    assert detail is not None
    assert detail["status"] == "running"

    # The compatibility path cannot terminalize or resurrect: no bridge means
    # no cancellation, not a projection-local one, and the row is untouched.
    with pytest.raises(HTTPException) as refused:
        await cancel_route(_STANDALONE_ROW_ID, _ScopedRequest(_USER_ID))
    assert refused.value.status_code == 503
    after = get_dag_run_store().get_run(_STANDALONE_ROW_ID)
    assert after is not None and after["status"] == "running"

    # Scope still holds without a bridge: nobody outside the Workspace
    # universe reads the row, and no canonical overlay is invented.
    foreign = await list_visible_runs(_FOREIGN_USER, limit=25)
    assert all(row["id"] != _STANDALONE_ROW_ID for row in foreign)
    assert await visible_run_detail(_FOREIGN_USER, _STANDALONE_ROW_ID) is None
