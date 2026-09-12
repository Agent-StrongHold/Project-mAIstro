#!/usr/bin/env python3
"""Fail when a new work-state enum appears outside the trusted lifecycle ledger (#36, #542).

The convergence program's central claim is that Run/NodeRun/Attempt is the one
execution identity. A candidate may not introduce a second lifecycle and approve
it by adding a classification to quality/execution-lifecycles.json in the same
change. New identities are judged against the merge-base ledger and require a
separately landed authorization. The candidate ledger is still the source of
reviewed classification/rationale for identities already admitted, and stale
entries must be pruned immediately.

Discovery is deliberately syntax-independent within a small static vocabulary:
Enum subclasses, status-shaped Literal type aliases, and status-shaped Literal
field annotations are treated alike. The value/name heuristic keeps ordinary
configuration Literals out of this ledger;
free-text and database-column audits remain separate gates.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "execution-lifecycles.json"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
RATCHET = "execution-lifecycles"
METRIC_DEFINITION_VERSION = "3"

CLASSIFICATIONS = frozenset({"CANONICAL", "DOMAIN", "PROJECTION", "RECEIPT", "CONVERGE"})
_ENUM_BASES = frozenset({"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag"})
_TYPING_FORMS = frozenset({"Literal", "Optional", "Union", "Annotated"})
_SCOPE_BOUNDARIES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_ALIAS_HINTS = frozenset({"lifecycle", "phase", "state", "status"})
_WORK_STATES = frozenset(
    {
        "ABORTED",
        "ACTIVE",
        "ASSIGNED",
        "CREATED",
        "BLOCKED",
        "CANCELED",
        "CANCELLED",
        "CLAIMED",
        "CODING",
        "COMPLETE",
        "COMPLETED",
        "DONE",
        "ERROR",
        "ERRORED",
        "FAILED",
        "IN_PROGRESS",
        "PAUSED",
        "PENDING",
        "PLANNING",
        "QUEUED",
        "RETRYING",
        "REVIEWING",
        "RUNNING",
        "SKIPPED",
        "STOPPED",
        "TESTING",
        "SUCCEEDED",
        "TIMED_OUT",
        "YIELDED",
        "TIMEOUT",
        "WAITING",
    }
)
_MIN_WORK_STATES = 3
_IMPORTED_TYPE_PREFIX = "<imported-type:"


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


def _load_reachability() -> object:
    spec = importlib.util.spec_from_file_location("_reachability", REACHABILITY)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REACHABILITY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_reachability"] = module
    spec.loader.exec_module(module)
    return module


def _attribute_name(node: ast.expr) -> str:
    """Return the terminal name for ``typing.Literal``-style expressions."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _looks_like_status_alias(name: str) -> bool:
    normalized = name.replace("-", "_").lower()
    parts = {part for part in normalized.split("_") if part}
    return bool(parts & _ALIAS_HINTS or any(normalized.endswith(hint) for hint in _ALIAS_HINTS))


def _scope_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    """Walk one lexical scope, exposing but not entering its child scopes."""
    for node in ast.iter_child_nodes(tree):
        yield node
        if not isinstance(node, _SCOPE_BOUNDARIES):
            yield from _scope_nodes(node)


def _typing_names(tree: ast.AST, inherited: dict[str, str]) -> dict[str, str]:
    """Resolve supported typing spellings without importing production code."""
    names = {**{name: name for name in _TYPING_FORMS}, **inherited}
    for node in _scope_nodes(tree):
        if (
            not isinstance(node, ast.ImportFrom)
            or node.level != 0
            or node.module not in {"typing", "typing_extensions"}
        ):
            continue
        for imported in node.names:
            if imported.name in _TYPING_FORMS:
                names[imported.asname or imported.name] = imported.name
    return names


def _imported_type_values(tree: ast.AST) -> dict[str, set[str]]:
    """Keep unresolved imports symbolic instead of treating them as empty types.

    No production module is imported or executed. A marker names the imported
    type; it is not an invented status value. Pure reuse is ignored, but a
    status-shaped alias/field extending it with a known work state needs a
    disposition even when its locally visible vocabulary has fewer than three
    states. The same source-only rule applies at the trusted base.
    """
    found: dict[str, set[str]] = {}
    for node in _scope_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module in {"typing", "typing_extensions"}:
                continue
            origin = "." * node.level + (node.module or "")
            for item in node.names:
                if item.name != "*":
                    target = f"{origin}.{item.name}" if node.module else f"{origin}{item.name}"
                    found[item.asname or item.name] = {f"{_IMPORTED_TYPE_PREFIX}{target}>"}
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name in {"typing", "typing_extensions"}:
                    continue
                bound = item.asname or item.name.split(".")[0]
                target = item.name if item.asname else bound
                found[bound] = {f"{_IMPORTED_TYPE_PREFIX}{target}>"}
    return found


def _work_vocabulary(values: set[str]) -> set[str]:
    """Return known states and explicit unresolved-import evidence for review.

    The ordinary three-state threshold is unchanged. An unresolved import
    combined with at least one known work state is conservatively visible:
    otherwise importing the first three states would conceal a new extension.
    No-import small Literals and pure imported-type reuse remain unclassified.
    """
    states = _normalized_work_states(values)
    imported = {value for value in values if value.startswith(_IMPORTED_TYPE_PREFIX)}
    if len(states) >= _MIN_WORK_STATES or (states and imported):
        return states | imported
    return set()


def _type_expression(node: ast.expr) -> ast.expr:
    """Parse explicitly postponed annotations without evaluating production code.

    Only type-bearing positions call this helper. Literal values and Annotated
    metadata are data, not expressions. The small bound also terminates nested
    quotes and self-referential string spellings without executing any of them.
    """
    for _ in range(8):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return node
        try:
            node = ast.parse(node.value, mode="eval").body
        except (SyntaxError, ValueError):
            break
    return ast.Constant(value=None)


def _typing_arguments(
    node: ast.Subscript, typing_names: dict[str, str]
) -> tuple[str | None, list[ast.expr]]:
    """Return type-bearing arguments, excluding unsupported forms and metadata."""
    form = typing_names.get(_attribute_name(node.value))
    if form not in _TYPING_FORMS:
        return None, []
    arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if form == "Literal":
        return form, arguments
    if form == "Annotated":
        arguments = arguments[:1]
    return form, [_type_expression(argument) for argument in arguments]


def _literal_values(
    node: ast.expr,
    aliases: dict[str, ast.expr],
    typing_names: dict[str, str],
    inherited: dict[str, set[str]],
    resolving: frozenset[str] = frozenset(),
) -> set[str]:
    """Resolve local aliases, unions and typing wrappers in their defining scope.

    Inherited aliases are already resolved in their parent scope so a child
    shadowing a helper cannot reinterpret a parent's vocabulary. Annotated
    contributes its type only, never strings or Literals in its metadata.
    """
    if isinstance(node, ast.Name):
        if node.id not in aliases:
            return inherited.get(node.id, set())
        if node.id in resolving:
            return set()
        return _literal_values(
            aliases[node.id],
            aliases,
            typing_names,
            inherited,
            resolving | {node.id},
        )
    if isinstance(node, ast.Attribute):
        roots = _literal_values(node.value, aliases, typing_names, inherited, resolving)
        return {
            f"{value[:-1]}.{node.attr}>"
            for value in roots
            if value.startswith(_IMPORTED_TYPE_PREFIX)
        }
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _literal_values(node.left, aliases, typing_names, inherited, resolving)
        return left | _literal_values(node.right, aliases, typing_names, inherited, resolving)
    if not isinstance(node, ast.Subscript):
        return set()
    form, arguments = _typing_arguments(node, typing_names)
    values: set[str] = set()
    for argument in arguments:
        if form == "Literal" and isinstance(argument, ast.Constant):
            if isinstance(argument.value, str):
                values.add(argument.value)
        else:
            values.update(_literal_values(argument, aliases, typing_names, inherited, resolving))
    return values


