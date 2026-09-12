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
from dataclasses import dataclass, field
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
_ALIAS_HINTS = frozenset({"lifecycle", "phase", "stage", "state", "status"})
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


@dataclass
class _TypeBinding:
    """Static binding, retaining definition-time names without running source.

    Ordinary assignments keep a shallow snapshot. Its values are bindings,
    not names to resolve again against a scope's final dictionary. PEP 695
    aliases deliberately retain the live annotation scope for lazy lookup.
    """

    expression: ast.expr | None = None
    environment: dict[str, _TypeBinding] = field(default_factory=dict)
    typing_form: str | None = None
    imported: str | None = None
    identity: str | None = None
    namespace: dict[str, _TypeBinding] | None = None


def _type_binding(
    node: ast.expr,
    environment: dict[str, _TypeBinding],
    resolving: frozenset[int] = frozenset(),
) -> _TypeBinding:
    """Look up names and supported qualified attributes without importing them."""
    if isinstance(node, ast.Name):
        return environment.get(node.id, _TypeBinding())
    if not isinstance(node, ast.Attribute):
        return _TypeBinding()
    owner = _binding_origin(_type_binding(node.value, environment, resolving), resolving)
    if owner.namespace is not None:
        return owner.namespace.get(node.attr, _TypeBinding())
    if owner.typing_form == "module" and node.attr in _TYPING_FORMS:
        return _TypeBinding(typing_form=node.attr)
    if owner.imported is not None:
        return _TypeBinding(imported=f"{owner.imported}.{node.attr}")
    return _TypeBinding()


def _binding_origin(binding: _TypeBinding, resolving: frozenset[int] = frozenset()) -> _TypeBinding:
    """Follow copies of a typing form or module without losing their snapshots."""
    if id(binding) in resolving:
        return _TypeBinding()
    if isinstance(binding.expression, (ast.Name, ast.Attribute)):
        resolving = resolving | {id(binding)}
        target = _type_binding(binding.expression, binding.environment, resolving)
        return _binding_origin(target, resolving)
    return binding


def _resolve_binding(
    binding: _TypeBinding, resolving: frozenset[int], *, literal_member: bool = False
) -> set[str]:
    """Resolve a captured binding with a recursion guard for lazy aliases."""
    if id(binding) in resolving:
        return set()
    if binding.imported is not None:
        return {f"{_IMPORTED_TYPE_PREFIX}{binding.imported}>"}
    if binding.expression is None:
        return set()
    return _resolve_expression(
        binding.expression,
        binding.environment,
        resolving | {id(binding)},
        literal_member=literal_member,
    )


