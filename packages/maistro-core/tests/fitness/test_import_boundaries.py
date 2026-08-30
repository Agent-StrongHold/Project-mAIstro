"""Architecture fitness functions: canonical ownership and import boundaries.

quality.yml Pillar 7 runs this suite as a blocking gate. These assertions are
ratchets against architectural regression, not aspirations.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORE_SRC = Path(__file__).resolve().parents[3] / "maistro-core" / "src" / "maistro"
_CANVAS_SRC = Path(__file__).resolve().parents[3] / "maistro-canvas" / "src" / "maistro_canvas"
_COMPATIBILITY_CONTRACTS = _REPO_ROOT / "quality" / "compatibility-contracts.json"

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

# #36 invariant 6 and #461 share one vocabulary/source of truth. Compatibility
# owners are inventoried in quality/compatibility-contracts.json, where each one
# must also carry its migration strategy, window, owner and retirement condition.
_COMPATIBILITY_BANNERS = (
    "Backwards compat aliases",
    "Backward-compatible alias",
    "alias, don't fork",
)
_REQUIRED_COMPATIBILITY_FIELDS = frozenset(
    {
        "identity",
        "scope",
        "persisted_data",
        "strategy",
        "migration",
        "deprecation_window",
        "owner",
        "removal_condition",
        "release_note",
    }
)


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


def _load_compatibility_contracts() -> dict[str, Any]:
    """Load the reviewed compatibility-window and canonical-surface registry."""
    value = json.loads(_COMPATIBILITY_CONTRACTS.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("compatibility contract registry must be a JSON object")
    return value


def _class_fields(path: Path, class_name: str) -> set[str] | None:
    """Return annotated class fields, or None when the canonical class vanished."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return {
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        }
    return None


def _compatibility_policy(
    document: dict[str, Any],
) -> tuple[set[str], set[str], list[str]]:
    """Return allowed strategies plus structural policy violations."""
    policy = document.get("policy")
    if not isinstance(policy, dict):
        return set(), set(), ["compatibility contract registry requires policy object"]
    return (
        set(policy.get("persisted_strategies", [])),
        set(policy.get("non_persisted_strategies", [])),
        [],
    )


def _compatibility_record_violations(
    record: object,
    *,
    index: int,
    seen: set[str],
    persisted_strategies: set[str],
    non_persisted_strategies: set[str],
) -> tuple[str | None, list[str]]:
    """Validate one reviewed compatibility-owner record."""
    violations: list[str] = []
    if not isinstance(record, dict):
        return None, [f"compatibility_aliases[{index}] must be an object"]

    missing = _REQUIRED_COMPATIBILITY_FIELDS - record.keys()
    if missing:
        return None, [
            f"compatibility_aliases[{index}] missing fields: {', '.join(sorted(missing))}"
        ]

    identity = record["identity"]
    if not isinstance(identity, str) or not identity.strip():
        return None, [f"compatibility_aliases[{index}] has invalid identity"]
    if identity in seen:
        violations.append(f"duplicate compatibility identity: {identity}")

    for field in (
        "scope",
        "strategy",
        "migration",
        "deprecation_window",
        "owner",
        "removal_condition",
        "release_note",
    ):
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            violations.append(f"compatibility record {identity} requires non-empty {field}")

    persisted = record["persisted_data"]
    strategy = record["strategy"]
    if not isinstance(persisted, bool):
        violations.append(f"compatibility record {identity} persisted_data must be boolean")
    elif persisted and strategy not in persisted_strategies:
        violations.append(
            f"persisted compatibility record {identity} requires durable migration strategy"
        )
    elif not persisted and strategy not in non_persisted_strategies:
        violations.append(f"compatibility record {identity} has unsupported strategy {strategy}")
    return identity, violations


def _compatibility_alias_violations(
    document: dict[str, Any], root: Path
) -> list[str]:
    """Validate compatibility metadata and reconcile it with source aliases."""
    persisted, non_persisted, violations = _compatibility_policy(document)
    raw_aliases = document.get("compatibility_aliases")
    if not isinstance(raw_aliases, list):
        return violations + ["compatibility_aliases must be a list"]

    reviewed_aliases: set[str] = set()
    for index, record in enumerate(raw_aliases):
        identity, record_violations = _compatibility_record_violations(
            record,
            index=index,
            seen=reviewed_aliases,
            persisted_strategies=persisted,
            non_persisted_strategies=non_persisted,
        )
        violations.extend(record_violations)
        if identity is not None:
            reviewed_aliases.add(identity)

    aliases = _public_direct_aliases(root)
    found_aliases = set(aliases)
    violations.extend(
        f"unreviewed public alias: {item}" for item in sorted(found_aliases - reviewed_aliases)
    )
    violations.extend(
        f"stale compatibility alias registry entry: {item}"
        for item in sorted(reviewed_aliases - found_aliases)
    )
    for identity in sorted(found_aliases & reviewed_aliases):
        source = aliases[identity].read_text(encoding="utf-8")
        if not any(banner in source for banner in _COMPATIBILITY_BANNERS):
            violations.append(f"compatibility alias is not bannered: {identity}")
    return violations


