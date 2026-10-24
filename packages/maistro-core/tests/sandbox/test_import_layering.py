"""The sandbox subsystem stays import-light toward the execution stack (#1197).

Invariant: whichever of the entry points below a process enters first, all of
them must import cleanly — only a fresh interpreter can prove that, because
in-process assertions see a sys.modules order the failure is order-dependent
on. The property was load-bearing in this very round: an intermediate shape
had the tools layer importing its capture bounds through a `maistro.sandbox`
leaf, which initialized the facade, whose fence then pulled
`maistro.runs` -> `maistro.graph` -> `maistro.capabilities` -> the opencode
provider -> `maistro.tools.sandbox.microvm` — an import-order cycle that made
`import maistro.capabilities` fail outright. The final shape removes the
back-edge at the root (executors import the stdlib-only
`maistro.tools.sandbox._capture`) and the facade resolves its one execution-
stack name lazily; this test keeps the whole matrix honest against any future
edge that reintroduces a cycle.
"""

from __future__ import annotations

import subprocess
import sys

_ENTRY_POINTS = (
    "maistro.capabilities",
    "maistro.runs",
    "maistro.sandbox",
    "maistro.tools.sandbox.microvm",
    "maistro.tools.sandbox.docker",
)


def test_sandbox_and_execution_stack_import_in_any_entry_order() -> None:
    for entry in _ENTRY_POINTS:
        probe = f"import {entry}; import maistro.capabilities; import maistro.sandbox"
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, (
            f"entering via {entry!r} broke the import graph:\n{proc.stderr.strip()}"
        )


def test_facade_resolves_the_lazy_fence_error_to_the_canonical_class() -> None:
    """`StaleExecutionFence` is owned by `maistro.runs.store`; the facade and
    `maistro.sandbox.fence` re-export it lazily, and the re-export must be the
    same class object the store raises — otherwise `except` clauses written
    against the store would miss a fence refusal."""
    from maistro.runs.store import StaleExecutionFence as canonical
    from maistro.sandbox import StaleExecutionFence as facade
    from maistro.sandbox.fence import StaleExecutionFence as fence_reexport

    assert facade is canonical
    assert fence_reexport is canonical


def test_unknown_facade_names_still_fail_loudly() -> None:
    """The lazy slot must not swallow AttributeErrors for genuine typos."""
    import maistro.sandbox as sandbox_pkg

    try:
        sandbox_pkg.Not_A_Real_Export  # noqa: B018 - attribute existence is the test
    except AttributeError as exc:
        assert "Not_A_Real_Export" in str(exc)
    else:
        raise AssertionError("a nonexistent facade name resolved successfully")
