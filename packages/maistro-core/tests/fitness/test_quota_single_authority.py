"""Architecture fitness function: the router cannot pose as a quota enforcer.

#1196 (Invocation-boundary quota enforcement) requires that
RouterEngine.quota_tracker be removed rather than merely unused, so that a
future change cannot casually revive it as a second, non-authoritative
enforcement point. This scans the AST of maistro.router's source rather than
just calling RouterEngine() with no arguments, so a regression that adds a
*new* QuotaTracker-typed attribute or import is caught even if it happens to
default to None.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROUTER_SRC = Path(__file__).resolve().parents[3] / "maistro-core" / "src" / "maistro" / "router"


def _iter_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


#: The module QuotaTracker is defined in. A whole-module import of this
#: (`import maistro.protocols.quota as quota`) is flagged on its own, because
#: the later `quota.QuotaTracker` reference is an ast.Attribute, not a Name —
#: catching only Name/ImportFrom would miss a qualified-attribute revival.
_QUOTA_PROTOCOL_MODULE = "maistro.protocols.quota"


def _quota_tracker_references(path: Path) -> list[str]:
    """Names of any QuotaTracker imports or references found in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == "QuotaTracker" for alias in node.names
        ):
            found.append(f"{path.name}: imports QuotaTracker from {node.module}")
        elif isinstance(node, ast.Import) and any(
            alias.name == _QUOTA_PROTOCOL_MODULE for alias in node.names
        ):
            found.append(f"{path.name}:{node.lineno}: imports {_QUOTA_PROTOCOL_MODULE}")
        elif isinstance(node, ast.Name) and node.id == "QuotaTracker":
            found.append(f"{path.name}:{node.lineno}: references QuotaTracker")
        elif isinstance(node, ast.Attribute) and node.attr == "QuotaTracker":
            found.append(f"{path.name}:{node.lineno}: references a qualified QuotaTracker")
        elif isinstance(node, ast.arg) and node.arg in {"quota_tracker", "_quota"}:
            found.append(f"{path.name}:{node.lineno}: parameter named {node.arg!r}")
    return found


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_router_has_no_quota_tracker_dependency() -> None:
    """maistro.router must not import, type-reference or accept a QuotaTracker.

    Enforcement belongs at the Invocation boundary (#1196), not in the
    router. RouterEngine previously took an unused ``quota_tracker``
    constructor argument that could be mistaken for an enforcement point;
    this gate keeps it from coming back.
    """
    assert _ROUTER_SRC.is_dir(), f"expected router source tree at {_ROUTER_SRC}"
    violations = [
        violation
        for py in _iter_python_files(_ROUTER_SRC)
        for violation in _quota_tracker_references(py)
    ]
    assert not violations, "maistro.router must have no QuotaTracker dependency:\n" + "\n".join(
        violations
    )


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_fitness_detector_catches_a_planted_quota_tracker(tmp_path: Path) -> None:
    """The detector itself fails on a planted regression."""
    planted = tmp_path / "router"
    planted.mkdir()
    (planted / "offender.py").write_text(
        "from maistro.protocols.quota import QuotaTracker\n\n"
        "def wire(quota_tracker: QuotaTracker) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (planted / "innocent.py").write_text(
        '"""A docstring mentioning QuotaTracker and quota_tracker."""\nimport os\n',
        encoding="utf-8",
    )
    # A qualified import under a differently named parameter: `quota_tracker`
    # and `from X import QuotaTracker` are both absent, so only the
    # ast.Import + ast.Attribute checks catch this revival.
    (planted / "qualified_offender.py").write_text(
        "import maistro.protocols.quota as quota\n\n"
        "def wire(tracker: quota.QuotaTracker) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )

    violations = [
        violation
        for py in _iter_python_files(planted)
        for violation in _quota_tracker_references(py)
    ]
    assert any("imports QuotaTracker" in v for v in violations)
    assert any("parameter named 'quota_tracker'" in v for v in violations)
    assert any("imports maistro.protocols.quota" in v for v in violations)
    assert any("qualified QuotaTracker" in v for v in violations)
    assert not any("innocent.py" in v for v in violations)
