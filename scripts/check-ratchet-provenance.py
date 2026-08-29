#!/usr/bin/env python3
"""Fail when a quality/security ledger has no explicit provenance policy (#542, #319).

The dangerous default is a checker reading both its measurement and its comparison
ledger from the candidate tree.  This inventory makes provenance an explicit
property of every Python checker that reads a JSON file under ``quality/``.

The scan is intentionally structural rather than a grep: it resolves simple
``Path`` expressions and module constants, so both ``ROOT / "quality" / ...``
and ``QUALITY / ...`` are visible.  A new ledger consumer therefore fails until
it is classified here and, for trusted-base ratchets, actually calls the shared
``ratchet_provenance`` resolver.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# Candidate-authored files are specifications or evidence whose *change* is the
# reviewed act.  Everything else under quality/*.json is presumed to be a
# comparison oracle and therefore must be base-resolved.
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
}

# AC state is folded from per-branch notes by ac_state_notes.py using
# resolve_baseline_dir.  The generated state/output files are not comparison
# oracles and are intentionally outside this JSON-consumer inventory.
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
    """Resolve the small path-expression language used by repository checkers."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "ROOT":
            return "ROOT"
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _expr_path(node.left, env)
        right = _expr_path(node.right, env)
        if left is None or right is None:
            return None
        return _join(left, right)
    if isinstance(node, ast.Call) and node.args:
        # Path("quality/foo.json") is uncommon but valid and should not evade
        # the inventory merely by changing construction syntax.
        if isinstance(node.func, ast.Name) and node.func.id in {"Path", "PurePath"}:
            return _expr_path(node.args[0], env)
    return None


def _module_paths(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    env: dict[str, str] = {}
    found: set[str] = set()

    # Module constants are enough for these checkers; deliberately do not infer
    # runtime values or execute candidate code while deciding whether it is safe.
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

    # Also catch direct expressions inside functions, e.g. a helper that opens
    # ROOT / "quality" / "x.json" without first assigning a module constant.
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


def violations(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    seen = consumers(root)
    for consumer in sorted(seen):
        key = (consumer.script, consumer.ledger)
        if key in CANDIDATE_AUTHORED:
            continue
        script = root / "scripts" / consumer.script
        if consumer.script in SPECIAL_TRUSTED_CONSUMERS or _uses_trusted_resolver(script):
            continue
        errors.append(
            f"{consumer.script} reads {consumer.ledger} from the candidate tree "
            "without trusted-base resolution or a documented exception"
        )

    # A documented exception that no longer has a matching consumer is stale.
    # Stale policy is dangerous because a future consumer could inherit a reason
    # that was written for a different implementation.
    live_keys = {(c.script, c.ledger) for c in seen}
    for key, reason in sorted(CANDIDATE_AUTHORED.items()):
        if key not in live_keys:
            errors.append(f"stale provenance exception {key[0]} -> {key[1]}: {reason}")
    return errors


def main() -> int:
    errors = violations(ROOT)
    if errors:
        print("FAIL: ratchet provenance inventory is incomplete", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(consumers(ROOT))} quality JSON consumer(s) have explicit provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
