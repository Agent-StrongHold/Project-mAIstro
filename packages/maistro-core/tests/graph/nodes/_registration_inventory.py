"""Statically derived registration inventory and registry identity parity.

Issue #1864: the module-level reconciliation (``_production_registration``)
proves *which registration modules* a guard loaded, but a registry cannot
independently prove its own completeness — nothing tied each registered kind
back to the exact registration expression that production source ships. A
conflated loop or a substituted class would leave the registry silently
smaller or differently bound, and the module-level sweep would prove whatever
the registry happened to hold.

This module derives the expected inventory from source alone and proves the
live registry binds each expected kind to the actual defining class, in the
actual defining module, backed by the actual checkout file.

Fail-closed contract: every registration form the product ships is resolved
(``@register_node`` class decorators, direct ``register_node(Cls)`` calls,
literal registration loops over inline tuples or module-level constants,
aliased and relative imports of the registrar). Any reference the extractor
cannot attribute — dynamic registration arguments, qualified or star-import
registrar access, nested (deferred) registration, ambiguous loop bindings —
raises :class:`UnsupportedRegistration` naming module and line, rather than
shrinking the expected inventory deceptively.

Limits, stated honestly: static analysis is not proof against arbitrary
Python reflection. Identity parity checks four independent witnesses (kind
membership in the registry, class name, defining ``__module__``, and the
method code objects' compiled filename), which a registry entry cannot fake
without also shipping source at the named checkout file — but no static or
object-attribute check can rule out every reflection-based substitution.
Runtime loading (``_production_registration``) remains the authority on what
production actually executes; this module is the authority on what the
checkout source claims.

This module deliberately performs **no node registration** of its own: a
fresh interpreter can import it next to a bare ``maistro.graph.nodes`` load
to prove that a core-only registry fails the parity proof for the reachable
design registrations (#1864's fresh-process case).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: tests/graph/nodes/_registration_inventory.py -> the repository root.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[5]

_REACHABILITY_SCRIPT: Final[Path] = _REPO_ROOT / "scripts" / "check-reachability.py"

#: The ledger ``scripts/check-reachability.py`` ratchets: identities with no
#: import path from any entry point. ``expected_registrations`` excludes them,
#: mirroring ``_import_reachable_registrations``' loading rule.
_REACHABILITY_BASELINE: Final[Path] = _REPO_ROOT / "quality" / "reachability-baseline.json"

#: The module whose ``register_node`` is the only registrar this inventory
#: attributes. Everything else fails closed.
_REGISTRAR_MODULE: Final[str] = "maistro.graph.nodes"
_REGISTRAR_SYMBOL: Final[str] = "register_node"


class UnsupportedRegistration(RuntimeError):
    """A registration reference this inventory cannot attribute.

    Raised instead of silently shrinking the expected inventory: a deceptively
    smaller minimum would let an unattributed registration escape the parity
    proof. The message names the module, the line and the diagnosis.
    """


@dataclass(frozen=True)
class ExpectedRegistration:
    """One registration expression, statically attributed to its source.

    ``file`` is the checkout source file the expression ships in, ``module``
    the importable name of the class's defining module (the file itself),
    ``class_name`` the class the expression registers, and ``kind`` the
    literal (or module-constant) ``kind`` ClassVar that class declares.
    """

    module: str
    file: Path
    class_name: str
    kind: str
    line: int

    @property
    def source(self) -> str:
        return f"{self.module} ({self.file})"


@dataclass(frozen=True)
class _Ref:
    """One registrar reference found in a module's AST."""

    node: ast.AST
    #: "call" (statement-position or loop-body call), "decorator" (bare
    #: registrar name decorating a class), "qualified" (``x.register_node``),
    #: "unbound" (a registrar-named call with no classified import binding),
    #: "bare" (the registrar name referenced as a value).
    form: str
    #: "module" scope (import-time registration) or "nested" (deferred).
    scope: str
    #: The loop-target name when the reference sits inside a module-level
    #: ``for`` whose target binds it, else ``None``.
    loop_target: str | None
    #: The class name when the reference decorates one.
    decorator_of: str | None


