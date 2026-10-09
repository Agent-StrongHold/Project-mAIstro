"""The benchmark machinery itself cannot alter production semantics (#925).

Mirrors the #883 failpoint lab's fail-closed guard: the lab lives in the test
tree, nothing under ``packages/*/src`` may import it, and no wheel can ship
it. The benchmark also adds no execution authority -- its arms drive the
shipped ``ReactStrategy``, ``PlanExecuteStrategy`` and ``GraphRun`` exactly
as production does.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

_LAB_MODULE_NAMES = {"planning_benchmark", "_world", "_policy", "_harness"}

_SRC_ROOTS = [
    path for path in Path(__file__).resolve().parents[5].glob("packages/*/src") if path.is_dir()
]


def _imported_module_names(path: Path) -> Iterator[str]:
    """Yield the dotted module names a file actually imports -- prose ignored."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def _is_lab_import(module_name: str) -> bool:
    segments = module_name.split(".")
    return bool(_LAB_MODULE_NAMES.intersection(segments))


def test_no_production_module_imports_the_benchmark_lab() -> None:
    assert _SRC_ROOTS, "the packages/*/src scan must see the source tree"
    offenders: list[str] = []
    for root in _SRC_ROOTS:
        for path in root.rglob("*.py"):
            for module_name in _imported_module_names(path):
                if _is_lab_import(module_name):
                    offenders.append(f"{path}: imports {module_name}")
    assert offenders == [], f"production modules import the benchmark lab: {offenders}"


def test_the_lab_defines_no_scheduler_or_store() -> None:
    """The harness drives shipped strategies and ``GraphRun``; it must not
    become a competing execution authority (no run/book/scheduling state)."""
    from . import _harness as harness_module
    from . import _policy as policy_module
    from . import _world as world_module

    forbidden_markers = ("RunStore", "NodeRunStore", "Scheduler", "Lease", "FencingToken")
    for module in (harness_module, policy_module, world_module):
        names = set(vars(module))
        for marker in forbidden_markers:
            defined = [name for name in names if marker.lower() in name.lower()]
            assert not defined, f"{module.__name__} defines {marker}-like names: {defined}"
