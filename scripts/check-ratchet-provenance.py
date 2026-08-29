#!/usr/bin/env python3
"""Fail when a quality/security ledger has no explicit provenance policy (#542, #319).

The dangerous default is a checker reading both its measurement and its comparison
ledger from the candidate tree. This inventory makes provenance an explicit
property of every Python checker that reads a JSON file under ``quality/``.

Large mature measurement scripts may delegate the trusted-base comparison to a
small adapter instead of being rewritten wholesale. The adapter is part of the
contract: it must itself use ``ratchet_provenance`` and this check executes every
live delegated adapter in required CI, so delegation cannot become a paper-only
classification.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

CANDIDATE_AUTHORED: dict[tuple[str, str], str] = {
    ("check-retired-guidance.py", "quality/retired-guidance.json"): (
        "retirement guidance is the reviewed specification being changed"
    ),
    ("pip_audit_gate.py", "quality/direct-dependency-exceptions.json"): (
        "dependency exceptions are an explicitly reviewed specification"
    ),
    ("check-convergence-matrix.py", "quality/reachability-baseline.json"): (
        "this call site uses reachability only for census attribution; "
        "check-reachability.py owns the blocking debt ratchet"
    ),
    ("check_ac_state_impl.py", "quality/reachability-baseline.json"): (
        "criterion reachability is a measurement input; the blocking reachability ratchet "
        "separately prevents a candidate from deleting an actually-unreachable module to "
        "promote its own AC rung"
    ),
    ("check_ac_state_impl.py", "quality/ac-state.json"): (
        "generated AC-state report output, not a comparison oracle"
    ),
}

TRUSTED_ADAPTERS: dict[tuple[str, str], str] = {
    ("check_enumerations.py", "quality/enumeration-baseline.json"): (
        "check-enumerations-provenance.py"
    ),
    ("check-reachability.py", "quality/reachability-baseline.json"): (
        "check-reachability-provenance.py"
    ),
    ("check-reachability-dispositions.py", "quality/reachability-baseline.json"): (
        "check-reachability-dispositions-provenance.py"
    ),
    ("check-reachability-dispositions.py", "quality/reachability-dispositions.json"): (
        "check-reachability-dispositions-provenance.py"
    ),
}

SPECIAL_TRUSTED_CONSUMERS = {"ac_state_notes.py"}


@dataclass(frozen=True, order=True)
class Consumer:
    script: str
    ledger: str


def _join(left: str, right: str) -> str:
    if left in {"ROOT", "."}:
        return right
    return str(PurePosixPath(left) / right)


def _expr_path(node: ast.AST, env: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in {"ROOT", "REPO"}:
            return "ROOT"
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _expr_path(node.left, env)
        right = _expr_path(node.right, env)
        if left is None or right is None:
            return None
        return _join(left, right)
    if (
        isinstance(node, ast.Call)
        and node.args
        and isinstance(node.func, ast.Name)
        and node.func.id in {"Path", "PurePath"}
    ):
        return _expr_path(node.args[0], env)
    return None


def _module_paths(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    env: dict[str, str] = {}
    found: set[str] = set()

    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        value = statement.value
        resolved = _expr_path(value, env) if value is not None else None
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement.target, ast.expr):
            targets = [statement.target]
        for target in targets:
            if isinstance(target, ast.Name) and resolved is not None:
                env[target.id] = resolved
        if resolved and resolved.startswith("quality/") and resolved.endswith(".json"):
            found.add(resolved)

    for node in ast.walk(tree):
        resolved = _expr_path(node, env)
        if resolved and resolved.startswith("quality/") and resolved.endswith(".json"):
            found.add(resolved)
    return found


def consumers(root: Path = ROOT) -> set[Consumer]:
    script_dir = root / "scripts"
    result: set[Consumer] = set()
    for path in sorted(script_dir.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            ledgers = _module_paths(path)
        except (OSError, SyntaxError) as exc:
            raise RuntimeError(f"cannot inventory {path}: {exc}") from exc
        result.update(Consumer(path.name, ledger) for ledger in ledgers)
    return result


def _uses_trusted_resolver(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    return "ratchet_provenance" in source and (
        "resolve_baseline(" in source or "resolve_baseline_dir(" in source
    )


def _adapter_problem(root: Path, adapter_name: str) -> str | None:
    adapter = root / "scripts" / adapter_name
    if not adapter.is_file():
        return f"delegated trusted-base adapter {adapter_name} does not exist"
    if not _uses_trusted_resolver(adapter):
        return f"delegated adapter {adapter_name} does not use ratchet_provenance"
    return None


def violations(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    seen = consumers(root)
    live_keys = {(c.script, c.ledger) for c in seen}
    checked_adapters: set[str] = set()

    for consumer in sorted(seen):
        key = (consumer.script, consumer.ledger)
        if key in CANDIDATE_AUTHORED:
            continue
        adapter_name = TRUSTED_ADAPTERS.get(key)
        if adapter_name is not None:
            if adapter_name not in checked_adapters:
                problem = _adapter_problem(root, adapter_name)
                if problem:
                    errors.append(problem)
                checked_adapters.add(adapter_name)
            continue
        script = root / "scripts" / consumer.script
        if consumer.script in SPECIAL_TRUSTED_CONSUMERS or _uses_trusted_resolver(script):
            continue
        errors.append(
            f"{consumer.script} reads {consumer.ledger} from the candidate tree "
            "without trusted-base resolution or a documented exception"
        )

    for key, reason in sorted(CANDIDATE_AUTHORED.items()):
        if root == ROOT and key not in live_keys:
            errors.append(f"stale provenance exception {key[0]} -> {key[1]}: {reason}")
    return errors


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def run_delegated(root: Path = ROOT) -> list[str]:
    live_keys = {(c.script, c.ledger) for c in consumers(root)}
    failures: list[str] = []
    seen_adapters: set[str] = set()
    for index, (key, adapter_name) in enumerate(sorted(TRUSTED_ADAPTERS.items())):
        if key not in live_keys or adapter_name in seen_adapters:
            continue
        seen_adapters.add(adapter_name)
        adapter = root / "scripts" / adapter_name
        try:
            module = _load_module(adapter, f"_ratchet_adapter_{index}")
            result = int(module.main())
        except Exception as exc:
            failures.append(f"{adapter_name}: could not execute: {type(exc).__name__}: {exc}")
            continue
        if result != 0:
            failures.append(f"{adapter_name}: trusted-base gate returned {result}")
    return failures


def main() -> int:
    errors = violations(ROOT)
    if not errors:
        errors.extend(run_delegated(ROOT))
    if errors:
        print("FAIL: ratchet provenance inventory is incomplete", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(consumers(ROOT))} quality JSON consumer(s) have explicit provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