@dataclass
class _RegistrarImports:
    """How a module binds the registrar, classified from its import lines.

    ``names`` maps a local alias to the registrar function itself
    (``from maistro.graph.nodes import register_node [as rn]``, including the
    relative ``from . import register_node`` the core leaf modules use).
    ``qualified`` maps a local alias to the registrar module
    (``import maistro.graph.nodes [as g]``); using such an alias is recorded
    but unsupported. ``star`` marks ``from maistro.graph.nodes import *``.
    """

    names: dict[str, None]
    qualified: dict[str, None]
    star: bool


_reachability_module_cache: dict[str, object] = {}


def _load_reachability_module() -> object:
    """Import ``scripts/check-reachability.py`` for its source-universe rules.

    The script is repository machinery, not per-tree data: even a synthetic
    tree under test is classified by the real rules, the way
    ``tests/test_reachability_source_universe.py`` runs the real script against
    tmp trees. A distinct module name keeps this copy out of the reachability
    suite's own when one session collects both.
    """
    cached = _reachability_module_cache.get("module")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("_composition_reachability", _REACHABILITY_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - load mechanism
        raise RuntimeError(f"cannot load reachability script at {_REACHABILITY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _reachability_module_cache["module"] = module
    return module


def _dotted_module(path: Path, root: Path) -> str | None:
    """The importable name of a file under a packaged ``src`` root, or ``None``.

    ``packages/<dist>/src/a/b/mod.py`` becomes ``a.b.mod``; a package
    ``__init__.py`` maps to its package. ``None`` means the registration site
    sits outside every packaged src root — the caller must fail loudly
    rather than silently sweep less.
    """
    parts = path.relative_to(root).parts
    if "src" not in parts:
        return None
    segments = list(parts[parts.index("src") + 1 :])
    if not segments:
        return None
    if segments[-1] == "__init__.py":
        segments = segments[:-1]
    else:
        segments[-1] = segments[-1][: -len(".py")]
    if not segments:
        return None
    return ".".join(segments)


# --- import classification -----------------------------------------------------------


def _resolve_relative(dotted: str, path: Path, level: int, module: str | None) -> str:
    """Resolve ``from <dots> <module> import ...`` to its absolute target."""
    parts = dotted.split(".")
    if path.name != "__init__.py":
        parts = parts[:-1]
    for _ in range(level - 1):
        parts = parts[:-1]
    base = ".".join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _classify_imports(tree: ast.Module, dotted: str, path: Path) -> _RegistrarImports:
    """Classify the module-body import lines that bind the registrar.

    Only direct module-body imports count: an import nested in a conditional
    block is not statically provable as a runtime registrar binding, and a
    module that calls the registrar through one fails closed as unclassified.
    """
    imports = _RegistrarImports(names={}, qualified={}, star=False)
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom):
            _classify_from_import(stmt, dotted, path, imports)
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.name == _REGISTRAR_MODULE:
                    imports.qualified[alias.asname or alias.name] = None
    return imports


def _classify_from_import(
    stmt: ast.ImportFrom, dotted: str, path: Path, imports: _RegistrarImports
) -> None:
    """Classify one ``from ... import`` line's aliases against the registrar."""
    target = (
        stmt.module or ""
        if stmt.level == 0
        else _resolve_relative(dotted, path, stmt.level, stmt.module)
    )
    for alias in stmt.names:
        if target == _REGISTRAR_MODULE:
            if alias.name == "*":
                imports.star = True
            elif alias.name == _REGISTRAR_SYMBOL:
                imports.names[alias.asname or alias.name] = None
        elif f"{target}.{alias.name}" == _REGISTRAR_MODULE:
            imports.qualified[alias.asname or alias.name] = None


# --- reference collection ------------------------------------------------------------

_COMPOUND: Final[tuple[type[ast.stmt], ...]] = (
    ast.If,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    *((ast.TryStar,) if hasattr(ast, "TryStar") else ()),
)


def _classify_call(node: ast.Call, imports: _RegistrarImports) -> str | None:
    """The reference form of a call whose callee names the registrar, else None."""
    func = node.func
    if isinstance(func, ast.Name):
        if func.id in imports.names:
            return "call"
        if func.id == _REGISTRAR_SYMBOL:
            return "unbound"
        return None
    if isinstance(func, ast.Attribute) and func.attr == _REGISTRAR_SYMBOL:
        return "qualified"
    return None


def _scan_expr(
    node: ast.AST,
    out: list[_Ref],
    imports: _RegistrarImports,
    scope: str,
    loop_target: str | None,
    decorator_of: str | None,
    in_decorator: bool = False,
) -> None:
    """Collect registrar references inside an expression tree.

    Anything found in expression position is deferred, not statement-position
    import-time registration: calls inside iterables, lambdas, comprehensions,
    assignments. Only the decorator scanner marks bare names as decorators.
    """
    if isinstance(node, ast.Call):
        form = _classify_call(node, imports)
        if form is not None:
            out.append(_Ref(node, form, scope, loop_target, decorator_of))
            for arg in (*node.args, *node.keywords):
                _scan_expr(arg, out, imports, "nested", None, None)
            return
    elif isinstance(node, ast.Attribute) and node.attr == _REGISTRAR_SYMBOL:
        out.append(_Ref(node, "qualified", scope, loop_target, decorator_of))
        return
    elif (
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and (node.id in imports.names or node.id == _REGISTRAR_SYMBOL)
    ):
        if in_decorator and decorator_of is not None:
            out.append(_Ref(node, "decorator", scope, loop_target, decorator_of))
        else:
            out.append(_Ref(node, "bare", scope, loop_target, None))
        return
    for child in ast.iter_child_nodes(node):
        _scan_expr(child, out, imports, scope, loop_target, decorator_of, in_decorator)


def _statement_expressions(stmt: ast.stmt) -> list[ast.expr]:
    """Every expression a simple statement evaluates.

    Both sides of assignments: a registrar reference can hide in a value
    (``handler = nodes.register_node``) as well as in a call argument.
    """
    exprs: list[ast.expr] = []
    exprs.extend(_condition_expressions(stmt))
    exprs.extend(_binding_expressions(stmt))
    exprs.extend(_flow_expressions(stmt))
    return [expr for expr in exprs if isinstance(expr, ast.expr)]


def _condition_expressions(stmt: ast.stmt) -> list[ast.expr]:
    """Expressions of the condition/with heads a statement can have."""
    if isinstance(stmt, (ast.If, ast.While, ast.Assert)):
        return [stmt.test]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        exprs = [item.context_expr for item in stmt.items]
        exprs.extend(
            item.optional_vars for item in stmt.items if isinstance(item.optional_vars, ast.expr)
        )
        return exprs
    return []


def _binding_expressions(stmt: ast.stmt) -> list[ast.expr]:
    """The bound names and assigned values of an assignment statement."""
    if isinstance(stmt, ast.Assign):
        return [*stmt.targets, stmt.value]
    if isinstance(stmt, ast.AugAssign):
        return [stmt.target, stmt.value]
    if isinstance(stmt, ast.AnnAssign):
        return [stmt.target, stmt.annotation, *([stmt.value] if stmt.value else [])]
    if isinstance(stmt, ast.Delete):
        return list(stmt.targets)
    return []


def _flow_expressions(stmt: ast.stmt) -> list[ast.expr]:
    """The carried values of return/raise statements."""
    if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.expr):
        return [stmt.value]
    if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.expr):
        return [stmt.exc]
    return []


