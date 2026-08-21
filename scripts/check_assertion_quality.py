#!/usr/bin/env python3
"""Classify per-test assertion-quality risks.

The default report contains only high-confidence syntax defects. ``--review``
adds lower-confidence heuristics for manual inspection. Syntax cannot certify
behavioral coverage; the mutation ratchet supplies that evidence.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_ROOTS = (ROOT / "tests", ROOT / "formal", *ROOT.glob("packages/*/tests"))
DEFAULT_SOURCE_ROOTS = (ROOT / "packages", ROOT / "apps", ROOT / "hive-conductor", ROOT / "tools")
ACTIONABLE_CODES = {"literal_constant_assert"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    test: str
    code: str

    @property
    def key(self) -> str:
        return f"{self.path}:{self.line}:{self.test}:{self.code}"


def _annotation_is_bool(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Name):
        return annotation.id == "bool"
    if isinstance(annotation, ast.Constant):
        return annotation.value == "bool"
    if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name):
        if annotation.value.id != "Literal":
            return False
        values = (
            annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        )
        return any(
            isinstance(value, ast.Constant) and isinstance(value.value, bool) for value in values
        )
    return False


def annotated_bool_functions(source_roots: Iterable[Path] = DEFAULT_SOURCE_ROOTS) -> set[str]:
    """Collect names of project functions whose declared contract is boolean."""
    names: set[str] = set()
    for root in source_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                    and node.returns
                    and _annotation_is_bool(node.returns)
                ):
                    names.add(node.name)
    return names


def _call_name(call: ast.Call) -> str:
    return getattr(call.func, "id", "") or getattr(call.func, "attr", "")


def _is_bool_contract(expression: ast.expr, bool_functions: set[str]) -> bool:
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        expression = expression.operand
    if not isinstance(expression, ast.Call):
        return False
    return _call_name(expression) in bool_functions | {"all", "any"}


def _has_raises_or_warns(node: ast.AST) -> bool:
    if not isinstance(node, ast.With | ast.AsyncWith):
        return False
    return any(
        isinstance(item.context_expr, ast.Call)
        and _call_name(item.context_expr) in {"raises", "warns"}
        for item in node.items
    )


def _has_assertion_call(fn: ast.AST) -> bool:
    return any(
        (name := _call_name(call)).startswith("assert") or name in {"fail", "expect"}
        for call in (node for node in ast.walk(fn) if isinstance(node, ast.Call))
    )


def _has_assertion_guard(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Raise):
            continue
        if isinstance(node.exc, ast.Name) and node.exc.id == "AssertionError":
            return True
        if isinstance(node.exc, ast.Call) and _call_name(node.exc) == "AssertionError":
            return True
    return False


def _is_observable_value(expression: ast.expr) -> bool:
    """Whether an expression reads behavior a test can reasonably contract on."""
    return isinstance(expression, ast.Attribute | ast.Call)


def _is_weak_assertion(assertion: ast.Assert, bool_functions: set[str]) -> bool:
    expression = assertion.test
    if _is_bool_contract(expression, bool_functions):
        return False
    if isinstance(expression, ast.Constant):
        return True
    if isinstance(expression, ast.Compare):
        comparator = expression.comparators[0] if expression.comparators else None
        if isinstance(expression.ops[0], ast.Is | ast.IsNot):
            if isinstance(comparator, ast.Constant) and comparator.value is None:
                return not _is_observable_value(expression.left)
            return False
        if isinstance(expression.ops[0], ast.Eq | ast.NotEq):
            if isinstance(comparator, ast.Constant) and isinstance(comparator.value, bool):
                return not _is_bool_contract(expression.left, bool_functions)
            return False
        return False
    if isinstance(expression, ast.Call):
        return _call_name(expression) not in {"isinstance", "hasattr", "issubclass"}
    return True


def _attribute(expression: ast.expr) -> tuple[str, str] | None:
    if isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name):
        return expression.value.id, expression.attr
    return None


def _returned_call_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for statement in fn.body:
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            continue
        value = statement.value
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _findings_for_test(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    relative_path: str,
    bool_functions: set[str],
) -> list[Finding]:
    assertions = [node for node in ast.walk(fn) if isinstance(node, ast.Assert)]
    raises_or_warns = any(_has_raises_or_warns(node) for node in ast.walk(fn))
    assertion_call = _has_assertion_call(fn)
    assertion_guard = _has_assertion_guard(fn)
    finding_prefix = {"path": relative_path, "line": fn.lineno, "test": fn.name}
    findings: list[Finding] = []

    if not assertions and not raises_or_warns and not assertion_call and not assertion_guard:
        findings.append(Finding(code="no_recognized_oracle", **finding_prefix))
    if any(isinstance(assertion.test, ast.Constant) for assertion in assertions):
        findings.append(Finding(code="literal_constant_assert", **finding_prefix))
    if (
        assertions
        and all(_is_weak_assertion(assertion, bool_functions) for assertion in assertions)
        and not raises_or_warns
        and not assertion_call
        and not assertion_guard
    ):
        findings.append(Finding(code="weak_only_oracle", **finding_prefix))

    returned_names = _returned_call_names(fn)
    for assertion in assertions:
        expression = assertion.test
        if not isinstance(expression, ast.Compare) or len(expression.ops) != 1:
            continue
        if (
            not isinstance(expression.ops[0], ast.Eq | ast.NotEq)
            or len(expression.comparators) != 1
        ):
            continue
        left = _attribute(expression.left)
        right = _attribute(expression.comparators[0])
        if left and right and left[0] in returned_names and left[1] == right[1]:
            findings.append(Finding(code="return_fixture_alias_comparison", **finding_prefix))
            break
    return findings


def findings_for_path(path: Path, bool_functions: set[str]) -> list[Finding]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError, ValueError):
        return []

    try:
        relative_path = path.relative_to(ROOT).as_posix()
    except ValueError:
        relative_path = path.as_posix()

    return [
        finding
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and fn.name.startswith("test")
        for finding in _findings_for_test(fn, relative_path, bool_functions)
    ]


def scan(test_roots: Iterable[Path] = DEFAULT_TEST_ROOTS) -> list[Finding]:
    bool_functions = annotated_bool_functions()
    findings: list[Finding] = []
    for root in test_roots:
        if not root.is_dir():
            continue
        findings.extend(
            finding
            for path in root.rglob("test*.py")
            for finding in findings_for_path(path, bool_functions)
        )
    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.code))


def actionable_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Keep only syntax defects that do not depend on test-intent inference."""
    return [finding for finding in findings if finding.code in ACTIONABLE_CODES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path, help="Test roots to scan (defaults to repository tests)."
    )
    parser.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    parser.add_argument(
        "--review",
        action="store_true",
        help="Include lower-confidence no-oracle, weak-assertion, and alias signals.",
    )
    args = parser.parse_args()
    findings = scan(args.paths or DEFAULT_TEST_ROOTS)
    if not args.review:
        findings = actionable_findings(findings)
    if args.json:
        print(
            json.dumps([asdict(finding) | {"key": finding.key} for finding in findings], indent=2)
        )
    else:
        for finding in findings:
            print(f"{finding.key}")
        report = "review signals" if args.review else "actionable findings"
        print(f"assertion-quality {report}: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
