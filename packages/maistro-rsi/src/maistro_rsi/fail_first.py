"""Fail-first evidence for RSI code-improvement objectives (#392).

A behavior-changing objective is marked improved only when a new or changed
test failed on the exact base revision for a reason the candidate introduced,
then passed on the candidate. The promotion record keeps the base SHA, the
failing test identity, a digest of that failure output, the candidate SHA, and
the passing result.

Characterization tests (already green on the base, no demonstrated defect) are
not improvement evidence. Editing test configuration or citing a failure in a
test the candidate did not add or change cannot manufacture that evidence.
Refactors, documentation, and spec drafts do not use a red test; each has an
explicit alternative contract the evaluator enforces.
"""

from __future__ import annotations

import ast
import hashlib
import re

from maistro_evolve.scorecard import GateResult
from maistro_evolve.tdd_gate import TddEvidence, changed_test_paths

FAIL_FIRST_GATE = "fail_first_evidence"

# Shared with the objective prompts so the default objective and every
# behavior-changing sibling path make the same promise, and the evaluator can
# see which contract an objective actually offered.
FAIL_FIRST_CLAUSE = (
    "Work fail-first: add or change a test so it fails on the exact base revision "
    "for the intended reason, then change the code until that same test passes. "
    "A characterization test that already passes on the base is not improvement evidence."
)
REFACTOR_CONTRACT = "Alternative evidence contract (refactor)"
DOC_CONTRACT = "Alternative evidence contract (documentation)"
SPEC_DRAFT_CONTRACT = "Alternative evidence contract (spec-draft)"

_DOC_SUFFIXES = (".md", ".rst", ".txt")
_FAILED_NODE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)


def failure_output_digest(output: str) -> str:
    """Stable digest of a baseline failure log. Empty input has no digest."""
    if not output:
        return ""
    return hashlib.sha256(output.encode("utf-8", errors="replace")).hexdigest()


def failing_node_ids(output: str) -> list[str]:
    """Pytest node ids from ``FAILED`` summary lines, in output order."""
    return [node.replace("\\", "/") for node in _FAILED_NODE.findall(output)]


def match_introduced_failure(failed_ids: list[str], introduced: set[str]) -> str:
    """The first failure that is a test the candidate added or edited.

    Parametrized ids (``test_x.py::test_f[case]``) match the unparametrized
    function the candidate changed. Anything else is an unrelated failure.
    """
    introduced_norm = {node.replace("\\", "/") for node in introduced}
    for failed in failed_ids:
        if failed in introduced_norm:
            return failed
        bare = failed.split("[", 1)[0]
        if bare in introduced_norm:
            return bare
    return ""


def introduced_test_ids(
    baseline_sources: dict[str, str], candidate_sources: dict[str, str]
) -> set[str]:
    """Node ids of ``test_*`` functions the candidate added or whose body changed."""
    introduced: set[str] = set()
    for rel, candidate in candidate_sources.items():
        path = rel.replace("\\", "/")
        base_fns = _test_functions(baseline_sources.get(rel, ""), path)
        cand_fns = _test_functions(candidate, path)
        for node_id, dumped in cand_fns.items():
            if base_fns.get(node_id) != dumped:
                introduced.add(node_id)
    return introduced


def python_sources_are_doc_only(pairs: list[tuple[str, str]]) -> bool:
    """True when every pair differs only by docstrings, comments, or annotations.

    A missing baseline (a new module) is not documentation of existing code.
    A parse error is not documentation either — fail closed.
    """
    if not pairs:
        return True
    for baseline, candidate in pairs:
        if not baseline:
            return False
        base_fp = _doc_fingerprint(baseline)
        cand_fp = _doc_fingerprint(candidate)
        if base_fp is None or cand_fp is None or base_fp != cand_fp:
            return False
    return True


def assess_promotion_evidence(
    *,
    objective: str,
    changed_files: list[str],
    config_files_changed: list[str],
    tests_passed: bool,
    tdd: TddEvidence,
    doc_only_py: bool,
) -> GateResult:
    """Whether this objective may be marked improved / promoted (#392).

    Behavior-changing objectives (the default, and any prompt carrying
    ``FAIL_FIRST_CLAUSE``) need a prior failure of a test the candidate
    introduced. Refactor, documentation, and spec-draft prompts may instead
    meet their own contract. A characterization-only diff meets neither.
    """
    detail = _detail(tdd, passed=False, contract="")
    if not changed_files:
        detail["passed"] = True
        detail["contract"] = "none"
        return GateResult(FAIL_FIRST_GATE, True, "no candidate diff", detail)

    py_src = _source_files(changed_files)
    tests = changed_test_paths(changed_files)
    allows_fail_first = (not objective) or (FAIL_FIRST_CLAUSE in objective)
    allows_refactor = REFACTOR_CONTRACT in objective
    allows_doc = (not objective) or (DOC_CONTRACT in objective)
    allows_spec = SPEC_DRAFT_CONTRACT in objective

    ff_ok, ff_reason = _fail_first_ok(
        py_src=py_src,
        tests=tests,
        config_files_changed=config_files_changed,
        tests_passed=tests_passed,
        tdd=tdd,
    )
    if ff_ok and allows_fail_first:
        detail = _detail(tdd, passed=True, contract="fail-first")
        return GateResult(
            FAIL_FIRST_GATE,
            True,
            "fail-first evidence recorded for the base revision",
            detail,
        )

    if _is_characterization(py_src, tests, tests_passed, tdd):
        return GateResult(
            FAIL_FIRST_GATE,
            False,
            "characterization-only candidate cannot satisfy improvement evidence",
            detail,
        )

    if allows_spec and _spec_draft_ok(changed_files, tests_passed, config_files_changed):
        detail["passed"] = True
        detail["contract"] = "spec-draft"
        return GateResult(
            FAIL_FIRST_GATE,
            True,
            "spec-draft contract satisfied: spec markdown only, suite green, no code change",
            detail,
        )
    if allows_doc and _doc_ok(
        changed_files, tests, config_files_changed, tests_passed, doc_only_py
    ):
        detail["passed"] = True
        detail["contract"] = "documentation"
        return GateResult(
            FAIL_FIRST_GATE,
            True,
            "documentation contract satisfied: no behavior, oracle, or configuration change",
            detail,
        )
    if allows_refactor and _refactor_ok(
        changed_files, tests, config_files_changed, tests_passed, doc_only_py
    ):
        detail["passed"] = True
        detail["contract"] = "refactor"
        return GateResult(
            FAIL_FIRST_GATE,
            True,
            "refactor contract satisfied: oracle and configuration untouched, suite green",
            detail,
        )

    if not allows_fail_first:
        return GateResult(
            FAIL_FIRST_GATE,
            False,
            "objective has no fail-first evidence and its alternative contract is not satisfied",
            detail,
        )
    return GateResult(FAIL_FIRST_GATE, False, ff_reason, detail)


