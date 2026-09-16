"""#1113 architecture gate: shipped Hive code cannot execute Graph work off-spine.

The behavior tests (``test_dag_agents.py``, ``test_canonical_dag_runner.py``,
``test_scheduler.py``) prove today's no-spine surfaces report ``unavailable``
instead of executing. Those tests fail only when the regression is exercised;
two source-level regressions could land without ever being called in a test:

1. a shipped module calling ``run_durable_graph(...)`` without ``run_store=``
   (or with an explicit ``None``) -- traversal would run with no canonical Run
   admission, exactly the pre-convergence universe #1113 retired;
2. a shipped module referencing ``InMemoryDurableRunStore`` or the old
   module-private ``_fallback_run_store`` / ``_fallback_node_resolver`` --
   the process-local lifecycle that disappears on restart.

This module walks the shipped backend sources (everything under ``backend/``
except ``tests/``) and fails with ``file:line`` evidence if either pattern
reappears. The in-memory store remains a test fixture only; production
execution authority is the Container's ``run_store`` + ``graph_run_store``.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]

# Shipped execution surface: every Python module a product process loads,
# which is the whole backend tree minus the test package and its caches.
_EXCLUDED_DIRS = frozenset({"tests", "__pycache__", "data"})

_FORBIDDEN_NAMES = frozenset(
    {
        "InMemoryDurableRunStore",
        "_fallback_run_store",
        "_fallback_node_resolver",
    }
)


def _shipped_sources() -> list[pathlib.Path]:
    return sorted(
        path
        for path in _BACKEND.rglob("*.py")
        if not (set(path.relative_to(_BACKEND).parts) & _EXCLUDED_DIRS)
    )


def _run_durable_graph_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id == "run_durable_graph") or (
            isinstance(func, ast.Attribute) and func.attr == "run_durable_graph"
        ):
            calls.append(node)
    return calls


def _admission_kwarg(call: ast.Call) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "run_store":
            return keyword.value
    return None


def test_shipped_run_durable_graph_calls_admit_canonical_work() -> None:
    """Every shipped traversal hands the executor a canonical ``run_store``.

    The executor's ``run_store`` parameter defaults to ``None``; a call that
    omits it (or passes ``None``) is the pre-convergence path, where node runs
    are filed only against the executor's private store. #1113 removed the
    last such call; this gate keeps it removed.
    """
    offenders: list[str] = []
    for path in _shipped_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _run_durable_graph_calls(tree):
            admitted = _admission_kwarg(call)
            if admitted is None:
                offenders.append(f"{path}:{call.lineno} omits run_store=")
            elif isinstance(admitted, ast.Constant) and admitted.value is None:
                offenders.append(f"{path}:{call.lineno} passes run_store=None")

    assert not offenders, "shipped Graph traversal without canonical Run admission:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("forbidden", sorted(_FORBIDDEN_NAMES))
def test_shipped_code_never_selects_the_inmemory_fallback(forbidden: str) -> None:
    """The process-local fallback store/resolver may not be imported or named.

    ``InMemoryDurableRunStore`` is confined to test fixtures (which live under
    ``tests/`` and are excluded here); the ``_fallback_*`` module globals were
    deleted from ``services/dag_agents.py`` by #1113. Any shipped reference to
    either is a second execution lifecycle trying to grow back.
    """
    offenders: list[str] = []
    for path in _shipped_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            seen: str | None = None
            if isinstance(node, ast.Name) and node.id == forbidden:
                seen = "reference"
            elif isinstance(node, ast.Attribute) and node.attr == forbidden:
                seen = "attribute"
            elif isinstance(node, ast.alias) and node.name.split(".")[-1] == forbidden:
                seen = "import"
            if seen is not None:
                offenders.append(f"{path}:{node.lineno} {seen} of {forbidden}")

    assert not offenders, f"shipped code selects {forbidden} as execution authority:\n" + "\n".join(
        offenders
    )
