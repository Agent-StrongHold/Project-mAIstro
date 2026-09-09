#!/usr/bin/env python3
"""Fail on any mutation of the product agent roster outside its one service.

`stores.agents` is a durable product projection -- a card index the Conductor
shows and the pulse resolves against, not an execution authority (the runtime
roster is `container.agents`, built by maistro's factory). After #840 exactly
one module may mutate it: `services/agent_materialization.py`. Every producer
-- CRUD routes, Forge, chat tools, the workspace cascade, boot
materialization -- funnels through that service. Four independent writer
families mutating the same roster the runtime never saw is the defect this
gate makes structurally impossible to reintroduce, the same way
check-wiring-reads.py gates DI wiring.

AST-based over production code, it flags four shapes:

  1. any mutation of `stores.agents` outside the service -- item assignment
     (including augmented), item deletion, or a mutating call (`pop` /
     `popitem` / `update` / `clear` / `setdefault`). Reads are free: `.get` /
     `.values` / iteration / membership never flag.
  2. any rebinding of a container's agent map (`container.agents = ...`) --
     attribute ASSIGNMENT, not mutation: `create_container` hands
     `_wire_hierarchy` the same dict object and the hierarchy closure captures
     that object, so assigning a fresh dict silently orphans every
     hierarchical resolution (the #840 Slice 1 bug). In-place `clear()` +
     `update()` is the correct pattern and never flags. maistro-server's
     `main.py` assignment is the one documented exception (ADR-082426-2192
     defers that roster decision).
  3. inside the module that DEFINES the agents store (`stores.py`, detected
     by its `agents = ModelStore("agents", ...)` assignment), any bare-name
     mutation of it outside `_seed*` functions. The definition site is its
     own boundary for the demo-mode seed only; a new rogue writer there must
     fail just as loudly as one anywhere else.
  4. `from stores import agents` anywhere outside the service -- the alias
     that hides a mutation from rule 1's spelling exists only to enable one.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The one module permitted to mutate `stores.agents`.
SERVICE = "packages/hive-conductor/backend/services/agent_materialization.py"

#: Documented exceptions to the container-agents rebinding rule.
CONTAINER_ASSIGN_EXCEPTIONS = frozenset(
    {
        # maistro-server binds its single synthetic agent post-construction;
        # ADR-082426-2192 defers its roster decision.
        "packages/maistro-server/src/maistro_server/main.py",
    }
)

#: Store-mutating method calls.
MUTATING_METHODS = frozenset({"pop", "popitem", "update", "clear", "setdefault"})


@dataclass(frozen=True)
class Violation:
    """One flagged write site, rendered file:line for the gate's output."""

    path: str
    line: int
    detail: str

    def render(self) -> str:
        return f"  {self.path}:{self.line} {self.detail}"


def _production_python_files(root: Path) -> list[Path]:
    """Every production module, by the same rule check-wiring-reads.py uses."""
    files: list[Path] = []
    for base in [*root.glob("packages/*/src"), *root.glob("packages/*/backend")]:
        for path in base.rglob("*.py"):
            rel = path.relative_to(base)
            if "tests" in rel.parts or path.name.startswith("test_"):
                continue
            files.append(path)
    return sorted(files)


def _relative(path: Path, root: Path) -> str:
    """Repo-relative when inside the repo, absolute when a test redirects it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _is_stores_agents(node: ast.AST) -> bool:
    """`stores.agents`, spelled through the module (the only spelling in use)."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "agents"
        and isinstance(node.value, ast.Name)
        and node.value.id == "stores"
    )


def _defines_agents_store(tree: ast.Module) -> bool:
    """Whether this module defines THE agents store (`agents = ModelStore(...)`)."""
    for node in tree.body:
        value = None
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "agents" for target in node.targets
            )
        ) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "agents"
            and node.value is not None
        ):
            value = node.value
        if value is not None and "modelstore" in ast.unparse(value).lower():
            return True
    return False


def _inside_seed_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether every enclosing function of `node` is a `_seed*` demo seeder."""
    current = parents.get(node)
    enclosing: list[str] = []
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            enclosing.append(current.name)
        current = parents.get(current)
    return bool(enclosing) and all(name.startswith("_seed") for name in enclosing)


def _is_bare_agents(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "agents"


def _write_through_violation(
    node: ast.expr,
    parents: dict[ast.AST, ast.AST],
    what: str,
    rel: str,
) -> Violation | None:
    """The violation for a subscript assignment/deletion or mutating call on
    `node`, or None when this node is only read through. Subscript context
    separates the writes (Store/Del) from reads like `row = stores.agents[k]`
    (Load), which never flag."""
    parent = parents.get(node)
    if isinstance(parent, ast.Subscript):
        store_ctx = isinstance(parent.ctx, ast.Store)
        del_ctx = isinstance(parent.ctx, ast.Del)
        if not (store_ctx or del_ctx):
            return None
        grand = parents.get(parent)
        if store_ctx and isinstance(grand, ast.Assign | ast.AugAssign):
            return Violation(rel, node.lineno, f"item-assigns {what} outside the service")
        if del_ctx and isinstance(grand, ast.Delete):
            return Violation(rel, node.lineno, f"deletes from {what} outside the service")
        return None
    if (
        isinstance(parent, ast.Attribute)
        and parent.attr in MUTATING_METHODS
        and isinstance(parents.get(parent), ast.Call)
    ):
        return Violation(rel, node.lineno, f"calls .{parent.attr}() on {what} outside the service")
    return None


def _store_violation(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
    *,
    defines_store: bool,
    rel: str,
) -> Violation | None:
    """The violation for one node that spells the agents store, if it mutates."""
    if _is_stores_agents(node):
        if rel == SERVICE:
            return None
        assert isinstance(node, ast.expr)
        return _write_through_violation(node, parents, "stores.agents", rel)
    if defines_store and _is_bare_agents(node):
        if _inside_seed_function(node, parents):
            return None
        assert isinstance(node, ast.expr)
        return _write_through_violation(node, parents, "the agents store (non-seed site)", rel)
    return None


def _alias_import_violation(node: ast.AST, rel: str) -> Violation | None:
    """`from stores import agents` outside the service -- the alias that hides
    a mutation from rule 1's spelling."""
    if (
        isinstance(node, ast.ImportFrom)
        and node.module == "stores"
        and rel != SERVICE
        and any(alias.name == "agents" for alias in node.names)
    ):
        return Violation(
            path=rel,
            line=node.lineno,
            detail=(
                "imports the agents store by name; read through the `stores` "
                "module -- importing it by name exists to hide mutations from "
                "this gate"
            ),
        )
    return None


def _rebind_violations(node: ast.AST, rel: str) -> list[Violation]:
    """Rebindings of a container's agent map in one Assign/AugAssign."""
    if not isinstance(node, ast.Assign | ast.AugAssign):
        return []
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    found: list[Violation] = []
    for target in targets:
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "agents"
            and "container" in ast.unparse(target.value).lower()
            and rel not in CONTAINER_ASSIGN_EXCEPTIONS
        ):
            found.append(
                Violation(
                    path=rel,
                    line=node.lineno,
                    detail=(
                        f"rebinds `{ast.unparse(target.value)}.agents` -- mutate the "
                        "wired dict in place; the hierarchy closure captured the "
                        "original object"
                    ),
                )
            )
    return found


def _file_violations(path: Path, root: Path) -> list[Violation]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    rel = _relative(path, root)
    violations: list[Violation] = []
    parents: dict[ast.AST, ast.AST] = {
        child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }
    defines_store = _defines_agents_store(tree)
    for node in ast.walk(tree):
        violation = _store_violation(node, parents, defines_store=defines_store, rel=rel)
        if violation is not None:
            violations.append(violation)
        violation = _alias_import_violation(node, rel)
        if violation is not None:
            violations.append(violation)
        violations.extend(_rebind_violations(node, rel))
    return violations


def find_violations(root: Path = ROOT) -> list[Violation]:
    """Every agent-roster write outside the one permitted service."""
    violations: list[Violation] = []
    for path in _production_python_files(root):
        violations.extend(_file_violations(path, root))
    return violations


def main(argv: list[str]) -> int:
    root = ROOT
    if "--root" in argv:
        root = Path(argv[argv.index("--root") + 1]).resolve()
    violations = find_violations(root)
    if violations:
        print(
            f"FAIL: {len(violations)} agent-roster write(s) outside {SERVICE}:\n",
            file=sys.stderr,
        )
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        print(
            "\n`stores.agents` has exactly one writer: the materialization\n"
            "service. Route the write through it (upsert/update/delete\n"
            "definition, manifest materialization) so the Warden scan,\n"
            "deterministic ids, workspace tagging, and provenance apply.\n"
            "Rebinding `container.agents` orphans the hierarchy closure:\n"
            "mutate the wired dict in place.",
            file=sys.stderr,
        )
        return 1
    print(
        "Agent store write path OK: stores.agents is mutated only by "
        "services/agent_materialization.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