def _collect_scope(
    stmts: list[ast.stmt],
    nested: bool,
    loop_target: str | None,
    imports: _RegistrarImports,
    out: list[_Ref],
    loops: list[ast.For],
) -> None:
    """Walk statements, tagging every registrar reference with its scope.

    Module scope means the reference executes at import time in a
    statically attributable position: a statement-position call, a class
    decorator, or a call inside a module-level ``for`` body bound to that
    loop's target. Function bodies, class bodies and expression positions are
    ``nested`` — deferred registration this inventory refuses to guess about.
    """
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect_function(stmt, imports, out, loops)
        elif isinstance(stmt, ast.ClassDef):
            _collect_class(stmt, nested, imports, out, loops)
        elif isinstance(stmt, _COMPOUND):
            _collect_compound(stmt, nested, loop_target, imports, out, loops)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            _collect_loop(stmt, nested, loop_target, imports, out, loops)
        else:
            _collect_simple(stmt, nested, loop_target, imports, out)


def _collect_function(
    stmt: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: _RegistrarImports,
    out: list[_Ref],
    loops: list[ast.For],
) -> None:
    """A function defers its body; its decorators are nested scope too."""
    for dec in stmt.decorator_list:
        _scan_expr(dec, out, imports, "nested", None, None, in_decorator=True)
    _collect_scope(stmt.body, True, None, imports, out, loops)