def _detail(tdd: TddEvidence, *, passed: bool, contract: str) -> dict[str, object]:
    return {
        "base_sha": tdd.base_sha,
        "failing_test_id": tdd.failing_test_id if contract == "fail-first" else "",
        "failure_output_digest": tdd.failure_output_digest if contract == "fail-first" else "",
        "candidate_sha": tdd.candidate_sha,
        "passed": passed,
        "contract": contract,
    }


def _source_files(changed_files: list[str]) -> list[str]:
    tests = set(changed_test_paths(changed_files))
    return [f for f in changed_files if f.replace("\\", "/").endswith(".py") and f not in tests]


def _is_characterization(
    py_src: list[str], tests: list[str], tests_passed: bool, tdd: TddEvidence
) -> bool:
    """A test-only diff that is already green: a snapshot, not a defect."""
    return bool(tests) and not py_src and tests_passed and tdd.baseline_changed_rc in (None, 0)


def _fail_first_ok(
    *,
    py_src: list[str],
    tests: list[str],
    config_files_changed: list[str],
    tests_passed: bool,
    tdd: TddEvidence,
) -> tuple[bool, str]:
    if config_files_changed:
        return False, "failure manufactured by editing test configuration/oracle"
    if not py_src or not tests:
        return False, "missing fail-first evidence"
    if tdd.baseline_execution_failed or tdd.baseline_changed_rc is None:
        return False, "non-reproducible fail-first evidence"
    if tdd.baseline_changed_rc == 0:
        return False, "already-passing on the base revision"
    if tdd.candidate_changed_rc != 0 or not tests_passed:
        return False, "missing fail-first evidence: passing result absent"
    if not tdd.base_sha or not tdd.candidate_sha:
        return False, "non-reproducible fail-first evidence"
    introduced = set(tdd.introduced_test_ids)
    if tdd.baseline_failure_ids and (
        not tdd.failing_test_id or tdd.failing_test_id not in introduced
    ):
        return False, "unrelated fail-first evidence"
    if not tdd.failing_test_id or tdd.failing_test_id not in introduced:
        return False, "missing fail-first evidence"
    if not tdd.failure_output_digest:
        return False, "missing fail-first evidence"
    return True, "ok"


def _spec_draft_ok(
    changed_files: list[str], tests_passed: bool, config_files_changed: list[str]
) -> bool:
    if not tests_passed or config_files_changed or not changed_files:
        return False
    for rel in changed_files:
        norm = rel.replace("\\", "/")
        if not (norm.startswith("docs/specs/") and norm.endswith(".md")):
            return False
    return True


def _doc_ok(
    changed_files: list[str],
    tests: list[str],
    config_files_changed: list[str],
    tests_passed: bool,
    doc_only_py: bool,
) -> bool:
    if not tests_passed or tests or config_files_changed or not changed_files:
        return False
    saw_doc = False
    for rel in changed_files:
        norm = rel.replace("\\", "/")
        if norm.endswith(_DOC_SUFFIXES):
            saw_doc = True
            continue
        if norm.endswith(".py"):
            if not doc_only_py:
                return False
            saw_doc = True
            continue
        return False
    return saw_doc


def _refactor_ok(
    changed_files: list[str],
    tests: list[str],
    config_files_changed: list[str],
    tests_passed: bool,
    doc_only_py: bool,
) -> bool:
    if not tests_passed or tests or config_files_changed or doc_only_py:
        return False
    return bool(_source_files(changed_files))


def _test_functions(source: str, rel: str) -> dict[str, str]:
    if not source:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: dict[str, str] = {}

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._classes: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._classes.append(node.name)
            self.generic_visit(node)
            self._classes.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._record(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._record(node)

        def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if node.name.startswith("test_"):
                parts = [*self._classes, node.name]
                found[f"{rel}::{'::'.join(parts)}"] = ast.dump(node)
            # Nested tests are not pytest node ids; do not walk into the body.

    _Visitor().visit(tree)
    return found


def _doc_fingerprint(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in list(ast.walk(tree)):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and _is_docstring(body[0]):
            node.body = body[1:]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.returns = None
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                arg.annotation = None
            if args.vararg is not None:
                args.vararg.annotation = None
            if args.kwarg is not None:
                args.kwarg.annotation = None
        elif isinstance(node, ast.AnnAssign):
            node.annotation = None
    return ast.dump(tree)


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )
