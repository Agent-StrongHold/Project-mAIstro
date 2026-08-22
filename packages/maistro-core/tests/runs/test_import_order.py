"""The canonical execution spine imports from its own front door.

`maistro.runs.model` used to bind `maistro.graph.definitions.Graph` at module
scope, and `maistro.graph`'s package __init__ imports `traversal_commit`, which
imports `maistro.runs.model`. The cycle was invisible in practice because
something always imported `maistro.graph` first — but `import maistro.runs` on
its own raised ImportError, so any new caller that reached the Run spine before
the Graph package failed at import time for reasons having nothing to do with it.

These run in subprocesses on purpose: within one interpreter the first test to
touch either package populates `sys.modules` and every later import order looks
fine regardless of the defect.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

import maistro

#: The subprocesses must find the package under test whether or not the parent
#: run set PYTHONPATH, so derive it from the imported package rather than trust
#: the ambient environment.
_SRC = str(pathlib.Path(maistro.__file__).resolve().parent.parent)


def _run(statement: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([_SRC, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


ORDERS = [
    "import maistro.runs",
    "import maistro.graph",
    "import maistro.runs.model",
    "import maistro.graph.traversal_commit",
    "import maistro.tasks.queue",
    "from maistro.runs.admission import admit_direct_work",
    "from maistro.tasks.admission import TaskRunAdmitter",
]


@pytest.mark.parametrize("statement", ORDERS)
def test_each_entry_point_imports_first(statement: str) -> None:
    result = _run(statement)

    assert result.returncode == 0, result.stderr


def test_a_run_snapshot_still_materializes_its_graph() -> None:
    """The deferred import must not have cost the behavior it carried."""
    statement = (
        "from maistro.runs.model import GraphSnapshot\n"
        "from maistro.graph.definitions import Graph, Node\n"
        "graph = Graph(workspace_id='w', project_id='p', name='g',\n"
        "              nodes=[Node(node_type='transform.format_markdown', name='n')])\n"
        "snapshot = GraphSnapshot.from_graph(graph)\n"
        "assert snapshot.materialize().graph_id == graph.graph_id\n"
    )
    result = _run(statement)

    assert result.returncode == 0, result.stderr