def _collect_class(
    stmt: ast.ClassDef,
    nested: bool,
    imports: _RegistrarImports,
    out: list[_Ref],
    loops: list[ast.For],
) -> None:
    """A module-level class's decorators are import-time registrations."""
    for dec in stmt.decorator_list:
        _scan_expr(
            dec,
            out,
            imports,
            "nested" if nested else "module",
            None,
            None if nested else stmt.name,
            in_decorator=True,
        )
    _collect_scope(stmt.body, True, None, imports, out, loops)


def _collect_compound(
    stmt: ast.stmt,
    nested: bool,
    loop_target: str | None,
    imports: _RegistrarImports,
    out: list[_Ref],
    loops: list[ast.For],
) -> None:
    """Headers defer; bodies stay at their enclosing scope."""
    for expr in _statement_expressions(stmt):
        _scan_expr(expr, out, imports, "nested", None, None)
    for body_name in ("body", "orelse", "finalbody"):
        body = getattr(stmt, body_name, None)
        if isinstance(body, list):
            _collect_scope(body, nested, loop_target, imports, out, loops)
    for handler in getattr(stmt, "handlers", []) or []:
        if isinstance(getattr(handler, "type", None), ast.expr):
            _scan_expr(handler.type, out, imports, "nested", None, None)
        _collect_scope(handler.body, nested, loop_target, imports, out, loops)


def _collect_loop(
    stmt: ast.For | ast.AsyncFor,
    nested: bool,
    loop_target: str | None,
    imports: _RegistrarImports,
    out: list[_Ref],
    loops: list[ast.For],
) -> None:
    """Register module-level ``for`` loops; the iterable always defers."""
    _scan_expr(stmt.iter, out, imports, "nested", None, None)
    if not nested and isinstance(stmt, ast.For):
        loops.append(stmt)
        target = stmt.target.id if isinstance(stmt.target, ast.Name) else None
        _collect_scope(stmt.body, nested, target, imports, out, loops)
    else:
        _collect_scope(stmt.body, True, None, imports, out, loops)
    if stmt.orelse:
        _collect_scope(stmt.orelse, nested, loop_target, imports, out, loops)


def _collect_simple(
    stmt: ast.stmt,
    nested: bool,
    loop_target: str | None,
    imports: _RegistrarImports,
    out: list[_Ref],
) -> None:
    """Simple statements: only statement-position calls are attributable.

    In nested scopes even those are deferred; every other expression position
    holds deferred references at best. An unclassified statement-position call
    (``consume(register_node(A))``) is still traversed: registrar references
    inside its arguments are reachable registrations this inventory refuses
    to attribute silently.
    """
    if (
        not nested
        and isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and (form := _classify_call(stmt.value, imports)) is not None
    ):
        out.append(_Ref(stmt.value, form, "module", loop_target, None))
        _scan_call_arguments(stmt.value, out, imports)
        return
    for expr in _statement_expressions(stmt):
        _scan_expr(expr, out, imports, "nested", None, None)
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        form = _classify_call(stmt.value, imports)
        if form is not None:
            out.append(_Ref(stmt.value, form, "nested", None, None))
            _scan_call_arguments(stmt.value, out, imports)
        else:
            _scan_expr(stmt.value, out, imports, "nested", None, None)


def _scan_call_arguments(call: ast.Call, out: list[_Ref], imports: _RegistrarImports) -> None:
    """A call's arguments are evaluated at registration time: deferred."""
    for arg in (*call.args, *call.keywords):
        _scan_expr(arg, out, imports, "nested", None, None)