def _is_enum(node: ast.ClassDef) -> bool:
    bases = {
        base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        for base in node.bases
    }
    return bool(bases & _ENUM_BASES)


def _normalized_work_states(values: set[str]) -> set[str]:
    return {
        value.upper().replace("-", "_").replace(" ", "_")
        for value in values
        if value.upper().replace("-", "_").replace(" ", "_") in _WORK_STATES
    }


def _enum_member_values(node: ast.ClassDef) -> set[str]:
    """Collect member names and literal string values without executing an Enum."""
    values: set[str] = set()
    for statement in node.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = (statement.target,)
            value = statement.value
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            values.add(target.id)
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                values.add(value.value)
    return values


def _enum_vocabularies(tree: ast.AST, module: str, prefix: str = "") -> dict[str, set[str]]:
    """Preserve lexical identity for Enums just as for Literal vocabularies."""
    found: dict[str, set[str]] = {}
    for node in _scope_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found.update(_enum_vocabularies(node, module, f"{prefix}{node.name}."))
        if not isinstance(node, ast.ClassDef) or not _is_enum(node):
            continue
        states = _normalized_work_states(_enum_member_values(node))
        if len(states) >= _MIN_WORK_STATES:
            found[f"{module}::{prefix}{node.name}"] = states
    return found


def _rebind_non_alias(node: ast.AST, aliases: dict[str, ast.expr]) -> bool:
    """Respect bindings that replace an imported or locally assigned helper.

    A later import replaces an earlier assignment. Definitions and parameters
    instead mask inherited import evidence without becoming literal aliases.
    Scope boundaries are still enforced by the caller's lexical walk.
    """
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for item in node.names:
            name = item.asname or item.name
            if isinstance(node, ast.Import):
                name = item.asname or item.name.split(".")[0]
            aliases.pop(name, None)
        return True
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        aliases[node.name] = ast.Constant(value=None)
        return True
    if isinstance(node, ast.arg):
        aliases[node.arg] = ast.Constant(value=None)
        return True
    return False


def _literal_aliases(tree: ast.AST) -> dict[str, ast.expr]:
    """Collect aliases in this scope only, including PEP 695 ``type`` statements.

    Helper aliases need not themselves be status-shaped: a final ``RunStatus``
    alias can legally be assembled from a private ``_RUNNING_STATES`` alias.
    Only status-shaped names are emitted by ``_literal_vocabularies``.
    """
    aliases: dict[str, ast.expr] = {}
    for node in _scope_nodes(tree):
        if _rebind_non_alias(node, aliases):
            continue
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
            value = node.value
        elif isinstance(node, ast.TypeAlias):
            targets = (node.name,)
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases[target.id] = value
    return aliases


def _uses_named_vocabulary(
    node: ast.expr, states: set[str], named: dict[str, set[str]], typing_names: dict[str, str]
) -> bool:
    """Reuse an alias only from the type expression, never Annotated metadata."""
    if isinstance(node, ast.Name):
        return named.get(node.id) == states
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _uses_named_vocabulary(node.left, states, named, typing_names)
        return left or _uses_named_vocabulary(node.right, states, named, typing_names)
    if not isinstance(node, ast.Subscript):
        return False
    _, arguments = _typing_arguments(node, typing_names)
    return any(_uses_named_vocabulary(item, states, named, typing_names) for item in arguments)


