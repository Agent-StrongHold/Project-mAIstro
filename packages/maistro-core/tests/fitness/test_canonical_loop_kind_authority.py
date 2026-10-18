"""#790 (ADR-092926-7a01): the M7 loop kinds have one registration authority.

Issue #788 Wave 1, Gate A: "CI contract tests fail if a product introduces a
competing Goal/Rubric/Run/eval identity." The `maistro.ontology` registry is
the runtime kind authority (`engine#ADR-036`): whichever module registers the
canonical loop kinds there *is* the loop's identity. A product that registers
its own ``Goal`` / ``Rubric`` / ``Eval``-style ontology kind has built a
second loop authority even if the objects never touch each other.

The canonical loop kinds may be registered only from the canonical ontology
module (``packages/maistro-core/src/maistro/ontology/``). This suite is the
static fence: it walks production Python for ``register(<canonical slug>, ..)``
calls outside that module. The #990 product-boundary suite
(``test_no_second_design_product.py``) is complementary -- it freezes product
shapes (names, routes, client storage); this fence freezes the runtime kind
namespace the loop objects live in.

The slug set is deliberately the loop nouns from #788/#790: Goal, Rubric,
Run, and eval. ``Pack`` and ``Fence`` are loop *contracts* (a pack is a
Graph/skill bundle of one Run, a fence is a decision on a waiting NodeRun),
not ontology kinds, so registering those words is not a loop identity and is
out of scope here.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PACKAGES = _REPO_ROOT / "packages"
_HIVE_BACKEND = _PACKAGES / "hive-conductor" / "backend"

#: The only module allowed to register the canonical loop kinds. #791 lands
#: the canonical Rubric (and any sibling kinds) here; today the module ships
#: only the ``Person`` docstring example.
_CANONICAL_ONTOLOGY_MODULE = _PACKAGES / "maistro-core" / "src" / "maistro" / "ontology"

#: Loop nouns whose ontology registration is reserved to the canonical module
#: (#790). Matched case-insensitively on the whole slug: ``"Goal"`` and
#: ``"goal"`` are the same competing identity; ``"goal_graph"`` is not.
_CANONICAL_LOOP_KINDS = frozenset(
    {
        "goal",
        "goals",
        "rubric",
        "rubrics",
        "run",
        "runs",
        "eval",
        "evals",
        "evaluation",
        "evaluations",
    }
)


def _production_python_files() -> list[Path]:
    """``packages/*/src`` trees plus the flat hive-conductor backend app."""
    files: list[Path] = []
    for pkg in sorted(_PACKAGES.iterdir()):
        src = pkg / "src"
        if src.is_dir():
            files.extend(p for p in src.rglob("*.py") if "__pycache__" not in p.parts)
    if _HIVE_BACKEND.is_dir():
        files.extend(p for p in _HIVE_BACKEND.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _is_test_path(path: Path) -> bool:
    return "test" in path.parts or path.name.startswith("test_")


def _relative(path: Path) -> str:
    try:
        return path.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _registered_kind_slugs(path: Path) -> list[tuple[int, str]]:
    """``(lineno, slug)`` for every ``register(<string>, ...)`` call in path.

    Both ``obj.register(...)`` and bare ``register(...)`` are matched; the
    first positional argument must be a literal string. Dispatch-style
    ``register`` calls take classes or functions, so the string-argument
    shape is registry-kind shaped and safe to read as a kind claim.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name != "register" or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        found.append((node.lineno, first.value))
    return found


def _competing_registrations(paths: Iterable[Path]) -> list[str]:
    """Canonical-kind registrations outside the canonical module, named."""
    offenders: list[str] = []
    for path in paths:
        if _is_test_path(path):
            continue
        if path.is_relative_to(_CANONICAL_ONTOLOGY_MODULE):
            continue
        for lineno, slug in _registered_kind_slugs(path):
            if slug.strip().lower() in _CANONICAL_LOOP_KINDS:
                offenders.append(
                    f"{_relative(path)}:{lineno}: registers canonical loop kind {slug!r}"
                )
    return offenders


@pytest.mark.contract("boundary")
def test_no_competing_loop_kind_registration() -> None:
    """Production code cannot register Goal/Rubric/Run/eval ontology kinds.

    Only the canonical ontology module may claim the loop-kind namespace
    (#790 Gate A). Today the fence passes vacuously -- nothing registers
    these kinds yet (#791 lands the canonical Rubric) -- and it stays that
    way only while no product grows its own loop identity.
    """
    offenders = _competing_registrations(_production_python_files())
    assert not offenders, (
        f"the M7 loop kinds have one registration authority (#790, ADR-092926-7a01): {offenders}"
    )


def test_fence_detects_a_synthetic_competing_registration(tmp_path: Path) -> None:
    """The fence trips on a product-side ``Goal`` kind and nothing else.

    A guard that cannot fire is decoration. The violation file registers a
    competing ``Goal`` ontology kind exactly the way a stray product module
    would; the control file registers a non-canonical kind and must pass.
    """
    violating = tmp_path / "product_goal.py"
    violating.write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "\n"
        "class GoalModel(BaseModel):\n"
        "    title: str\n"
        "\n"
        "\n"
        "def wire(registry) -> None:\n"
        "    registry.register('Goal', GoalModel)\n",
        encoding="utf-8",
    )
    control = tmp_path / "product_widget.py"
    control.write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "\n"
        "class Widget(BaseModel):\n"
        "    name: str\n"
        "\n"
        "\n"
        "def wire(registry) -> None:\n"
        "    registry.register('Widget', Widget)\n",
        encoding="utf-8",
    )

    offenders = _competing_registrations([violating, control])
    assert len(offenders) == 1, offenders
    assert "product_goal.py" in offenders[0]
    assert "registers canonical loop kind 'Goal'" in offenders[0]