# --- extraction ----------------------------------------------------------------------


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string constants usable as kind-value aliases."""
    constants: dict[str, str] = {}
    for stmt in tree.body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _module_classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {stmt.name: stmt for stmt in tree.body if isinstance(stmt, ast.ClassDef)}


def _module_assignment(tree: ast.Module, name: str) -> ast.expr | None:
    """The value a module-level assignment binds to ``name``, or None."""
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in stmt.targets
        ):
            return stmt.value
        if isinstance(stmt, ast.AnnAssign) and (
            isinstance(stmt.target, ast.Name) and stmt.target.id == name
        ):
            return stmt.value
    return None


def _literal_class_tuple(
    node: ast.expr, classes: dict[str, ast.ClassDef], dotted: str
) -> list[str]:
    """Class names named by a literal tuple/list expression, or raise."""
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in node.elts:
            if isinstance(elt, ast.Name) and elt.id in classes:
                names.append(elt.id)
            else:
                raise UnsupportedRegistration(
                    f"{dotted}:{node.lineno} literal registration sequence names "
                    "something that is not a class defined in this module"
                )
        return names
    raise UnsupportedRegistration(
        f"{dotted}:{node.lineno} dynamic registration sequence; only a literal "
        "tuple/list of classes defined in this module (or a module constant "
        "naming one) is statically attributable"
    )


def _resolved_class_names(
    node: ast.expr, tree: ast.Module, classes: dict[str, ast.ClassDef], dotted: str
) -> list[str]:
    """Class names a registration argument/iterable resolves to, or raise."""
    if isinstance(node, ast.Name):
        if node.id in classes:
            return [node.id]
        value = _module_assignment(tree, node.id)
        if value is not None:
            return _literal_class_tuple(value, classes, dotted)
    return _literal_class_tuple(node, classes, dotted)


def _class_kind(cls: ast.ClassDef, constants: dict[str, str], dotted: str) -> str:
    """The literal ``kind`` ClassVar a class declares, or fail closed."""
    for stmt in cls.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(stmt, ast.AnnAssign):
            target, value = stmt.target, stmt.value
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        if not (isinstance(target, ast.Name) and target.id == "kind" and value is not None):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            kind = value.value
        elif isinstance(value, ast.Name) and value.id in constants:
            kind = constants[value.id]
        else:
            kind = ""
        if kind:
            return kind
        break
    raise UnsupportedRegistration(
        f"{dotted}:{cls.lineno} class {cls.name} has no `kind` this inventory "
        "can resolve to a non-empty literal string (string literal or module "
        "string constant); dynamic kinds fail closed"
    )


def _reject_ambiguous_loops(
    dotted: str,
    loops: list[ast.For],
    refs: list[_Ref],
    constants: dict[str, str],
    classes: dict[str, ast.ClassDef],
) -> None:
    """Loop bindings that participate in registration must be unambiguous
    before any are resolved: two registration loops sharing a target name
    (or a target shadowing a module-level name) would conflate unrelated
    registrations. Unrelated loops that carry no registrar calls are not
    considered."""
    targets = [
        s.target.id
        for s in loops
        if isinstance(s.target, ast.Name) and _loop_body_refs(refs, s.target.id)
    ]
    duplicated = {name for name in targets if targets.count(name) > 1}
    shadowed = duplicated & (set(constants) | set(classes))
    if duplicated or shadowed:
        raise UnsupportedRegistration(
            f"{dotted}: ambiguous loop bindings for registrar calls — loop "
            f"target(s) {sorted(duplicated)} repeat or shadow module-level names"
        )


def _register_one(
    expected: list[ExpectedRegistration],
    classes: dict[str, ast.ClassDef],
    constants: dict[str, str],
    dotted: str,
    path: Path,
    cls_name: str,
    line: int,
) -> None:
    """Attribute one class registration: kind resolved from its own source."""
    cls = classes[cls_name]
    expected.append(
        ExpectedRegistration(
            module=dotted,
            file=path,
            class_name=cls_name,
            kind=_class_kind(cls, constants, dotted),
            line=line,
        )
    )


def _extract_decorators(
    dotted: str,
    refs: list[_Ref],
    classes: dict[str, ast.ClassDef],
    constants: dict[str, str],
    path: Path,
    expected: list[ExpectedRegistration],
    accounted: set[int],
) -> None:
    """Class decorators: the class is named by the reference itself."""
    for ref in refs:
        if ref.scope != "module":
            continue
        if ref.form == "decorator":
            _register_one(
                expected,
                classes,
                constants,
                dotted,
                path,
                ref.decorator_of or "",
                ref.node.lineno,
            )
            accounted.add(id(ref.node))
        elif ref.form == "call" and ref.decorator_of:
            raise UnsupportedRegistration(
                f"{dotted}:{ref.node.lineno} decorator-form registrar call is "
                "unsupported; the bare `@register_node` is the shipped decorator"
            )


def _loop_body_refs(refs: list[_Ref], target_name: str) -> list[_Ref]:
    """The module-scope, non-decorator calls this loop's target binds."""
    return [
        ref
        for ref in refs
        if ref.scope == "module"
        and ref.form == "call"
        and not ref.decorator_of
        and ref.loop_target == target_name
    ]