def _canonical_surface_entry_violations(
    surface: object, *, index: int, root: Path, seen: set[str]
) -> list[str]:
    """Validate one canonical identity and its required identity-bearing fields."""
    if not isinstance(surface, dict):
        return [f"canonical_surface[{index}] must be an object"]
    identity = surface.get("identity")
    required_fields = surface.get("required_fields")
    if not isinstance(identity, str) or "::" not in identity:
        return [f"canonical_surface[{index}] has invalid identity"]

    violations: list[str] = []
    if identity in seen:
        violations.append(f"duplicate canonical surface identity: {identity}")
    if not isinstance(required_fields, list) or not all(
        isinstance(field, str) and field for field in required_fields
    ):
        return violations + [f"canonical surface {identity} has invalid required_fields"]

    relative_path, class_name = identity.split("::", 1)
    fields = _class_fields(root / relative_path, class_name)
    if fields is None:
        return violations + [f"canonical type disappeared without migration: {identity}"]
    missing_fields = set(required_fields) - fields
    if missing_fields:
        violations.append(
            f"canonical fields disappeared without migration: {identity}: "
            + ", ".join(sorted(missing_fields))
        )
    return violations


def _canonical_surface_violations(document: dict[str, Any], root: Path) -> list[str]:
    """Refuse silent removal or rename of reviewed canonical identities."""
    surfaces = document.get("canonical_surface")
    if not isinstance(surfaces, list):
        return ["canonical_surface must be a list"]

    violations: list[str] = []
    seen: set[str] = set()
    for index, surface in enumerate(surfaces):
        entry_violations = _canonical_surface_entry_violations(
            surface, index=index, root=root, seen=seen
        )
        violations.extend(entry_violations)
        if isinstance(surface, dict) and isinstance(surface.get("identity"), str):
            seen.add(surface["identity"])
    return violations


def _compatibility_contract_violations(
    root: Path, *, contracts: dict[str, Any] | None = None
) -> list[str]:
    """Refuse silent canonical renames and underspecified compatibility windows."""
    document = contracts if contracts is not None else _load_compatibility_contracts()
    violations: list[str] = []
    if document.get("schema_version") != 1:
        violations.append("compatibility contract registry schema_version must be 1")
    violations.extend(_compatibility_alias_violations(document, root))
    violations.extend(_canonical_surface_violations(document, root))
    return violations


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_core_does_not_import_applications() -> None:
    """Core stays product-agnostic and compatibility contracts stay explicit."""
    assert _CORE_SRC.is_dir(), f"expected core source tree at {_CORE_SRC}"
    violations = _violations(_CORE_SRC, _FORBIDDEN_FOR_CORE)
    assert not violations, "maistro-core reverse-dependency violation(s):\n" + "\n".join(violations)

    compatibility = _compatibility_contract_violations(_CORE_SRC)
    assert not compatibility, "canonical/compatibility owner violation(s):\n" + "\n".join(
        compatibility
    )


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
        '\"\"\"A docstring mentioning hive and maistro_server.\"\"\"\nimport os\n',
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

    # A public direct alias that was never reviewed is exactly the #36/#461
    # regression. The executable contract must reject it, not merely find it.
    (planted / "alias.py").write_text(
        "# Backward-compatible alias\nOldCanonical = NewCanonical\n", encoding="utf-8"
    )
    minimal_contract: dict[str, Any] = {
        "schema_version": 1,
        "policy": {
            "persisted_strategies": ["dual-read"],
            "non_persisted_strategies": ["import-alias"],
        },
        "canonical_surface": [],
        "compatibility_aliases": [],
    }
    compatibility = _compatibility_contract_violations(planted, contracts=minimal_contract)
    assert "unreviewed public alias: alias.py::OldCanonical=NewCanonical" in compatibility

    # A persisted rename cannot claim an import-only alias as its migration.
    minimal_contract["compatibility_aliases"] = [
        {
            "identity": "alias.py::OldCanonical=NewCanonical",
            "scope": "persisted-record",
            "persisted_data": True,
            "strategy": "import-alias",
            "migration": "read the old record",
            "deprecation_window": "one release",
            "owner": "#461",
            "removal_condition": "fixture proves no old rows remain",
            "release_note": "breaking rename",
        }
    ]
    compatibility = _compatibility_contract_violations(planted, contracts=minimal_contract)
    assert any("requires durable migration strategy" in item for item in compatibility)

    # Removing a required canonical field is a red gate until a reviewed
    # migration updates the contract surface.
    (planted / "canonical.py").write_text(
        "class Canonical:\n    keep: str\n", encoding="utf-8"
    )
    minimal_contract["compatibility_aliases"] = []
    minimal_contract["canonical_surface"] = [
        {"identity": "canonical.py::Canonical", "required_fields": ["keep", "removed"]}
    ]
    compatibility = _compatibility_contract_violations(planted, contracts=minimal_contract)
    assert any("canonical fields disappeared without migration" in item for item in compatibility)

    # Constants are not compatibility type owners and must stay outside this
    # focused architecture gate.
    (planted / "constants.py").write_text("OLD_CONSTANT = NEW_CONSTANT\n", encoding="utf-8")
    aliases = _public_direct_aliases(planted)
    assert "constants.py::OLD_CONSTANT=NEW_CONSTANT" not in aliases
