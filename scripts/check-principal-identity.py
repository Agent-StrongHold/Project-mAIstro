#!/usr/bin/env python3
"""Ratchet parallel HTTP principal shapes (Workspace cutover P0.1, #53 AC-P1).

One principal type, ``maistro.identity.Principal``, is meant to cross every
service boundary. This scans production Python under ``packages/*/src`` and the
flat application backends for the two ways that stops being true:

  * ``state_user_access`` -- a file that reads or writes the dict-shaped
    ``<request>.state.user``, directly or through ``getattr``/``setattr``.
    One entry per file; the canonical carrier is ``request.state.principal``.
  * ``parallel_principal_class`` -- a class named ``*Principal``, ``*User`` or
    ``*Identity`` that carries ``role``/``roles``, outside the owner modules.

The tolerated set in ``quality/principal-identity-baseline.json`` is read from
the trusted merge base (docs/ci/RATCHET-PROVENANCE.md). A file or class that is
new relative to that base fails unless ``quality/ratchet-authorizations.json``
already granted it at the base. The candidate ledger must match the tree
exactly, so a fixed entry has to be deleted in the change that fixes it.

Run:  uv run python scripts/check-principal-identity.py
Bank: uv run python scripts/check-principal-identity.py --write-baseline
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
RATCHET = "principal-identity"
METRIC_DEFINITION_VERSION = "1"

SCAN_ROOTS = (
    ROOT / "packages" / "maistro-core" / "src",
    ROOT / "packages" / "maistro-server" / "src",
    ROOT / "packages" / "maistro-canvas" / "src",
    ROOT / "packages" / "maistro-turing" / "src",
    ROOT / "packages" / "hive-conductor" / "backend",
    ROOT / "packages" / "maistro-turing" / "backend",
)

# Owners of principal-shaped types that are not HTTP request principals, or are
# the canonical one. Anything else carrying role/roles is a parallel principal.
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
_ROLE_FIELDS = frozenset({"role", "roles"})


@dataclass(frozen=True)
class Violation:
    kind: str
    path: str
    subject: str
    detail: str

    def key(self) -> str:
        return f"{self.kind}::{self.path}" + (f"::{self.subject}" if self.subject else "")


def _provenance() -> ModuleType:
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


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.relative_to(root).parts or "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _is_state_user(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "user"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "state"
    )


def _is_state_attr_call(node: ast.Call) -> bool:
    """``getattr(x.state, "user", ...)`` / ``setattr(x.state, "user", ...)``."""
    return (
        isinstance(node.func, ast.Name)
        and node.func.id in {"getattr", "setattr", "hasattr"}
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "state"
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "user"
    )


def _role_fields(node: ast.ClassDef) -> set[str]:
    fields: set[str] = set()
    for stmt in node.body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        elif isinstance(stmt, ast.Assign):
            targets = stmt.targets
        fields.update(t.id for t in targets if isinstance(t, ast.Name) and t.id in _ROLE_FIELDS)
    return fields


def scan_source(rel: str, source: str) -> list[Violation]:
    tree = ast.parse(source, filename=rel)
    accesses = 0
    found: list[Violation] = []
    for node in ast.walk(tree):
        if _is_state_user(node) or (isinstance(node, ast.Call) and _is_state_attr_call(node)):
            accesses += 1
        elif (
            isinstance(node, ast.ClassDef)
            and rel not in ALLOWED_PARALLEL_CLASS_FILES
            and _NAME_PATTERN.search(node.name)
            and (fields := _role_fields(node))
        ):
            found.append(
                Violation(
                    "parallel_principal_class",
                    rel,
                    node.name,
                    f"class {node.name} defines {', '.join(sorted(fields))}",
                )
            )
    if accesses:
        found.append(
            Violation("state_user_access", rel, "", f"{accesses} dict-shaped user access(es)")
        )
    return found


def collect_violations() -> tuple[list[Violation], int]:
    """Every violation in the tree, and how many files were scanned."""
    files = _iter_python_files()
    found: list[Violation] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            found.extend(scan_source(_rel(path), source))
        except SyntaxError:
            continue
    return sorted(found, key=lambda item: item.key()), len(files)


def _tolerated(payload: object) -> dict[str, str]:
    tolerated = payload.get("tolerated") if isinstance(payload, dict) else None
    return dict(tolerated) if isinstance(tolerated, dict) else {}


def compare(
    current: set[str], candidate: set[str], trusted: set[str], authorized: set[str]
) -> list[str]:
    """Failures for a measurement judged against the trusted and candidate ledgers."""
    added = current - trusted
    failures = [
        f"{key}: NEW parallel principal surface absent from the trusted base and not "
        "previously authorized"
        for key in sorted(added - authorized)
    ]
    failures.extend(
        f"{key}: authorized new entry is not recorded in the candidate ledger"
        for key in sorted((added & authorized) - candidate)
    )
    failures.extend(
        f"{key}: current violation missing from candidate ledger"
        for key in sorted(current - candidate)
    )
    failures.extend(
        f"{key}: fixed -- delete it from the candidate ledger"
        for key in sorted(candidate - current)
    )
    return failures


def write_baseline(violations: list[Violation]) -> None:
    payload = {
        "_comment": (
            "Parallel HTTP principal debt for Workspace cutover P0.1 (#53). Judged "
            "against the trusted merge base; a fixed entry must be deleted here."
        ),
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "tolerated": {item.key(): item.detail for item in violations},
    }
    BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record the current violation set in the candidate ledger",
    )
    args = parser.parse_args()

    violations, scanned = collect_violations()
    if args.write_baseline:
        write_baseline(violations)
        print(f"wrote {len(violations)} violation(s) to {BASELINE.relative_to(ROOT)}")
        return 0

    current = {item.key() for item in violations}
    candidate_payload = (
        json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    )
    candidate = set(_tolerated(candidate_payload))

    prov = _provenance()
    try:
        prov.require_measurement(scanned, ratchet=RATCHET, what="production Python files")
        trusted_ref = prov.resolve_baseline(BASELINE, root=ROOT)
        trusted_payload = trusted_ref.loads(default={})
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=trusted_payload.get("metric_definition_version")
            if isinstance(trusted_payload, dict)
            else None,
            ratchet=RATCHET,
            baseline=trusted_ref,
        )
        trusted = set(_tolerated(trusted_payload))
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted)} tolerated violations",
            new_value=f"{len(current)} current violations",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{key}: {authorized[key]}"
                for key in sorted(current - trusted)
                if key in authorized
            ),
        ).render()
    )
    for item in violations:
        print(f"  tolerated · {item.key()} -- {item.detail}")

    failures = compare(current, candidate, trusted, set(authorized))
    if failures:
        print(f"\nFAIL: {len(failures)} principal-identity ratchet problem(s):\n", file=sys.stderr)
        print("\n".join(f"  - {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"ok: {len(current)} tolerated principal-identity violation(s), none new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