def _reject_non_target_call(dotted: str, call: ast.Call, target_name: str) -> None:
    """A loop-body registration must pass exactly the loop target."""
    if (
        len(call.args) != 1
        or call.keywords
        or not isinstance(call.args[0], ast.Name)
        or call.args[0].id != target_name
    ):
        raise UnsupportedRegistration(
            f"{dotted}:{call.lineno} loop-body registrar call does not "
            f"pass exactly the loop target {target_name!r}; ambiguous "
            "loop bindings fail closed"
        )


def _extract_loops(
    dotted: str,
    tree: ast.Module,
    loops: list[ast.For],
    refs: list[_Ref],
    classes: dict[str, ast.ClassDef],
    constants: dict[str, str],
    path: Path,
    expected: list[ExpectedRegistration],
    accounted: set[int],
) -> None:
    """Module-level loops: the call argument must be exactly the loop
    target, and the iterable a literal class tuple (directly or via a
    constant)."""
    for loop in loops:
        if not isinstance(loop.target, ast.Name):
            continue  # non-Name targets leave their calls unaccounted -> fail below
        target_name = loop.target.id
        body_refs = _loop_body_refs(refs, target_name)
        if not body_refs:
            continue  # a loop with no registrar calls is not a registration loop
        iterable = _resolved_class_names(loop.iter, tree, classes, dotted)
        for ref in body_refs:
            _reject_non_target_call(dotted, ref.node, target_name)
            for cls_name in iterable:
                _register_one(expected, classes, constants, dotted, path, cls_name, ref.node.lineno)
            accounted.add(id(ref.node))


def _extract_direct_call(
    dotted: str,
    tree: ast.Module,
    ref: _Ref,
    classes: dict[str, ast.ClassDef],
    constants: dict[str, str],
    path: Path,
    expected: list[ExpectedRegistration],
    accounted: set[int],
) -> None:
    """A direct `register_node(Cls)` statement (or a constant naming one)."""
    call = ref.node
    if len(call.args) != 1 or call.keywords or not isinstance(call.args[0], ast.Name):
        raise UnsupportedRegistration(
            f"{dotted}:{call.lineno} dynamic registration argument; only a "
            "class defined in this module (or a module constant naming one) "
            "is statically attributable"
        )
    for cls_name in _resolved_class_names(call.args[0], tree, classes, dotted):
        _register_one(expected, classes, constants, dotted, path, cls_name, call.lineno)
    accounted.add(id(call))


def _extract_remaining(
    dotted: str,
    tree: ast.Module,
    refs: list[_Ref],
    classes: dict[str, ast.ClassDef],
    constants: dict[str, str],
    path: Path,
    expected: list[ExpectedRegistration],
    accounted: set[int],
) -> None:
    """Remaining module-scope references: direct calls plus every unsupported
    form, each diagnosed explicitly."""
    for ref in refs:
        if id(ref.node) in accounted:
            continue
        if ref.scope != "module":
            raise UnsupportedRegistration(
                f"{dotted}:{ref.node.lineno} registrar reference nested inside "
                "a function/class body is deferred registration; only "
                "import-time registration is attributable, so it fails closed"
            )
        if ref.form == "qualified":
            raise UnsupportedRegistration(
                f"{dotted}:{ref.node.lineno} qualified registrar access "
                "(<module>.register_node) is unsupported; import the registrar "
                "directly (absolute or relative `from ... import register_node`)"
            )
        if ref.form in ("unbound", "bare"):
            raise UnsupportedRegistration(
                f"{dotted}:{ref.node.lineno} unclassified registrar reference: "
                f"{_REGISTRAR_SYMBOL} is not imported from {_REGISTRAR_MODULE} "
                "in this module (star import, re-export chain or local "
                "redefinition); unclassified registrar access fails closed"
            )
        _extract_direct_call(dotted, tree, ref, classes, constants, path, expected, accounted)


