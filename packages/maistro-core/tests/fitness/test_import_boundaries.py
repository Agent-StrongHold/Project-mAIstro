"""Architecture fitness functions: canonical ownership and import boundaries.

quality.yml Pillar 7 runs this suite as a blocking gate. These assertions are
ratchets against architectural regression, not aspirations.
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

# #36 invariant 6: compatibility owners must never silently read as canonical.
# A direct public type alias is the concrete shape this repository has today.
# Every allowed identity is reviewed here and must also be explicitly described
# as compatibility-only in its source file. A new alias is therefore a red build
# until somebody decides whether it is canonical, compatibility-only, or should
# not exist.
_COMPATIBILITY_ALIAS_LEDGER = frozenset(
    {
        "builders/dag.py::GraphSpec=GraphConfig",
        "types/config.py::MaistroConfig=AgentConfig",
        "types/errors.py::MaistroError=AgentError",
        "types/errors.py::StrongholdError=AgentError",
        "workspaces/model.py::WorkspaceMember=WorkspaceMembership",
    }
)
_COMPATIBILITY_BANNERS = ("Backwards compat aliases", "Backward-compatible alias")


def _iter_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _imported_roots(path: Path, *, module_level_only: bool) -> set[str]:
    """Top-level module names imported by ``path``.

    Uses the AST rather than a regex so that strings, comments and docstrings
    mentioning a package name cannot produce a false violation.
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
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# Statement types that can wrap an import at module scope. Their bodies still
# execute at import time, so an import inside one is a module-level import.
_MODULE_SCOPE_WRAPPERS = (ast.If, ast.Try, ast.With, ast.For, ast.While)


def _module_scope_nodes(tree: ast.Module) -> list[ast.stmt]:
    """Statements that execute at import time, excluding functions/classes."""
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


def _looks_like_public_type_name(name: str) -> bool:
    """Return whether ``name`` looks like a public class/type identity.

    ALL_CAPS assignments are constants, not type-owner aliases. Keeping this
    predicate deliberately narrow prevents the architecture gate from silently
    expanding into a generic assignment linter.
    """
    return bool(name) and name[0].isupper() and not name.isupper()


def _public_direct_aliases(root: Path) -> dict[str, Path]:
    """Return direct public type aliases as stable path/name identities.

    `OldName = CanonicalName` is the compatibility-owner shape #36 found. We
    intentionally do not treat constants, imports, `TypeAlias` expressions or
    generic assignments as aliases: the gate is narrow enough to be trusted.
    """
    aliases: dict[str, Path] = {}
    for py in _iter_python_files(root):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Name):
                continue
            if not _looks_like_public_type_name(target.id) or not _looks_like_public_type_name(
                node.value.id
            ):
                continue
            rel = py.relative_to(root).as_posix()
            aliases[f"{rel}::{target.id}={node.value.id}"] = py
    return aliases


def _compatibility_alias_violations(root: Path) -> list[str]:
    """Refuse unreviewed, stale, or unbannered compatibility-owner aliases."""
    aliases = _public_direct_aliases(root)
    found = set(aliases)
    violations = [
        f"unreviewed public alias: {item}"
        for item in sorted(found - _COMPATIBILITY_ALIAS_LEDGER)
    ]
    violations.extend(
        f"stale compatibility alias ledger entry: {item}"
        for item in sorted(_COMPATIBILITY_ALIAS_LEDGER - found)
    )
    for identity in sorted(found & _COMPATIBILITY_ALIAS_LEDGER):
        source = aliases[identity].read_text(encoding="utf-8")
        if not any(banner in source for banner in _COMPATIBILITY_BANNERS):
            violations.append(f"compatibility alias is not bannered: {identity}")
    return violations


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_core_does_not_import_applications() -> None:
    """Core stays product-agnostic and compatibility aliases stay explicit."""
    assert _CORE_SRC.is_dir(), f"expected core source tree at {_CORE_SRC}"
    violations = _violations(_CORE_SRC, _FORBIDDEN_FOR_CORE)
    assert not violations, "maistro-core reverse-dependency violation(s):\n" + "\n".join(violations)

    compatibility = _compatibility_alias_violations(_CORE_SRC)
    assert not compatibility, "canonical/compatibility owner violation(s):\n" + "\n".join(compatibility)


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_core_never_imports_an_application_at_any_scope() -> None:
    """Applications are off-limits to core even behind a guard."""
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
    """The detectors themselves fail on planted regressions."""
    planted = tmp_path / "pkg"
    planted.mkdir()
    (planted / "offender.py").write_text("from hive import something\n", encoding="utf-8")
    (planted / "innocent.py").write_text(
        '"""A docstring mentioning hive and maistro_server."""\nimport os\n',
        encoding="utf-8",
    )
    (planted / "guarded.py").write_text(
        "def go():\n    try:\n        from hive import thing\n    except ImportError:\n"
        "        thing = None\n    return thing\n",
        encoding="utf-8",
    )
    (planted / "gated.py").write_text(
        "try:\n    import hive\nexcept ImportError:\n    hive = None\n",
        encoding="utf-8",
    )

    module_level = _violations(planted, frozenset({"hive"}))
    assert len(module_level) == 2, f"expected offender.py and gated.py, got {module_level}"
    assert any("offender.py" in v for v in module_level)
    assert any("gated.py" in v for v in module_level)

    any_scope = _violations(planted, frozenset({"hive"}), module_level_only=False)
    assert len(any_scope) == 3, (
        f"expected offender.py, gated.py and the function-local guarded.py, got {any_scope}"
    )
    assert any("guarded.py" in v for v in any_scope)

    # A public direct alias that was never reviewed is exactly the #36 invariant
    # 6 regression. Planting one proves the gate cannot silently return nothing.
    (planted / "alias.py").write_text("OldCanonical = NewCanonical\n", encoding="utf-8")
    aliases = _public_direct_aliases(planted)
    assert "alias.py::OldCanonical=NewCanonical" in aliases

    # Constants are not compatibility type owners and must stay outside this
    # focused architecture gate.
    (planted / "constants.py").write_text("OLD_CONSTANT = NEW_CONSTANT\n", encoding="utf-8")
    aliases = _public_direct_aliases(planted)
    assert "constants.py::OLD_CONSTANT=NEW_CONSTANT" not in aliases
