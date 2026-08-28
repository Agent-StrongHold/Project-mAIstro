#!/usr/bin/env python3
"""Inventory actual direct-effect call sites that bypass canonical Invocation (#55).

Module/import reachability cannot prove that an effect path is used. This gate
therefore counts AST ``Call`` nodes at deliberately curated semantic effect
boundaries, not imports and not fuzzy method names such as ``.execute()``.

The inventory is a two-way ratchet: every discovered call site must have a
reviewed disposition, and every recorded call site must still exist. Stable
identities are based on file + lexical scope + semantic boundary + occurrence,
so unrelated line-number churn does not create inventory noise.

Run: ``python scripts/check_direct_effects.py``
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "quality" / "direct-effect-call-sites.json"

DISPOSITIONS = frozenset(
    {
        "MIGRATE_TO_GOVERNED_INVOCATION",
        "RETIRE",
        "INTENTIONAL_LIBRARY/INFRASTRUCTURE",
    }
)

# Match model URLs at the HTTP call itself, never endpoint text elsewhere.
_MODEL_ENDPOINTS = ("chat/completions", "/completions", "/v1/responses")
_HTTP_EFFECT_METHODS = frozenset({"post", "stream", "send", "request"})

# Semantic helpers whose call itself is a model effect.
_MODEL_FUNCTIONS = {
    "maistro.agents.pm_llm_call.maistro_llm_call": "model-helper",
}

# Typed clients whose public calls have product effect semantics. Constructors
# and cleanup are intentionally absent: importing/constructing a client is not
# usage, and aclose() is lifecycle cleanup rather than a product effect.
_TYPED_EFFECT_METHODS: dict[str, dict[str, tuple[str, str]]] = {
    "maistro.tools.browser.BrowserClient": {
        "search_web": ("TOOL_EFFECT", "browser.search_web"),
        "browse": ("TOOL_EFFECT", "browser.browse"),
    },
    "maistro.tools.atlassian.AtlassianMCPClient": {
        "jira_get_my_issues": (
            "MCP_EFFECT",
            "atlassian.jira_get_my_issues",
        ),
        "jira_search_issues": (
            "MCP_EFFECT",
            "atlassian.jira_search_issues",
        ),
        "jira_get_issue": ("MCP_EFFECT", "atlassian.jira_get_issue"),
        "jira_create_issue": (
            "MCP_EFFECT",
            "atlassian.jira_create_issue",
        ),
        "jira_update_issue": (
            "MCP_EFFECT",
            "atlassian.jira_update_issue",
        ),
        "confluence_search": (
            "MCP_EFFECT",
            "atlassian.confluence_search",
        ),
        "confluence_get_page": (
            "MCP_EFFECT",
            "atlassian.confluence_get_page",
        ),
        "confluence_create_page": (
            "MCP_EFFECT",
            "atlassian.confluence_create_page",
        ),
        "confluence_update_page": (
            "MCP_EFFECT",
            "atlassian.confluence_update_page",
        ),
    },
}

# Product-level wrappers are included because these calls identify the shipped
# caller that causes the effect, rather than only the wrapper's internal HTTP.
_FUNCTION_EFFECTS: dict[str, tuple[str, str]] = {
    "services.tool_executor.web_search": ("TOOL_EFFECT", "hive.web_search"),
    "services.tool_executor.browse_url": ("TOOL_EFFECT", "hive.browse_url"),
    "services.tool_executor.clarify": ("MODEL_EFFECT", "hive.clarify"),
}

# Runtime object types cannot always be recovered from Python's AST. These
# entries are deliberately exact path/scope/callee triples rather than fuzzy
# ``send``/``execute``/``invoke`` matching.
_PATH_CALLS: dict[tuple[str, str, str], tuple[str, str]] = {
    (
        "packages/maistro-core/src/maistro/capabilities/governed_invocation.py",
        "GovernedInvocationExecutionService.invoke",
        "self._invocations.invoke",
    ): ("CANONICAL_INVOCATION", "InvocationExecutionService.invoke"),
    (
        "packages/maistro-core/src/maistro/capabilities/harness_manager.py",
        "HarnessSessionManager.send_invocation",
        "invocation_service.invoke",
    ): (
        "CANONICAL_INVOCATION",
        "GovernedInvocationExecutionService.invoke",
    ),
    (
        "packages/maistro-core/src/maistro/capabilities/harness_manager.py",
        "HarnessSessionManager.start",
        "provider.start_session",
    ): ("HARNESS_EFFECT", "harness.start_session"),
    (
        "packages/maistro-core/src/maistro/capabilities/harness_manager.py",
        "HarnessSessionManager.send",
        "safe.send",
    ): ("HARNESS_EFFECT", "harness.send"),
    (
        "packages/maistro-core/src/maistro/capabilities/harness_manager.py",
        "HarnessSessionManager.stream",
        "safe.stream",
    ): ("HARNESS_EFFECT", "harness.stream"),
    (
        "packages/maistro-core/src/maistro/capabilities/harness_manager.py",
        "HarnessSessionManager.stop",
        "safe.stop",
    ): ("HARNESS_EFFECT", "harness.stop"),
}


@dataclass(frozen=True)
class Site:
    """One actual AST call site at a curated effect boundary."""

    id: str
    path: str
    qualname: str
    line: int
    category: str
    entry_point: str
    callee: str


@dataclass
class Scope:
    qualname: str
    aliases: dict[str, str]
    strings: dict[str, ast.expr]
    objects: dict[str, str]


def _production_python_files(root: Path = ROOT) -> list[Path]:
    """Return production Python under package src/backends, excluding tests."""
    files: list[Path] = []
    bases = [*root.glob("packages/*/src"), *root.glob("packages/*/backend")]
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(base)
            if "tests" in rel.parts or path.name.startswith("test_"):
                continue
            files.append(path)
    return sorted(set(files))


class _ScopeImportCollector(ast.NodeVisitor):
    """Collect imports in one lexical scope, including conditional imports."""

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            key = alias.asname or alias.name.split(".")[0]
            self.aliases[key] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module:
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            key = alias.asname or alias.name
            self.aliases[key] = f"{node.module}.{alias.name}"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _scope_aliases(body: list[ast.stmt]) -> dict[str, str]:
    collector = _ScopeImportCollector()
    for statement in body:
        collector.visit(statement)
    return collector.aliases


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def _resolve_symbol(node: ast.expr, aliases: dict[str, str]) -> str | None:
    dotted = _dotted(node)
    if not dotted:
        return None
    head, *tail = dotted.split(".")
    resolved = aliases.get(head, head)
    if not tail:
        return resolved
    return ".".join([resolved, *tail])


class _ScopeBindingCollector(ast.NodeVisitor):
    """Collect simple strings and typed client constructions in one scope."""

    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases
        self.strings: dict[str, ast.expr] = {}
        self.objects: dict[str, str] = {}

    def _record(
        self,
        targets: list[ast.expr],
        value: ast.expr | None,
    ) -> None:
        if value is None:
            return
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if not names:
            return
        if isinstance(value, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Name)):
            for name in names:
                self.strings[name] = value
        if not isinstance(value, ast.Call):
            return
        symbol = _resolve_symbol(value.func, self.aliases)
        if symbol not in _TYPED_EFFECT_METHODS:
            return
        for name in names:
            self.objects[name] = symbol

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record(list(node.targets), node.value)
        self.generic_visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record([node.target], node.value)
        if node.value is not None:
            self.generic_visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _scope_bindings(
    body: list[ast.stmt],
    aliases: dict[str, str],
) -> tuple[dict[str, ast.expr], dict[str, str]]:
    collector = _ScopeBindingCollector(aliases)
    for statement in body:
        collector.visit(statement)
    return collector.strings, collector.objects


def _string_parts(
    node: ast.expr,
    bindings: dict[str, ast.expr],
    seen: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name) and node.id in bindings and node.id not in seen:
        return _string_parts(
            bindings[node.id],
            bindings,
            seen | {node.id},
        )
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.extend(_string_parts(value.value, bindings, seen))
        return tuple(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_parts(node.left, bindings, seen) + _string_parts(
            node.right,
            bindings,
            seen,
        )
    return ()


def _http_url(call: ast.Call) -> ast.expr | None:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr not in _HTTP_EFFECT_METHODS:
        return None
    for keyword in call.keywords:
        if keyword.arg == "url":
            return keyword.value
    if func.attr == "request":
        return call.args[1] if len(call.args) >= 2 else None
    return call.args[0] if call.args else None


def _is_model_http_call(
    call: ast.Call,
    bindings: dict[str, ast.expr],
) -> bool:
    url = _http_url(call)
    if url is None:
        return False
    return any(
        endpoint in part
        for part in _string_parts(url, bindings)
        for endpoint in _MODEL_ENDPOINTS
    )


def _callee_text(call: ast.Call) -> str:
    return _dotted(call.func) or ast.unparse(call.func)


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        aliases = _scope_aliases(tree.body)
        strings, objects = _scope_bindings(tree.body, aliases)
        self.scopes = [Scope("<module>", aliases, strings, objects)]
        self.raw: list[tuple[str, str, str, int, str]] = []

    @property
    def scope(self) -> Scope:
        return self.scopes[-1]

    def _push_scope(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    ) -> None:
        if self.scope.qualname == "<module>":
            qualname = node.name
        else:
            qualname = f"{self.scope.qualname}.{node.name}"
        aliases = {**self.scope.aliases, **_scope_aliases(node.body)}
        local_strings, local_objects = _scope_bindings(node.body, aliases)
        strings = {**self.scope.strings, **local_strings}
        objects = {**self.scope.objects, **local_objects}
        self.scopes.append(Scope(qualname, aliases, strings, objects))
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._push_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._push_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._push_scope(node)

    def visit_Call(self, node: ast.Call) -> None:
        callee = _callee_text(node)
        classification = self._classify(node, callee)
        if classification is not None:
            category, entry_point = classification
            self.raw.append(
                (
                    self.scope.qualname,
                    category,
                    entry_point,
                    node.lineno,
                    callee,
                )
            )
        self.generic_visit(node)

    def _classify(
        self,
        call: ast.Call,
        callee: str,
    ) -> tuple[str, str] | None:
        path_rule = _PATH_CALLS.get((self.path, self.scope.qualname, callee))
        if path_rule is not None:
            return path_rule
        if _is_model_http_call(call, self.scope.strings):
            return "MODEL_EFFECT", "openai-compatible-http"

        symbol = _resolve_symbol(call.func, self.scope.aliases)
        if symbol in _MODEL_FUNCTIONS:
            return "MODEL_EFFECT", _MODEL_FUNCTIONS[symbol]
        if symbol in _FUNCTION_EFFECTS:
            return _FUNCTION_EFFECTS[symbol]

        if not isinstance(call.func, ast.Attribute):
            return None
        if not isinstance(call.func.value, ast.Name):
            return None
        object_type = self.scope.objects.get(call.func.value.id)
        if object_type is None:
            return None
        return _TYPED_EFFECT_METHODS[object_type].get(call.func.attr)


def analyze_source(source: str, path: str = "example.py") -> list[Site]:
    """Analyze one source string. Syntax errors are ignored as non-production input."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = _Visitor(path, tree)
    visitor.visit(tree)

    counts: dict[tuple[str, str, str], int] = {}
    sites: list[Site] = []
    for qualname, category, entry_point, line, callee in visitor.raw:
        key = (qualname, category, entry_point)
        occurrence = counts.get(key, 0) + 1
        counts[key] = occurrence
        site_id = (
            f"{path}::{qualname}::{category}:"
            f"{entry_point}#{occurrence}"
        )
        sites.append(
            Site(
                id=site_id,
                path=path,
                qualname=qualname,
                line=line,
                category=category,
                entry_point=entry_point,
                callee=callee,
            )
        )
    return sites