def _extract(
    path: Path, dotted: str, tree: ast.Module, imports: _RegistrarImports
) -> list[ExpectedRegistration]:
    """Attribute every registrar reference in the module, or fail closed."""
    constants = _module_constants(tree)
    classes = _module_classes(tree)
    refs: list[_Ref] = []
    loops: list[ast.For] = []
    _collect_scope(tree.body, False, None, imports, refs, loops)
    _reject_ambiguous_loops(dotted, loops, refs, constants, classes)

    expected: list[ExpectedRegistration] = []
    accounted: set[int] = set()
    _extract_decorators(dotted, refs, classes, constants, path, expected, accounted)
    _extract_loops(dotted, tree, loops, refs, classes, constants, path, expected, accounted)
    _extract_remaining(dotted, tree, refs, classes, constants, path, expected, accounted)

    if len(accounted) != len(refs):
        unaccounted = [ref for ref in refs if id(ref.node) not in accounted]
        raise UnsupportedRegistration(
            f"{dotted}: {len(unaccounted)} registrar reference(s) in positions "
            "this inventory does not model (first at line "
            f"{unaccounted[0].node.lineno}); unattributed registration fails "
            "closed rather than shrinking the expected inventory"
        )
    # Source order, so the inventory reads as the file's registration
    # sequence; a stable sort keeps each loop's tuple order on its line.
    return sorted(expected, key=lambda reg: reg.line)


