"""Architecture fitness functions: import-direction boundaries.

quality.yml Pillar 7 has always declared these; until now the step guarded on
this directory's existence and emitted a warning when it was absent, so the
pillar passed green without asserting anything.

These are the boundaries ADR-019 relies on for the Stronghold split: maistro-core
is the product-agnostic runtime that downstream products import, so it must never
import *back* into an application or a sibling ability package. A violation here
is not a style problem — it makes core un-importable for any consumer that does
not also ship the app it reached into.

Assertions are deliberately narrow and currently true; they are a ratchet against
regression, not an aspiration.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CORE_SRC = Path(__file__).resolve().parents[3] / "maistro-core" / "src" / "maistro"
_CANVAS_SRC = Path(__file__).resolve().parents[3] / "maistro-canvas" / "src" / "maistro_canvas"

# Applications and sibling ability packages. maistro-core must not import any of
# them: it is the substrate they are built on (ADR-019 canonical source split).
_FORBIDDEN_FOR_CORE = frozenset(
    {
        "maistro_server",
        "maistro_canvas",
        "maistro_turing",
        "maistro_rsi",
        "maistro_design",
        "maistro_evolve",
        "maistro_bootstrap",
        "hive",
        "backend",
    }
)

# maistro-canvas is a standalone ability (CLAUDE.md design decision 8): it may
# depend on maistro-core, but never on an application.
_FORBIDDEN_FOR_CANVAS = frozenset({"hive", "backend", "maistro_server"})


def _iter_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _imported_roots(path: Path, *, module_level_only: bool) -> set[str]:
    """Top-level module names imported by ``path``.

    Uses the AST rather than a regex so that strings, comments and docstrings
    mentioning a package name cannot produce a false violation — Warden's own
    pattern fixtures contain such strings.

    ``module_level_only`` restricts the scan to imports that execute at import
    time. That distinction is the whole point: a *module-level* import of an
    optional package makes maistro-core un-importable for anyone who did not
    install it, whereas a guarded, function-local import behind an optional
    extra is the documented plugin pattern. `maistro/cli/_install.py:20` and
    `_builders_tui.py:160-163` are exactly that — `maistro-bootstrap[builders]`
    is declared in the `builders` extra (maistro-core/pyproject.toml:49-53) and
    both call sites import inside a function under try/except.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not expected
        return set()

    nodes = _module_scope_nodes(tree) if module_level_only else list(ast.walk(tree))
    roots: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        # level > 0 is a relative import — always within the package.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# Statement types that can wrap an import at module scope. Their bodies still
# execute at import time, so an import inside one is a module-level import.
_MODULE_SCOPE_WRAPPERS = (ast.If, ast.Try, ast.With, ast.For, ast.While)


def _module_scope_nodes(tree: ast.Module) -> list[ast.stmt]:
    """Statements that execute at import time.

    Descends into module-scope ``if`` / ``try`` / ``with`` / loop bodies, but
    never into a function or class body. Scanning ``tree.body`` alone was not
    enough: for

        try:
            import maistro_canvas
        except ImportError:
            maistro_canvas = None

    ``tree.body`` holds only the ``Try`` node, so the ``Import`` was invisible
    and a feature-gated top-level import of a sibling package would sail past
    this suite while still breaking `import maistro` for any consumer that had
    not installed that package. A ``try/except ImportError`` at module scope is
    exactly the shape that bug takes in the wild, which is why it must be
    caught here and a *function-local* one must not.
    """
    out: list[ast.stmt] = []
    stack: list[ast.stmt] = list(tree.body)
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, _MODULE_SCOPE_WRAPPERS):
            stack.extend(node.body)
            stack.extend(getattr(node, "orelse", []))
            stack.extend(getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                stack.extend(handler.body)
    return out


def _violations(
    root: Path, forbidden: frozenset[str], *, module_level_only: bool = True
) -> list[str]:
    found: list[str] = []
    for py in _iter_python_files(root):
        offenders = _imported_roots(py, module_level_only=module_level_only) & forbidden
        for offender in sorted(offenders):
            found.append(f"{py.relative_to(root.parents[2])} imports {offender}")
    return found


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_core_does_not_import_applications() -> None:
    """maistro-core must not import any app or sibling ability package.

    ADR-019: core is product-agnostic. A reverse dependency here would force
    every downstream consumer to install the application core reached into.
    """
    assert _CORE_SRC.is_dir(), f"expected core source tree at {_CORE_SRC}"
    violations = _violations(_CORE_SRC, _FORBIDDEN_FOR_CORE)
    assert not violations, "maistro-core reverse-dependency violation(s):\n" + "\n".join(violations)


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_core_never_imports_an_application_at_any_scope() -> None:
    """Applications are off-limits to core even behind a guard.

    An optional *ability* package (maistro-bootstrap, declared in the `builders`
    extra) may legitimately be imported function-local behind try/except. An
    application never can: there is no configuration in which the shared runtime
    should reach into hive-conductor or maistro-server, guarded or not.
    """
    applications = frozenset({"hive", "backend", "maistro_server"})
    violations = _violations(_CORE_SRC, applications, module_level_only=False)
    assert not violations, "maistro-core imports an application:\n" + "\n".join(violations)


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_canvas_does_not_import_applications() -> None:
    """maistro-canvas is standalone: it may use core, never an application."""
    if not _CANVAS_SRC.is_dir():  # pragma: no cover - canvas always present today
        pytest.skip(f"maistro-canvas source tree not found at {_CANVAS_SRC}")
    violations = _violations(_CANVAS_SRC, _FORBIDDEN_FOR_CANVAS)
    assert not violations, "maistro-canvas reverse-dependency violation(s):\n" + "\n".join(
        violations
    )


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_fitness_detector_catches_a_planted_violation(tmp_path: Path) -> None:
    """The detector must actually fail on a violation.

    Without this, the two assertions above would pass just as happily if
    ``_imported_roots`` silently returned nothing — the exact failure mode that
    let Pillar 7 report green while asserting nothing.
    """
    planted = tmp_path / "pkg"
    planted.mkdir()
    (planted / "offender.py").write_text("from hive import something\n", encoding="utf-8")
    (planted / "innocent.py").write_text(
        '"""A docstring mentioning hive and maistro_server."""\nimport os\n',
        encoding="utf-8",
    )
    # Guarded, function-local: allowed at module scope, caught at any scope.
    (planted / "guarded.py").write_text(
        "def go():\n    try:\n        from hive import thing\n    except ImportError:\n"
        "        thing = None\n    return thing\n",
        encoding="utf-8",
    )

    # A module-scope try/except still executes at import time, so it counts as
    # a module-level import even though tree.body holds only the Try node.
    (planted / "gated.py").write_text(
        "try:\n    import hive\nexcept ImportError:\n    hive = None\n",
        encoding="utf-8",
    )

    module_level = _violations(planted, frozenset({"hive"}))
    assert len(module_level) == 2, f"expected offender.py and gated.py, got {module_level}"
    assert any("offender.py" in v for v in module_level)
    assert any("gated.py" in v for v in module_level), (
        "a module-scope try/except import must be caught: it runs at import time"
    )

    any_scope = _violations(planted, frozenset({"hive"}), module_level_only=False)
    assert len(any_scope) == 3, (
        f"expected offender.py, gated.py and the function-local guarded.py, got {any_scope}"
    )
    assert any("guarded.py" in v for v in any_scope)
