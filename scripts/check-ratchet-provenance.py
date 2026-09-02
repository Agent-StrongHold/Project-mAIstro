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
_ROOT_NAMES = frozenset({"ROOT", "REPO", "REPO_ROOT"})

CANDIDATE_AUTHORED: dict[tuple[str, str], str] = {
    ("check-retired-guidance.py", "quality/retired-guidance.json"): (
        "retirement guidance is the reviewed specification being changed"
    ),
    ("check-image-inventory.py", "quality/image-inventory.json"): (
        "image inventory is the reviewed current-tree specification: the checker validates "
        "each Dockerfile's disposition and named build/scan jobs rather than comparing "
        "against a tolerated prior-state oracle"
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
    ("check_ac_state_impl.py", "quality/ratchet-authorizations.json"): (
        "the worktree copy is read only to reject stale or spent grants; permission to lower "
        "an AC-state floor is read separately from the trusted base by authorized_floors()"
    ),
    ("check-branch-independence.py", "quality/branch-independence.json"): (
        "the branch-independence registry is the reviewed representation specification; "
        "the checker separately compares its frozen legacy set against the trusted base"
    ),
    ("check_direct_effects.py", "quality/direct-effect-call-sites.json"): (
        "direct-effect entries are per-call-site reviewed policy: exact AST identities must "
        "match both directions and every live site must state disposition, owner and rationale"
    ),
}

# Adapter values are tooling identities (filename stems), not paths. Keeping the
# identity in the same form as check-reachability.py's tooling graph means the
# dynamic load below is visible as a real edge instead of making live CI tooling
# look unreachable merely because Python loads it from a filename.
TRUSTED_ADAPTERS: dict[tuple[str, str], str] = {
    ("check-citation-status.py", "quality/citation-baseline.json"): (
        "check-citation-status-provenance"
    ),
    ("check-promotion-surface.py", "quality/promotion-surface-baseline.json"): (
        "check-promotion-surface-provenance"
    ),
    ("check-shell-execution.py", "quality/shell-execution.json"): (
        "check-shell-execution-provenance"
    ),
    ("check_contract_markers_impl.py", "quality/contract-markers-baseline.json"): (
        "check-contract-markers-provenance"
    ),
    ("check_enumerations.py", "quality/enumeration-baseline.json"): (
        "check-enumerations-provenance"
    ),
    ("check-reachability.py", "quality/reachability-baseline.json"): (
        "check-reachability-provenance"
    ),
    ("check-reachability-dispositions.py", "quality/reachability-baseline.json"): (
        "check-reachability-dispositions-provenance"
    ),
    ("check-reachability-dispositions.py", "quality/reachability-dispositions.json"): (
        "check-reachability-dispositions-provenance"
    ),
    ("tools/lint_lifecycle.py", "quality/lifecycle-baseline.json"): ("check-lifecycle-provenance"),
}

# These consumers are themselves provenance mechanisms. ac_state_notes.py folds
# a trusted directory through ratchet_provenance; ratchet_provenance.py owns the
# resolver that base-resolves ratchet-authorizations.json, so requiring it to
# import itself would be nonsense rather than stronger enforcement.
SPECIAL_TRUSTED_CONSUMERS = {"ac_state_notes.py", "ratchet_provenance.py"}


@dataclass(frozen=True, order=True)
class Consumer:
    script: str
    ledger: str


def _join(left: str, right: str) -> str:
    if left in {"ROOT", "."}:
        return right
    return str(PurePosixPath(left) / right)


def _is_repo_root_expression(node: ast.AST) -> bool:
    """Recognize ``Path(__file__).resolve().parents[1]`` as the repository root."""
    if not (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == 1
    ):
        return False
    resolved = node.value.value
    if not (
        isinstance(resolved, ast.Call)
        and isinstance(resolved.func, ast.Attribute)
        and resolved.func.attr == "resolve"
    ):
        return False
    path_call = resolved.func.value
    return bool(
        isinstance(path_call, ast.Call)
        and isinstance(path_call.func, ast.Name)
        and path_call.func.id in {"Path", "PurePath"}
        and len(path_call.args) == 1
        and isinstance(path_call.args[0], ast.Name)
        and path_call.args[0].id == "__file__"
    )


def _expr_path(node: ast.AST, env: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _ROOT_NAMES:
            return "ROOT"
        return env.get(node.id)
    if _is_repo_root_expression(node):
        return "ROOT"
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


def _consumer_identity(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return path.name if relative.startswith("scripts/") else relative


def _consumer_path(root: Path, identity: str) -> Path:
    return root / identity if "/" in identity else root / "scripts" / identity


def _consumer_files(root: Path) -> list[Path]:
    files = list((root / "scripts").glob("*.py"))
    tools = root / "tools"
    if tools.is_dir():
        files.extend(tools.glob("*.py"))
    return sorted(files)


def consumers(root: Path = ROOT) -> set[Consumer]:
    result: set[Consumer] = set()
    for path in _consumer_files(root):
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            ledgers = _module_paths(path)
        except (OSError, SyntaxError) as exc:
            raise RuntimeError(f"cannot inventory {path}: {exc}") from exc
        identity = _consumer_identity(path, root)
        result.update(Consumer(identity, ledger) for ledger in ledgers)
    return result


def _uses_trusted_resolver(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    return "ratchet_provenance" in source and (
        "resolve_baseline(" in source
        or "resolve_baseline_dir(" in source
        or "load_authorizations(" in source
    )


def _adapter_filename(adapter_name: str) -> str:
    """Return the on-disk filename for a tooling identity or legacy filename."""
    return adapter_name if adapter_name.endswith(".py") else f"{adapter_name}.py"


def _adapter_problem(root: Path, adapter_name: str) -> str | None:
    filename = _adapter_filename(adapter_name)
    adapter = root / "scripts" / filename
    if not adapter.is_file():
        return f"delegated trusted-base adapter {filename} does not exist"
    if not _uses_trusted_resolver(adapter):
        return f"delegated adapter {filename} does not use ratchet_provenance"
    return None


def stale_mapping_errors(
    live_keys: set[tuple[str, str]],
    mappings: dict[tuple[str, str], str],
    *,
    label: str,
) -> list[str]:
    """Return mappings that name consumers/ledgers the repository no longer has."""
    return [
        f"stale {label} mapping {script} -> {ledger}: {value}"
        for (script, ledger), value in sorted(mappings.items())
        if (script, ledger) not in live_keys
    ]


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
        script = _consumer_path(root, consumer.script)
        if consumer.script in SPECIAL_TRUSTED_CONSUMERS or _uses_trusted_resolver(script):
            continue
        errors.append(
            f"{consumer.script} reads {consumer.ledger} from the candidate tree "
            "without trusted-base resolution or a documented exception"
        )

    # The repository's committed policy maps are themselves inventory. A stale
    # mapping must fail rather than quietly skip the adapter it promised would
    # execute. Synthetic roots used by unit tests intentionally do not inherit
    # the repository's full policy map.
    if root == ROOT:
        errors.extend(
            stale_mapping_errors(live_keys, CANDIDATE_AUTHORED, label="provenance exception")
        )
        errors.extend(stale_mapping_errors(live_keys, TRUSTED_ADAPTERS, label="trusted adapter"))
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
        filename = _adapter_filename(adapter_name)
        adapter = root / "scripts" / filename
        try:
            module = _load_module(adapter, f"_ratchet_adapter_{index}")
            result = int(module.main())
        except Exception as exc:
            failures.append(f"{filename}: could not execute: {type(exc).__name__}: {exc}")
            continue
        if result != 0:
            failures.append(f"{filename}: trusted-base gate returned {result}")
    return failures


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    unknown = [arg for arg in args if arg != "--inventory-only"]
    if unknown:
        print(f"FAIL: unknown argument(s): {' '.join(unknown)}", file=sys.stderr)
        return 2

    errors = violations(ROOT)
    if not errors and "--inventory-only" not in args:
        errors.extend(run_delegated(ROOT))
    if errors:
        print("FAIL: ratchet provenance inventory is incomplete", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    mode = "inventory" if "--inventory-only" in args else "inventory + delegated gates"
    print(f"OK: {len(consumers(ROOT))} quality JSON consumer(s) have explicit provenance ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
