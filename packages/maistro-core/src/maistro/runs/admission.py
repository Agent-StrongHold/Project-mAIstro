"""Admitting directly-submitted work as a canonical Run (#41).

A task, a chat turn or a single-agent request is still work, and #41's rule is
that work has exactly one execution identity regardless of where it entered:
`Workspace/Project → Graph → Run → NodeRun → Attempt`. What such a request lacks
is a Graph, because nobody drew one — so admission builds the trivial one, a
single node in the submitting Project.

`Graph` deliberately does not validate `node_type` against the node catalog: a
Graph is a definition, and definitions are written before their implementations
exist. That freedom is wrong at *admission*, where the whole point is to produce
a Run something can later execute. A Run whose only node names a kind no
executor knows would be a canonical-looking record of work that can never
start — the shape of half-truth this convergence program exists to remove. So
this module checks the kind against the registry and refuses otherwise.

What this module does not do is choose the kind. That decision belongs to the
entry point, because only the entry point knows what it submitted;
`maistro.runs.task_kinds` makes it for the task-shaped ones. Admission takes the
kind as given and holds it to being real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.graph.definitions import Graph, Node
from maistro.graph.nodes import list_kinds
from maistro.runs.model import RunStatus

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore

#: Provenance key recording how a Run entered the system.
ADMISSION_SOURCE = "admission_source"


class UnknownNodeKindError(ValueError):
    """Raised when admission is asked for a node kind no executor knows."""


def _require_registered(node_type: str) -> None:
    if not node_type.strip():
        raise UnknownNodeKindError("node_type must be a non-empty string")
    known_kinds = set(list_kinds())
    if node_type not in known_kinds:
        known = ", ".join(sorted(known_kinds))
        raise UnknownNodeKindError(
            f"no node kind {node_type!r} is registered, so a Run admitted with it could "
            f"never execute. Registered kinds: {known}"
        )


def direct_work_graph(
    *,
    workspace_id: str,
    project_id: str,
    node_type: str,
    name: str,
    parameters: dict[str, Any] | None = None,
    description: str = "",
) -> Graph:
    """The trivial Graph for one unit of directly-submitted work.

    One node, no edges, filed in the submitting Project. Raises
    :class:`UnknownNodeKindError` when ``node_type`` names no registered kind —
    admission that produces an unexecutable Run is worse than refusing.
    """
    _require_registered(node_type)
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        description=description,
        nodes=[Node(node_type=node_type, name=name, parameters=dict(parameters or {}))],
        edges=[],
    )


async def admit_direct_work(
    store: RunStore,
    *,
    workspace_id: str,
    project_id: str,
    node_type: str,
    name: str,
    source: str,
    parameters: dict[str, Any] | None = None,
    description: str = "",
    actor_principal_id: str | None = None,
    persona_id: str | None = None,
    provenance: dict[str, Any] | None = None,
    initial_status: RunStatus = RunStatus.CREATED,
) -> Run:
    """Admit directly-submitted work and return its canonical Run.

    ``source`` records what admitted it — a queue, a chat turn, a webhook — so a
    Run can be traced back to its entry point without the entry point having to
    own any lifecycle state of its own. That is the whole trade #41 asks for:
    the admission record stays a receipt, the Run becomes the truth.
    """
    graph = direct_work_graph(
        workspace_id=workspace_id,
        project_id=project_id,
        node_type=node_type,
        name=name,
        parameters=parameters,
        description=description,
    )
    return await store.create_run(
        graph,
        actor_principal_id=actor_principal_id,
        persona_id=persona_id,
        # `source` last, deliberately. With the spread last, a caller passing
        # `admission_source` in its own provenance silently overrode the
        # argument, and the Run could then claim it entered through a queue,
        # webhook or request path it never touched — which is the one field an
        # audit correlates on.
        provenance={**(provenance or {}), ADMISSION_SOURCE: source},
        # One commit. An entry point that already knows the work is queued says
        # so here rather than transitioning immediately afterwards.
        initial_status=initial_status,
    )


__all__ = [
    "ADMISSION_SOURCE",
    "UnknownNodeKindError",
    "admit_direct_work",
    "direct_work_graph",
]