def expected_in_module(path: Path, dotted: str) -> list[ExpectedRegistration]:
    """The registrations one source file ships, attributed statically."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = _classify_imports(tree, dotted, path)
    return _extract(path, dotted, tree, imports)


def scan_registration_modules(root: Path = _REPO_ROOT) -> dict[str, Path]:
    """Every production source file that registers node kinds, by import name.

    Alias-aware: a module calling a registrar imported under any alias
    (``from maistro.graph.nodes import register_node as rn``) is a
    registration site even though its call sites never spell the canonical
    name — a name-literal-only scan silently misses such modules, a
    deceptively smaller inventory. Test-shaped files stay outside the
    universe: the reachability classification this builds on excludes
    ``tests/`` trees and ``test_*`` modules, which is exactly the rule that
    keeps fixture registrations from satisfying the production proof.

    This is the full production-shaped universe, ledgered-unreachable sites
    included: the reconciliation needs the intersection to demand a reviewed
    disposition for every excluded site. Reachable-only consumers (the loader
    and :func:`expected_registrations`) apply the ledger themselves.
    """
    reachability = _load_reachability_module()
    modules: dict[str, Path] = {}
    outside_src: list[Path] = []
    for path in sorted(reachability._all_package_python_files(root)):
        dotted = _dotted_module(path, root)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = _classify_imports(tree, dotted or "(unpackaged)", path)
        refs: list[_Ref] = []
        loops: list[ast.For] = []
        _collect_scope(tree.body, False, None, imports, refs, loops)
        if not refs:
            continue
        if dotted is None:
            outside_src.append(path)
            continue
        if dotted in modules:
            raise UnsupportedRegistration(
                f"two registration files map to import name {dotted!r}: "
                f"{modules[dotted]} and {path}"
            )
        modules[dotted] = path
    if outside_src:
        raise RuntimeError(
            "node registration outside a packaged src root cannot be swept by dotted "
            "import name; load it through the catalog sweep or extend this guard's "
            "mapping: " + ", ".join(str(p.relative_to(root)) for p in outside_src)
        )
    return modules


def _unreachable_ledger(root: Path) -> frozenset[str]:
    """The ledgered unreachable identities under ``root``.

    Synthetic negative-case trees carry no baseline file; an empty ledger
    keeps them reachable, which is what those cases assert against.
    """
    try:
        baseline = root / _REACHABILITY_BASELINE.relative_to(_REPO_ROOT)
        data = json.loads(baseline.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return frozenset()
    return frozenset(data["unreachable"])


def expected_registrations(
    root: Path = _REPO_ROOT,
) -> dict[str, list[ExpectedRegistration]]:
    """The statically expected registration inventory, per reachable module.

    Modules the reachability ledger classifies unreachable are excluded, the
    same identities ``_import_reachable_registrations`` declines to load: a
    reviewed-unreachable site's kinds never run in production, so expecting
    them would contradict the loading layer this inventory must equal.

    Pure source analysis: importing and running this in a fresh interpreter
    registers nothing, so it can judge a registry that interpreter loaded
    independently of the loading this helper's sibling performs.
    """
    unreachable = _unreachable_ledger(root)
    return {
        dotted: expected_in_module(path, dotted)
        for dotted, path in scan_registration_modules(root).items()
        if dotted not in unreachable
    }


# --- identity parity -----------------------------------------------------------------


@dataclass(frozen=True)
class IdentityParity:
    """The statically expected registrations against a registry's bindings.

    Every mismatch class is explicit, so a regression names its own hole;
    ``extras`` reports incidental registry entries separately from the
    reachable minimum instead of folding them into it.
    """

    checked: int
    #: kind -> "module (file)": expected by source, absent from the registry.
    missing: dict[str, str]
    #: kind -> (expected class name, registry class name).
    wrong_class: dict[str, tuple[str, str]]
    #: kind -> (expected defining module, registry class __module__).
    wrong_module: dict[str, tuple[str, str]]
    #: kind -> (expected checkout file, compiled filenames witnessed instead).
    wrong_source_file: dict[str, tuple[str, list[str]]]
    #: Registry kinds outside the expected minimum (fixtures excluded) ->
    #: their defining module. Reported separately, never merged into the
    #: reachable minimum.
    extras: dict[str, str]

    def failures(self) -> list[str]:
        lines: list[str] = []
        for kind, source in sorted(self.missing.items()):
            lines.append(f"{kind!r} expected from {source} is not in the registry")
        for kind, (want, got) in sorted(self.wrong_class.items()):
            lines.append(f"{kind!r} binds {got!r}, source registers {want!r}")
        for kind, (want, got) in sorted(self.wrong_module.items()):
            lines.append(f"{kind!r} binds a class from {got!r}, source defines it in {want!r}")
        for kind, (want, got) in sorted(self.wrong_source_file.items()):
            lines.append(
                f"{kind!r} binds a class compiled from {got}, not the checkout file {want}"
            )
        return lines


def _own_function_files(cls: type) -> list[str]:
    """Compiled filenames of the functions the class itself defines."""
    files: list[str] = []
    for value in vars(cls).values():
        function: object = value
        if isinstance(value, (staticmethod, classmethod)):
            function = value.__func__
        if isinstance(function, types.FunctionType):
            files.append(function.__code__.co_filename)
    return files


def verify_identity_parity(
    expected: Mapping[str, Sequence[ExpectedRegistration]],
    *,
    kind_classes: Mapping[str, type] | None = None,
) -> IdentityParity:
    """Prove the registry binds each expected kind to its defining identity.

    ``kind_classes`` injects the kind->class view; production proofs pass
    ``None`` to sweep the live registry. Four independent witnesses per kind:
    registry membership, class name, defining ``__module__``, and the method
    code objects' compiled filename against the checkout file — a same-named
    substitute class or a spoofed ``__module__`` fails the witnesses it
    cannot forge (its own methods still compile from wherever it was
    defined).
    """
    if kind_classes is None:
        from maistro.graph.nodes import get_node, list_kinds

        kind_classes = {kind: get_node(kind) for kind in list_kinds()}

    flat = [reg for regs in expected.values() for reg in regs]
    missing: dict[str, str] = {}
    wrong_class: dict[str, tuple[str, str]] = {}
    wrong_module: dict[str, tuple[str, str]] = {}
    wrong_source_file: dict[str, tuple[str, list[str]]] = {}
    for reg in flat:
        cls = kind_classes.get(reg.kind)
        if cls is None:
            missing[reg.kind] = reg.source
            continue
        if cls.__name__ != reg.class_name:
            wrong_class[reg.kind] = (reg.class_name, cls.__name__)
        if cls.__module__ != reg.module:
            wrong_module[reg.kind] = (reg.module, cls.__module__)
        files = _own_function_files(cls)
        if not files:
            # No own methods: fall back to the file of the module the bound
            # class claims (never the expected module — that would let a
            # substitute inherit the real module's file as its witness).
            module = sys.modules.get(cls.__module__)
            module_file = getattr(module, "__file__", None)
            files = [str(module_file)] if module_file else ["<no witness>"]
        if any(Path(name).resolve() != reg.file.resolve() for name in files):
            wrong_source_file[reg.kind] = (str(reg.file), sorted(files))

    expected_kinds = {reg.kind for reg in flat}
    extras = {
        kind: kind_classes[kind].__module__
        for kind in sorted(kind_classes)
        if not kind.startswith("test.") and kind not in expected_kinds
    }
    return IdentityParity(
        checked=len(flat),
        missing=missing,
        wrong_class=wrong_class,
        wrong_module=wrong_module,
        wrong_source_file=wrong_source_file,
        extras=extras,
    )
