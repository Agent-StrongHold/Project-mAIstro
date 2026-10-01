#!/usr/bin/env python3
"""Ratchet parallel HTTP principal shapes (Workspace cutover P0.1 / #53 AC-P1).

Scans production Python under ``packages/*/src`` and flat application backends
for:

  * subscript or ``.get`` access to ``request.state.user`` (dict-shaped principal)
  * concrete classes named like ``*Principal`` / ``*User`` / ``*Identity`` that
    expose ``role`` or ``roles`` outside the canonical owner module

Baseline: ``quality/principal-identity-baseline.json``. A new violation fails CI;
a fixed violation must drop its baseline row.

The comparison ledger is resolved from the trusted base revision
(``scripts/ratchet_provenance.py``), not the candidate tree: a commit that
added a violation and the baseline row blessing it in the same change could
otherwise approve its own regression (#542, #319). The worktree copy remains
the bookkeeping oracle — a row naming a violation that no longer exists must
be pruned.

Run: ``python scripts/check-principal-identity.py``
Bank: ``python scripts/check-principal-identity.py --write-baseline``
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "quality" / "principal-identity-baseline.json"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"

SCAN_ROOTS = (
    ROOT / "packages" / "maistro-core" / "src",
    ROOT / "packages" / "maistro-server" / "src",
    ROOT / "packages" / "maistro-canvas" / "src",
    ROOT / "packages" / "maistro-turing" / "src",
    ROOT / "packages" / "hive-conductor" / "backend",
    ROOT / "packages" / "maistro-turing" / "backend",
)

# Modules allowed to define parallel principal-shaped types until migrated.
ALLOWED_PARALLEL_CLASS_FILES = frozenset(
    {
        "packages/maistro-core/src/maistro/identity/principal.py",
        "packages/maistro-core/src/maistro/identity/lifecycle.py",
        "packages/maistro-core/src/maistro/auth/oauth.py",
        "packages/maistro-core/src/maistro/security/sentinel/authz_types.py",
        "packages/maistro-core/src/maistro/types/agent.py",
        "packages/maistro-core/src/maistro/security/_types.py",
        "packages/maistro-core/src/maistro/memory/episodic/sharing.py",
        "packages/maistro-server/src/maistro_server/api/principal.py",
        "packages/hive-conductor/backend/services/governed_model.py",
    }
)

_NAME_PATTERN = re.compile(r"(Principal|User|Identity)$")


@dataclass(frozen=True)
class Violation:
    kind: str
    path: str
    line: int
    detail: str

    def key(self) -> str:
        return f"{self.kind}::{self.path}:{self.line}:{self.detail}"


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            rel = _rel(path)
            if "/tests/" in f"/{rel}/" or rel.endswith("/tests/conftest.py"):
                continue
            files.append(path)
    return files


def _is_state_user(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "state"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "request"
        and node.attr == "user"
    )


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rel = _rel(path)
        self.violations: list[Violation] = []

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_state_user(node.value):
            self.violations.append(
                Violation(
                    "dict_user_subscript",
                    self.rel,
                    node.lineno,
                    "request.state.user[...]",
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _is_state_user(node.func.value)
        ):
            self.violations.append(
                Violation(
                    "dict_user_get",
                    self.rel,
                    node.lineno,
                    "request.state.user.get(...)",
                )
            )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self.rel in ALLOWED_PARALLEL_CLASS_FILES:
            return
        if not _NAME_PATTERN.search(node.name):
            return
        role_fields = _class_role_fields(node)
        if role_fields:
            self.violations.append(
                Violation(
                    "parallel_principal_class",
                    self.rel,
                    node.lineno,
                    f"class {node.name} defines {', '.join(sorted(role_fields))}",
                )
            )
        self.generic_visit(node)


def _class_role_fields(node: ast.ClassDef) -> set[str]:
    fields: set[str] = set()
    for stmt in node.body:
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id in {"role", "roles"}
        ):
            fields.add(stmt.target.id)
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id in {"role", "roles"}:
                    fields.add(target.id)
    return fields


def collect_violations() -> list[Violation]:
    found: list[Violation] = []
    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        visitor = _Visitor(path)
        visitor.visit(tree)
        found.extend(visitor.violations)
    return sorted(found, key=lambda item: (item.kind, item.path, item.line, item.detail))


def _provenance() -> ModuleType:
    """Load the shared trusted-base resolver (``scripts/ratchet_provenance.py``)."""
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def _load_tolerated(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    tolerated = payload.get("tolerated")
    if not isinstance(tolerated, dict):
        return {}
    return {str(key): str(value) for key, value in tolerated.items()}


def _load_baseline() -> dict[str, str]:
    """Candidate ledger (worktree): the bookkeeping oracle for stale-row pruning."""
    if not BASELINE.is_file():
        return {}
    return _load_tolerated(json.loads(BASELINE.read_text(encoding="utf-8")))


def _trusted_baseline() -> dict[str, str]:
    """Ledger at the merge base: the oracle NEW violations are judged against."""
    ref = _provenance().resolve_baseline(BASELINE, root=ROOT)
    return _load_tolerated(ref.loads(default={"tolerated": {}}))


def audit() -> tuple[list[Violation], list[str], list[str]]:
    violations = collect_violations()
    trusted = _trusted_baseline()
    candidate = _load_baseline()
    current = {item.key(): item.detail for item in violations}
    new_keys = sorted(set(current) - set(trusted))
    stale_keys = sorted(set(candidate) - set(current))
    new_violations = [item for item in violations if item.key() in new_keys]
    return new_violations, stale_keys, sorted(candidate.keys())


def write_baseline(violations: list[Violation]) -> None:
    payload = {
        "_comment": (
            "Parallel HTTP principal debt for P0.1. New violations fail CI; "
            "fixed violations must delete their row."
        ),
        "tolerated": {item.key(): item.detail for item in violations},
    }
    BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current violation set as the tolerated baseline",
    )
    args = parser.parse_args()

    violations = collect_violations()
    if args.write_baseline:
        write_baseline(violations)
        print(f"wrote {len(violations)} tolerated violation(s) to {BASELINE.relative_to(ROOT)}")
        return 0

    try:
        prov = _provenance()
        new_violations, stale_keys, tolerated_keys = audit()
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"scanned principal identity surface: {len(violations)} current violation(s)")
    if tolerated_keys:
        print(f"tolerated (baselined): {len(tolerated_keys)}")
        for key in tolerated_keys[:10]:
            print(f"  · {key}")
        if len(tolerated_keys) > 10:
            print(f"  · … and {len(tolerated_keys) - 10} more")

    failures: list[str] = []
    if new_violations:
        failures.extend(f"NEW  {item.key()}" for item in new_violations)
    if stale_keys:
        failures.extend(f"STALE {key} (fixed — delete from baseline)" for key in stale_keys)

    if failures:
        print(f"\nFAIL: {len(failures)} principal-identity ratchet problem(s):\n")
        print("\n".join(failures))
        return 1

    print("ok: no new principal-identity violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