def _literal_field_vocabularies(
    tree: ast.AST,
    aliases: dict[str, ast.expr],
    typing_names: dict[str, str],
    inherited: dict[str, set[str]],
    named: dict[str, set[str]],
    identity_prefix: str,
) -> dict[str, set[str]]:
    """Discover fields in this class, retaining nested scopes in their identity."""
    found: dict[str, set[str]] = {}
    if not isinstance(tree, ast.ClassDef):
        return found
    for node in _scope_nodes(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if not _looks_like_status_alias(node.target.id):
            continue
        annotation = _type_expression(node.annotation)
        states = _work_vocabulary(_literal_values(annotation, aliases, typing_names, inherited))
        if not states:
            continue
        # Reusing a named vocabulary adds no authority. Extending it with new
        # states does, so a union containing an alias must not hide the field.
        if _uses_named_vocabulary(annotation, states, named, typing_names):
            continue
        found[f"{identity_prefix}{node.target.id}"] = states
    return found


def _literal_scope_vocabularies(
    tree: ast.AST,
    module: str,
    prefix: str,
    inherited: dict[str, set[str]],
    inherited_named: dict[str, set[str]],
    inherited_typing: dict[str, str],
) -> dict[str, set[str]]:
    """Give each alias its lexical identity rather than flattening sibling scopes."""
    aliases = _literal_aliases(tree)
    imported = _imported_type_values(tree)
    inherited = {**inherited, **imported}
    typing_names = _typing_names(tree, inherited_typing)
    values = {
        name: _literal_values(value, aliases, typing_names, inherited)
        for name, value in aliases.items()
    }
    named = {
        name: _work_vocabulary(value)
        for name, value in values.items()
        if _looks_like_status_alias(name) and _work_vocabulary(value)
    }
    identity_prefix = f"{module}::{prefix}"
    found = {f"{identity_prefix}{name}": states for name, states in named.items()}
    visible_named = {
        **{
            name: states
            for name, states in inherited_named.items()
            if name not in aliases and name not in imported
        },
        **named,
    }
    found.update(
        _literal_field_vocabularies(
            tree, aliases, typing_names, inherited, visible_named, identity_prefix
        )
    )
    for child in _scope_nodes(tree):
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found.update(
                _literal_scope_vocabularies(
                    child,
                    module,
                    f"{prefix}{child.name}.",
                    {**inherited, **values},
                    visible_named,
                    typing_names,
                )
            )
    return found


def _literal_vocabularies(tree: ast.AST, module: str) -> dict[str, set[str]]:
    return _literal_scope_vocabularies(tree, module, "", {}, {}, {})


def work_state_vocabularies(source: str, module: str) -> dict[str, set[str]]:
    """Find Enum and status-shaped Literal vocabularies in one source file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return {**_enum_vocabularies(tree, module), **_literal_vocabularies(tree, module)}


def work_state_enums(source: str, module: str) -> dict[str, set[str]]:
    """Compatibility name for the shared Enum and Literal lifecycle detector."""
    return work_state_vocabularies(source, module)


def work_state_literals(source: str, module: str) -> dict[str, set[str]]:
    """Return only Literal identities for focused gate and fixture tests."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    enum_vocabularies = _enum_vocabularies(tree, module)
    return {
        name: states
        for name, states in work_state_vocabularies(source, module).items()
        if name not in enum_vocabularies
    }


def discover() -> dict[str, set[str]]:
    reach = _load_reachability()
    found: dict[str, set[str]] = {}
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        module = reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        found.update(work_state_vocabularies(path.read_text(errors="replace"), module))
    return found


def _discover_at_revision(revision: str | None, current: dict[str, set[str]]) -> set[str]:
    """Find current identities whose source already existed at the trusted base."""
    if not revision:
        return set()
    modules = {name.rsplit("::", 1)[0] for name in current}
    reach = _load_reachability()
    visible: set[str] = set()
    for key, path in reach._collect_modules().items():  # type: ignore[attr-defined]
        module = reach._display_name(key, reach.FLAT_APPS)  # type: ignore[attr-defined]
        if module not in modules:
            continue
        relative = path.relative_to(ROOT).as_posix()
        proc = subprocess.run(
            ["git", "show", f"{revision}:{relative}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            cwd=ROOT,
        )
        if proc.returncode == 0:
            visible.update(work_state_vocabularies(proc.stdout, module))
    return visible


def _entries(ledger: object) -> dict[str, object]:
    if not isinstance(ledger, dict):
        return {}
    entries = ledger.get("lifecycles")
    return dict(entries) if isinstance(entries, dict) else {}


def _unauthorized_additions(
    added: list[str], authorized: dict[str, str], visible_at_base: set[str]
) -> list[str]:
    """Keep a candidate classification from authorizing a newly added identity."""
    return [name for name in added if name not in authorized and name not in visible_at_base]


def audit(ledger: dict[str, object], found: dict[str, set[str]]) -> list[str]:
    """Every way the candidate ledger and code disagree, named."""
    entries = ledger.get("lifecycles")
    if not isinstance(entries, dict):
        return ["ledger has no 'lifecycles' object"]

    failures: list[str] = []
    for name in sorted(set(found) - set(entries)):
        failures.append(
            f"{name}: an unclassified work-state vocabulary ({', '.join(sorted(found[name]))}). "
            f"Classify it in {LEDGER.name} as one of {', '.join(sorted(CLASSIFICATIONS))}."
        )
    for name in sorted(set(entries) - set(found)):
        failures.append(f"{name}: classified here but no longer found in the code; prune it")

    for name in sorted(set(entries) & set(found)):
        entry = entries[name]
        if not isinstance(entry, dict):
            failures.append(f"{name}: entry must be an object")
            continue
        classification = entry.get("classification")
        if classification not in CLASSIFICATIONS:
            failures.append(
                f"{name}: classification {classification!r} is not one of "
                f"{', '.join(sorted(CLASSIFICATIONS))}"
            )
        if not str(entry.get("rationale", "")).strip():
            failures.append(f"{name}: needs a rationale")
        if classification == "CONVERGE" and not str(entry.get("converged_by", "")).strip():
            failures.append(
                f"{name}: CONVERGE requires 'converged_by' naming the issue that removes it"
            )
    return failures


def main() -> int:
    if not LEDGER.exists():
        print(f"FAIL: {LEDGER} is missing", file=sys.stderr)
        return 1
    candidate_ledger = json.loads(LEDGER.read_text())
    candidate_entries = _entries(candidate_ledger)
    found = discover()
    candidate_failures = audit(candidate_ledger, found)

    prov = _provenance()
    try:
        trusted_ref = prov.resolve_baseline(LEDGER, root=ROOT)
        trusted_payload = trusted_ref.loads(default={"lifecycles": {}})
        trusted_entries = _entries(trusted_payload)
        prov.require_measurement(found, ratchet=RATCHET, what="work-state vocabularies")
        prov.require_metric_version(
            METRIC_DEFINITION_VERSION,
            recorded=(
                str(trusted_payload.get("metric_definition_version"))
                if isinstance(trusted_payload, dict)
                and trusted_payload.get("metric_definition_version") is not None
                else None
            ),
            ratchet=RATCHET,
            baseline=trusted_ref,
        )
        authorized = prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)
    except prov.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    added = sorted(set(found) - set(trusted_entries))
    # Scanner expansion must surface pre-existing debt without turning that debt
    # into a self-authorized new lifecycle. A current detector pass over the
    # trusted source distinguishes newly visible aliases from code introduced by
    # this change; the latter still needs a prior grant.
    visible_at_base = _discover_at_revision(trusted_ref.base_sha, found)
    unauthorized = _unauthorized_additions(added, authorized, visible_at_base)
    unbanked_authorized = [
        name for name in added if name in authorized and name not in candidate_entries
    ]

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=trusted_ref,
            tool="python ast",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted_entries)} classified lifecycles",
            new_value=f"{len(found)} discovered lifecycles",
            candidate_sha=prov.head_sha(ROOT),
            authorizations=tuple(
                f"{name}: {authorized[name]}" for name in added if name in authorized
            ),
        ).render()
    )

    failures = list(candidate_failures)
    failures.extend(
        f"{name}: NEW work-state vocabulary is absent from the trusted base and has no "
        "already-landed authorization"
        for name in unauthorized
    )
    failures.extend(
        f"{name}: authorized lifecycle addition is not classified in the candidate ledger"
        for name in unbanked_authorized
    )
    if failures:
        print("FAIL: the execution-lifecycle ledger does not match trusted policy\n")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    counts: dict[str, int] = {}
    for entry in candidate_entries.values():
        if isinstance(entry, dict):
            key = str(entry["classification"])
            counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    print(f"OK: {len(found)} work-state vocabularies, all classified ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