def discover(root: Path = ROOT) -> dict[str, Site]:
    found: dict[str, Site] = {}
    for path in _production_python_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue
        for site in analyze_source(source, rel):
            if site.id in found:
                raise RuntimeError(
                    f"duplicate direct-effect site identity: {site.id}"
                )
            found[site.id] = site
    return found


def _load_inventory(
    path: Path = INVENTORY,
) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(key): dict(value)
        for key, value in payload.get("sites", {}).items()
    }


def audit(
    recorded: dict[str, dict[str, Any]],
    found: dict[str, Site],
) -> list[str]:
    failures: list[str] = []
    for site_id in sorted(found.keys() - recorded.keys()):
        site = found[site_id]
        failures.append(
            f"NEW {site_id} (line {site.line}, callee {site.callee!r}) is an "
            "unclassified direct-effect call site"
        )
    for site_id in sorted(recorded.keys() - found.keys()):
        failures.append(
            f"STALE {site_id} disappeared from code; remove or update its "
            "inventory entry"
        )

    for site_id in sorted(found.keys() & recorded.keys()):
        site = found[site_id]
        entry = recorded[site_id]
        for field in (
            "path",
            "qualname",
            "category",
            "entry_point",
            "callee",
        ):
            expected = getattr(site, field)
            if entry.get(field) != expected:
                failures.append(
                    f"{site_id}: recorded {field}={entry.get(field)!r}, "
                    f"discovered {expected!r}"
                )
        disposition = str(entry.get("disposition", "")).strip()
        owner = str(entry.get("owner", "")).strip()
        rationale = str(entry.get("rationale", "")).strip()
        if disposition not in DISPOSITIONS:
            failures.append(
                f"{site_id}: disposition must be one of "
                f"{sorted(DISPOSITIONS)}"
            )
        if not owner:
            failures.append(f"{site_id}: owner is required")
        if not rationale:
            failures.append(f"{site_id}: rationale is required")
    return failures


def _write_inventory(
    found: dict[str, Site],
    recorded: dict[str, dict[str, Any]],
    path: Path = INVENTORY,
) -> None:
    sites: dict[str, dict[str, Any]] = {}
    for site_id, site in sorted(found.items()):
        old = recorded.get(site_id, {})
        data = asdict(site)
        data.pop("id")
        data.update(
            {
                "disposition": old.get("disposition", ""),
                "owner": old.get("owner", ""),
                "rationale": old.get("rationale", ""),
            }
        )
        sites[site_id] = data
    payload = {
        "_comment": (
            "Actual AST call sites at curated direct-effect boundaries for #55. "
            "Imports/definitions are not usage. Update with "
            "scripts/check_direct_effects.py --update, then review every blank "
            "disposition/owner/rationale."
        ),
        "sites": sites,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not INVENTORY.exists():
        print(f"FAIL: {INVENTORY} is missing", file=sys.stderr)
        return 1
    found = discover(ROOT)
    recorded = _load_inventory(INVENTORY)
    if "--update" in args:
        _write_inventory(found, recorded, INVENTORY)
        print(
            f"wrote {INVENTORY.relative_to(ROOT)} with "
            f"{len(found)} discovered call site(s)"
        )
        return 0

    failures = audit(recorded, found)
    categories: dict[str, int] = {}
    for site in found.values():
        categories[site.category] = categories.get(site.category, 0) + 1
    summary = (
        ", ".join(
            f"{name}={count}"
            for name, count in sorted(categories.items())
        )
        or "none"
    )
    print(f"direct-effect call sites: {len(found)} ({summary})")
    if failures:
        print(
            "FAIL: direct-effect inventory does not match current production "
            "call sites",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(
        "Direct-effect inventory matches code and every site is dispositioned."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
