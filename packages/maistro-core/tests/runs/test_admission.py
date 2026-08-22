"""Directly-submitted work becomes a canonical Run (#41).

The rule is that work has one execution identity regardless of where it entered.
A task or chat turn has no Graph because nobody drew one, so admission builds the
trivial one — and the property that matters is that it refuses to build an
unexecutable one, because a canonical-looking Run that can never start is worse
than an honest rejection.
"""

from __future__ import annotations

import pytest

from maistro.graph.nodes import list_kinds
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission import (
    ADMISSION_SOURCE,
    UnknownNodeKindError,
    admit_direct_work,
    direct_work_graph,
)
from maistro.runs.store import InMemoryRunStore

#: Any registered kind works; the tests are about admission, not this kind.
KIND = "transform.format_markdown"


@pytest.fixture
async def scoped():
    """A run store over a real Project, which is what the store insists on.

    `InMemoryRunStore` validates a Graph's scope against a live Project before
    creating a Run — the type-level half of #36's fourth invariant. Admission
    inherits that for free, so these tests exercise it rather than stubbing it.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Direct work"
    )
    return InMemoryRunStore(project_store=projects), project.project_id


def _graph(**overrides):
    kwargs = {
        "workspace_id": "w1",
        "project_id": "p1",
        "node_type": KIND,
        "name": "summarise the inbox",
    }
    kwargs.update(overrides)
    return direct_work_graph(**kwargs)


# --- the graph ----------------------------------------------------------------


def test_direct_work_is_one_node_in_the_submitting_project() -> None:
    graph = _graph()
    assert len(graph.nodes) == 1
    assert graph.edges == []
    assert (graph.workspace_id, graph.project_id) == ("w1", "p1")
    assert graph.nodes[0].node_type == KIND


def test_parameters_reach_the_node() -> None:
    graph = _graph(parameters={"tone": "brief"})
    assert graph.nodes[0].parameters == {"tone": "brief"}


def test_the_caller_cannot_mutate_the_graph_through_its_parameters() -> None:
    params = {"tone": "brief"}
    graph = _graph(parameters=params)
    params["tone"] = "verbose"
    assert graph.nodes[0].parameters == {"tone": "brief"}


@pytest.mark.parametrize("kind", ["", "   ", "task.direct", "not.a.kind"])
def test_an_unregistered_kind_is_refused(kind: str) -> None:
    """Graph does not validate node_type, deliberately — a definition may
    precede its implementation. At admission that freedom is wrong: the point is
    to produce a Run something can execute."""
    with pytest.raises(UnknownNodeKindError):
        _graph(node_type=kind)


def test_the_refusal_names_the_kinds_that_would_work() -> None:
    with pytest.raises(UnknownNodeKindError) as excinfo:
        _graph(node_type="task.direct")
    message = str(excinfo.value)
    assert "task.direct" in message
    assert any(kind in message for kind in list_kinds())


# --- the run ------------------------------------------------------------------


async def test_admission_yields_a_run_scoped_to_the_project(scoped) -> None:
    store, project_id = scoped
    run = await admit_direct_work(
        store,
        workspace_id="w1",
        project_id=project_id,
        node_type=KIND,
        name="summarise the inbox",
        source="task-queue",
    )
    assert run.run_id
    assert (run.workspace_id, run.project_id) == ("w1", project_id)
    assert await store.get_run(run.run_id) is not None


async def test_the_run_records_what_admitted_it(scoped) -> None:
    """A Run must be traceable to its entry point without that entry point
    owning any lifecycle state of its own — the trade #41 asks for."""
    store, project_id = scoped
    run = await admit_direct_work(
        store,
        workspace_id="w1",
        project_id=project_id,
        node_type=KIND,
        name="n",
        source="chat-turn",
        provenance={"session_id": "s-7"},
    )
    assert run.provenance[ADMISSION_SOURCE] == "chat-turn"
    assert run.provenance["session_id"] == "s-7", "caller provenance survives alongside it"


async def test_the_actor_is_carried_onto_the_run(scoped) -> None:
    store, project_id = scoped
    run = await admit_direct_work(
        store,
        workspace_id="w1",
        project_id=project_id,
        node_type=KIND,
        name="n",
        source="task-queue",
        actor_principal_id="user-3",
    )
    assert run.actor_principal_id == "user-3"


async def test_two_admissions_are_two_runs(scoped) -> None:
    store, project_id = scoped
    first = await admit_direct_work(
        store, workspace_id="w1", project_id=project_id, node_type=KIND, name="n", source="s"
    )
    second = await admit_direct_work(
        store, workspace_id="w1", project_id=project_id, node_type=KIND, name="n", source="s"
    )
    assert first.run_id != second.run_id


async def test_admission_into_an_unknown_project_is_refused(scoped) -> None:
    """Scope is not advisory. The store validates the Graph's Project before
    creating a Run, so admission cannot smuggle work into a Project that does
    not exist."""
    store, _ = scoped
    with pytest.raises(Exception):  # noqa: B017 - store raises its own scope error
        await admit_direct_work(
            store, workspace_id="w1", project_id="p-nope", node_type=KIND, name="n", source="s"
        )


async def test_caller_provenance_cannot_override_the_admission_source(scoped) -> None:
    """`admission_source` is what an audit correlates on, so a caller must not
    be able to relabel where its work entered from."""
    runs, project_id = scoped

    run = await admit_direct_work(
        runs,
        workspace_id="w1",
        project_id=project_id,
        node_type=KIND,
        name="n",
        source="task_queue",
        provenance={ADMISSION_SOURCE: "totally_trusted_webhook", "other": "kept"},
    )

    assert run.provenance[ADMISSION_SOURCE] == "task_queue"
    assert run.provenance["other"] == "kept"
