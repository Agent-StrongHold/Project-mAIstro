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

#: Every governed production Python root outside ``packages/*/src``. These
#: are the product surfaces that ship executable Python but do not use the
#: ``src`` layout: the flat Hive backend app, the Turing backend that CI
#: measures as production coverage, the Canvas frontend server, and the
#: Hive cage/dags/eval trees the Hive Dockerfile copies into the image.
_FLAT_APP_ROOTS: tuple[Path, ...] = (
    _PACKAGES / "hive-conductor" / "backend",
    _PACKAGES / "maistro-turing" / "backend",
    _PACKAGES / "maistro-canvas" / "frontend" / "server",
    _PACKAGES / "hive-conductor" / "cage",
    _PACKAGES / "hive-conductor" / "dags",
    _PACKAGES / "hive-conductor" / "eval",
)

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
    """``packages/*/src`` trees plus every governed flat production root.

    The flat roots in :data:`_FLAT_APP_ROOTS` ship executable Python that
    never sits under a ``src`` tree; any of them could carry a competing
    literal loop-kind registration, so all are walked.
    """
    files: list[Path] = []
    for pkg in sorted(_PACKAGES.iterdir()):
        src = pkg / "src"
        if src.is_dir():
            files.extend(p for p in src.rglob("*.py") if "__pycache__" not in p.parts)
    for root in _FLAT_APP_ROOTS:
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _is_test_path(path: Path) -> bool:
    # Test roots in this repo are named ``tests`` (plural); also keep the
    # singular and ``test_*`` module spellings so fixture helpers, conftest
    # modules, and inline ``register(...)`` wiring under any test directory
    # are never scanned as production code.
    return (
        "tests" in path.parts
        or "test" in path.parts
        or path.name.startswith("test_")
        or path.name == "conftest.py"
    )


def _relative(path: Path) -> str:
    try:
        return path.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _module_constant_strings(tree: ast.AST) -> dict[str, str]:
    """Names bound exactly once to a string literal anywhere in the module.

    The repository's registration idiom defines the kind slug as a module
    constant (``RUBRIC_KIND = "rubric"`` at ``maistro/ontology/rubric.py:43``)
    and passes the constant to ``register``. A fence that reads only inline
    literals would miss exactly that shape. Names assigned more than once (or
    bound to non-literals) stay unresolved rather than guessed.
    """
    assignment_counts: dict[str, int] = {}
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        target: ast.Name | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target
        if target is None:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        assignment_counts[target.id] = assignment_counts.get(target.id, 0) + 1
        values[target.id] = value.value
    return {name: value for name, value in values.items() if assignment_counts[name] == 1}


def _registered_kind_slugs(path: Path) -> list[tuple[int, str]]:
    """``(lineno, slug)`` for every ``register(<kind>, ...)`` call in path.

    Both ``obj.register(...)`` and bare ``register(...)`` are matched; the
    first positional argument must be a literal string or a module constant
    bound to one (see :func:`_module_constant_strings`). Dispatch-style
    ``register`` calls take classes or functions, so the string-argument
    shape is registry-kind shaped and safe to read as a kind claim.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    constants = _module_constant_strings(tree)
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
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((node.lineno, first.value))
        elif isinstance(first, ast.Name) and first.id in constants:
            found.append((node.lineno, constants[first.id]))
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
@pytest.mark.ac("SPEC-092926-7a02/AC-1")
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


@pytest.mark.ac("SPEC-092926-7a02/AC-1")
def test_fence_detects_a_synthetic_competing_registration(tmp_path: Path) -> None:
    """The fence trips on a product-side ``Goal`` kind and nothing else.

    A guard that cannot fire is decoration. The violation file registers a
    competing ``Goal`` ontology kind exactly the way a stray product module
    would; the constant-backed violation file uses the repository's real
    idiom (``GOAL_KIND = 'goal'`` passed to ``register``, as the canonical
    Rubric does with ``RUBRIC_KIND``) so the fence cannot be dodged by
    hoisting the slug into a constant; the control file registers a
    non-canonical kind and must pass.
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
    violating_via_constant = tmp_path / "product_goal_kind.py"
    violating_via_constant.write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "\n"
        "GOAL_KIND = 'goal'\n"
        "\n"
        "\n"
        "class GoalModel(BaseModel):\n"
        "    title: str\n"
        "\n"
        "\n"
        "def wire(registry) -> None:\n"
        "    registry.register(GOAL_KIND, GoalModel)\n",
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

    offenders = _competing_registrations([violating, violating_via_constant, control])
    assert len(offenders) == 2, offenders
    assert "product_goal.py" in offenders[0]
    assert "registers canonical loop kind 'Goal'" in offenders[0]
    assert "product_goal_kind.py" in offenders[1]
    assert "registers canonical loop kind 'goal'" in offenders[1]