def _type_operands(node: ast.expr, environment: dict[str, _TypeBinding]) -> list[ast.expr]:
    """Extract only type operands; quoted union arms are not Literal data."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [_type_expression(node.left), _type_expression(node.right)]
    if not isinstance(node, ast.Subscript):
        return []
    form = _binding_origin(_type_binding(node.value, environment)).typing_form
    if form not in _TYPING_FORMS or form == "Literal":
        return []
    operands = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
    if form == "Annotated":
        operands = operands[:1]
    return [_type_expression(operand) for operand in operands]


def _resolve_expression(
    node: ast.expr,
    environment: dict[str, _TypeBinding],
    resolving: frozenset[int] = frozenset(),
    *,
    literal_member: bool = False,
) -> set[str]:
    """Interpret the supported static vocabulary, never executing expressions.

    A string-valued binding contributes data only inside Literal. This permits
    Final-backed members without interpreting a runtime string assignment as
    a type alias. Conversely, quoted type operands are parsed only where the
    typing syntax expects a type, never in Literal data or Annotated metadata.
    """
    if isinstance(node, ast.Constant):
        return {node.value} if literal_member and isinstance(node.value, str) else set()
    if isinstance(node, (ast.Name, ast.Attribute)):
        return _resolve_binding(
            _type_binding(node, environment), resolving, literal_member=literal_member
        )
    if (
        isinstance(node, ast.Subscript)
        and _binding_origin(_type_binding(node.value, environment)).typing_form == "Literal"
    ):
        arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        return set().union(
            *(
                _resolve_expression(argument, environment, resolving, literal_member=True)
                for argument in arguments
            )
        )
    return set().union(
        *(
            _resolve_expression(operand, environment, resolving)
            for operand in _type_operands(node, environment)
        )
    )


def _reuses_vocabulary(
    node: ast.expr, states: set[str], environment: dict[str, _TypeBinding]
) -> bool:
    """Share a named alias only when the complete type vocabulary is unchanged."""
    if isinstance(node, (ast.Name, ast.Attribute)):
        binding = _type_binding(node, environment)
        return bool(
            binding.identity
            and _work_vocabulary(_resolve_binding(binding, frozenset())) == states
        )
    return any(
        _reuses_vocabulary(operand, states, environment)
        for operand in _type_operands(node, environment)
    )


def _assigned_names(target: ast.AST) -> Iterator[str]:
    """Unpack static binding targets, excluding object attributes and subscripts."""
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _assigned_names(element)
    elif isinstance(target, ast.Starred):
        yield from _assigned_names(target.value)


def _import_bindings(node: ast.Import | ast.ImportFrom) -> dict[str, _TypeBinding]:
    """An import replaces a previous typing or value binding at that statement."""
    found: dict[str, _TypeBinding] = {}
    for item in node.names:
        if item.name == "*":
            continue  # Wildcard resolution is outside the declared static contract.
        if isinstance(node, ast.Import):
            name = item.asname or item.name.split(".")[0]
            origin = item.name if item.asname else name
            standard = origin in {"typing", "typing_extensions"}
            found[name] = _TypeBinding(
                typing_form="module" if standard else None,
                imported=None if standard else origin,
            )
        else:
            origin = "." * node.level + (node.module or "")
            target = f"{origin}.{item.name}" if node.module else f"{origin}{item.name}"
            standard = node.level == 0 and node.module in {"typing", "typing_extensions"}
            form = item.name if standard and item.name in _TYPING_FORMS else None
            found[item.asname or item.name] = _TypeBinding(
                typing_form=form, imported=None if standard else target
            )
    return found


@dataclass
class _LiteralCollector:
    """Source-ordered lexical discovery; no second ledger or authorization path."""

    module: str
    aliases: list[_TypeBinding] = field(default_factory=list)
    annotations: list[tuple[str, ast.expr, dict[str, _TypeBinding]]] = field(default_factory=list)
    functions: list[tuple[ast.AST, str, dict[str, _TypeBinding]]] = field(default_factory=list)

    def _assignment(
        self,
        node: ast.Assign | ast.AnnAssign | ast.TypeAlias,
        prefix: str,
        environment: dict[str, _TypeBinding],
    ) -> None:
        """Capture RHS names before changing any assignment target."""
        if isinstance(node, ast.TypeAlias):
            targets, expression = [node.name], node.value
        elif isinstance(node, ast.Assign):
            targets, expression = node.targets, node.value
        else:
            targets, expression = [node.target], node.value
        if expression is None:
            return
        snapshot = environment if isinstance(node, ast.TypeAlias) else dict(environment)
        for target in targets:
            for name in _assigned_names(target):
                # Destructuring is a binding but is not itself a type expression.
                value = expression if isinstance(target, ast.Name) else None
                identity = (
                    f"{self.module}::{prefix}{name}" if _looks_like_status_alias(name) else None
                )
                binding = _TypeBinding(value, snapshot, identity=identity)
                environment[name] = binding
                if identity:
                    self.aliases.append(binding)

    def _definition(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        prefix: str,
        environment: dict[str, _TypeBinding],
        enclosing: dict[str, _TypeBinding],
        *,
        in_class: bool,
    ) -> None:
        """Classes are namespaces, not enclosing lexical scopes for their children."""
        parent = enclosing if in_class else environment
        child_prefix = f"{prefix}{node.name}."
        if isinstance(node, ast.ClassDef):
            values = self.scope(node, child_prefix, parent)
            namespace = {
                name: value for name, value in values.items() if value is not parent.get(name)
            }
            environment[node.name] = _TypeBinding(namespace=namespace)
        else:
            environment[node.name] = _TypeBinding()
            # A function body runs after definition. Retain its non-class closure
            # rather than a snapshot of a class dictionary it cannot close over.
            self.functions.append((node, child_prefix, parent))

    def _field(self, node: ast.AST, prefix: str, environment: dict[str, _TypeBinding]) -> None:
        """Keep the annotation's own binding snapshot, separate from its value."""
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            return
        if _looks_like_status_alias(node.target.id):
            self.annotations.append(
                (f"{self.module}::{prefix}{node.target.id}", node.annotation, dict(environment))
            )

    @staticmethod
    def _mask_target(node: ast.AST, environment: dict[str, _TypeBinding]) -> None:
        """Parameters and binding targets mask inherited type evidence."""
        if isinstance(node, ast.arg):
            environment[node.arg] = _TypeBinding()
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for name in _assigned_names(node.target):
                environment[name] = _TypeBinding()
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            for name in _assigned_names(node.optional_vars):
                environment[name] = _TypeBinding()

    def _statement(
        self,
        node: ast.AST,
        prefix: str,
        environment: dict[str, _TypeBinding],
        enclosing: dict[str, _TypeBinding],
        *,
        in_class: bool,
    ) -> None:
        """Process one statement; nested lexical bodies have their own walk."""
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            environment.update(_import_bindings(node))
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            self._definition(node, prefix, environment, enclosing, in_class=in_class)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.TypeAlias)):
            if in_class:
                self._field(node, prefix, environment)
            self._assignment(node, prefix, environment)
        else:
            self._mask_target(node, environment)

    def scope(
        self, tree: ast.AST, prefix: str, enclosing: dict[str, _TypeBinding]
    ) -> dict[str, _TypeBinding]:
        """Snapshot eager assignments while sharing only real lexical closures."""
        environment = dict(enclosing)
        for node in _scope_nodes(tree):
            self._statement(
                node, prefix, environment, enclosing, in_class=isinstance(tree, ast.ClassDef)
            )
        return environment

    def discover(self, tree: ast.AST) -> dict[str, set[str]]:
        """Collect declarations, then resolve captured and explicitly lazy types."""
        initial = {name: _TypeBinding(typing_form=name) for name in _TYPING_FORMS}
        initial.update(
            {name: _TypeBinding(typing_form="module") for name in ("typing", "typing_extensions")}
        )
        self.scope(tree, "", initial)
        # Appending nested functions during this loop is deliberate and finite:
        # every source function is enqueued by exactly one lexical scope walk.
        for node, prefix, environment in self.functions:
            self.scope(node, prefix, environment)
        found: dict[str, set[str]] = {}
        for binding in self.aliases:
            states = _work_vocabulary(_resolve_binding(binding, frozenset()))
            if binding.identity and states:
                found.setdefault(binding.identity, set()).update(states)
        for identity, expression, environment in self.annotations:
            expression = _type_expression(expression)
            states = _work_vocabulary(_resolve_expression(expression, environment))
            if states and not _reuses_vocabulary(expression, states, environment):
                found.setdefault(identity, set()).update(states)
        return found


def _literal_vocabularies(tree: ast.AST, module: str) -> dict[str, set[str]]:
    return _LiteralCollector(module).discover(tree)


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
