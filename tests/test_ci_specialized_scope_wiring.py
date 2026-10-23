from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.ci_merge_group_scope import scope_for_event

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CONTRACT_SCRIPT = ROOT / "scripts" / "check-required-checks.py"

SPECIALIZED = {
    "postgres": "postgres",
    "object-storage": "object_storage",
    "durable-events": "durable_events",
    "strike-ladder": "strike_ladder",
    "hive-conductor-e2e": "hive_e2e",
    "hive-conductor-e2e-ui": "hive_e2e",
    "wheel-imports": "wheel_imports",
    "docker-build": "docker_build",
}


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _contract_gate():
    loader = importlib.util.spec_from_file_location
    spec = loader("_ci_scope_required_checks", CONTRACT_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# A minimal evaluator for the GitHub-expression subset the specialized scope
# gates use: dotted identifiers, single-quoted string literals, ==, !=, &&,
# ||, and parentheses. Structural substring assertions cannot tell a policy
# where PRs are unconditionally enabled from one gated on the classifier
# output; evaluating the condition can (#1351). An unknown identifier raises,
# so a condition drifting to an unmodelled form fails the test loudly.
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"\s*(\(|\)|&&|\|\||==|!=|'[^']*'|[A-Za-z][A-Za-z0-9_.\-]*)")


def _tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = _TOKEN_RE.match(expression, position)
        if match is None:
            if expression[position:].strip() == "":
                break
            raise ValueError(f"unmodelled expression syntax at: {expression[position:]!r}")
        tokens.append(match.group(1))
        position = match.end()
    return tokens


#: Parsed conditions: ``("or"|"and", left, right)`` or ``("cmp", ident, op, literal)``.
Condition = tuple


class _ConditionParser:
    """Recursive descent over the full token stream (no evaluation yet), so
    short-circuiting later never leaves tokens unconsumed."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self) -> str:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _comparison(self) -> Condition:
        left = self._take()
        operator = self._take()
        right = self._take()
        if operator not in ("==", "!="):
            raise ValueError(f"unmodelled operator: {operator!r}")
        if len(right) >= 2 and right[0] == "'" and right[-1] == "'":
            right = right[1:-1]
        return ("cmp", left, operator, right)

    def _atom(self) -> Condition:
        if self._peek() == "(":
            self._take()
            value = self._or_expr()
            if self._take() != ")":
                raise ValueError("unbalanced parentheses")
            return value
        return self._comparison()

    def _and_expr(self) -> Condition:
        value = self._atom()
        while self._peek() == "&&":
            self._take()
            value = ("and", value, self._atom())
        return value

    def _or_expr(self) -> Condition:
        value = self._and_expr()
        while self._peek() == "||":
            self._take()
            value = ("or", value, self._and_expr())
        return value

    def parse(self) -> Condition:
        result = self._or_expr()
        if self.index != len(self.tokens):
            raise ValueError(f"trailing tokens: {self.tokens[self.index :]!r}")
        return result


def _parse_condition(tokens: list[str]) -> Condition:
    return _ConditionParser(tokens).parse()


def _eval_condition(condition: Condition, env: Mapping[str, str]) -> bool:
    kind = condition[0]
    if kind == "or":
        # Python's own short-circuit: a false-guarded right side (e.g. the
        # merge_group clauses on a pull_request event) is never evaluated, so
        # identifiers it names need not be in `env`.
        return _eval_condition(condition[1], env) or _eval_condition(condition[2], env)
    if kind == "and":
        return _eval_condition(condition[1], env) and _eval_condition(condition[2], env)
    _, identifier, operator, literal = condition
    if identifier not in env:
        raise KeyError(f"condition references an unmodelled identifier: {identifier!r}")
    return (env[identifier] == literal) if operator == "==" else (env[identifier] != literal)


def evaluate_github_expression(expression: str, env: Mapping[str, str]) -> bool:
    """Evaluate one scope-gate condition; raise on unknown identifiers."""
    return _eval_condition(_parse_condition(_tokenize(expression)), env)


def test_required_workflow_lint_job_emits_every_specialized_leg() -> None:
    scope = _jobs()["workflow-lint"]
    outputs = scope["outputs"]
    assert set(outputs) == set(SPECIALIZED.values())

    prefix = "${{ steps.scope.outputs."
    output_refs_are_scoped = [value.startswith(prefix) for value in outputs.values()]
    assert all(output_refs_are_scoped)

    checkout = scope["steps"][0]
    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["with"]["fetch-depth"] == 0

    command = scope["steps"][1]["run"]
    assert "ci_merge_group_scope.py --github-outputs" in command
    assert "$GITHUB_OUTPUT" in command


def test_specialized_scope_gates_preserve_required_matrix_contexts() -> None:
    jobs = _jobs()
    # Both candidate events are path-scoped (#1351): the only clause that can
    # enable a job on pull_request or a develop merge group is the classifier
    # output guard. Non-candidate events and foreign merge bases keep the
    # unconditional escapes.
    event_escape = "(github.event_name != 'merge_group' && github.event_name != 'pull_request')"
    base_escape = (
        "(github.event_name == 'merge_group'"
        " && github.event.merge_group.base_ref != 'refs/heads/develop')"
    )

    for job_name, output in SPECIALIZED.items():
        job = jobs[job_name]
        assert job["needs"] == "workflow-lint", job_name

        if job_name == "postgres":
            # GitHub evaluates job-level if before expanding the matrix. A
            # skipped matrix cannot report the two required concrete names.
            assert "if" not in job, job_name
            continue

        condition = job["if"]
        output_guard = f"needs.workflow-lint.outputs.{output} == 'true'"
        assert event_escape in condition, job_name
        assert base_escape in condition, job_name
        assert output_guard in condition, job_name


@pytest.mark.parametrize("leg_output", ["true", "false"])
def test_pull_request_scope_gate_is_exactly_the_classifier_output(
    leg_output: str,
) -> None:
    """On a pull_request event, a specialized job runs iff its measured leg
    is selected -- the same policy gates-ran judges the head with (#1351)."""
    jobs = _jobs()
    for job_name, output in SPECIALIZED.items():
        if job_name == "postgres":
            continue
        condition = jobs[job_name]["if"]
        env = {
            "github.event_name": "pull_request",
            f"needs.workflow-lint.outputs.{output}": leg_output,
        }
        assert evaluate_github_expression(condition, env) is (leg_output == "true"), job_name


@pytest.mark.parametrize("leg_output", ["true", "false"])
def test_develop_merge_group_scope_gate_is_exactly_the_classifier_output(
    leg_output: str,
) -> None:
    jobs = _jobs()
    for job_name, output in SPECIALIZED.items():
        if job_name == "postgres":
            continue
        condition = jobs[job_name]["if"]
        env = {
            "github.event_name": "merge_group",
            "github.event.merge_group.base_ref": "refs/heads/develop",
            f"needs.workflow-lint.outputs.{output}": leg_output,
        }
        assert evaluate_github_expression(condition, env) is (leg_output == "true"), job_name


def test_non_candidate_events_and_foreign_merge_bases_run_unconditionally() -> None:
    """Protected pushes and merge groups targeting any other base are not
    path-scoped candidates: every specialized job must run even when the
    classifier output says false."""
    jobs = _jobs()
    for job_name, output in SPECIALIZED.items():
        if job_name == "postgres":
            continue
        condition = jobs[job_name]["if"]
        push = {
            "github.event_name": "push",
            f"needs.workflow-lint.outputs.{output}": "false",
        }
        assert evaluate_github_expression(condition, push) is True, job_name
        foreign = {
            "github.event_name": "merge_group",
            "github.event.merge_group.base_ref": "refs/heads/main",
            f"needs.workflow-lint.outputs.{output}": "false",
        }
        assert evaluate_github_expression(condition, foreign) is True, job_name


@pytest.mark.parametrize(
    ("changed_path", "postgres_in_scope"),
    [
        ("docs/ci/MERGE-QUEUE.md", False),
        ("packages/hive-conductor/backend/services/evolution.py", False),
        ("alembic.ini", True),
        ("uv.lock", True),
    ],
)
def test_postgres_matrix_is_not_filtered_by_merge_group_path_scope(
    changed_path: str, postgres_in_scope: bool
) -> None:
    scope = scope_for_event("merge_group", [changed_path])
    assert scope["postgres"] is postgres_in_scope
    # Scope remains truthful for its other consumers, but cannot suppress the
    # matrix GitHub requires on every merge-group head, even for docs/Hive.
    postgres = _jobs()["postgres"]
    assert postgres["needs"] == "workflow-lint"
    assert "if" not in postgres
    assert all("if" not in step for step in postgres["steps"])


def test_postgres_matrix_keeps_both_required_names_and_real_database_checks() -> None:
    postgres = _jobs()["postgres"]
    versions = postgres["strategy"]["matrix"]["postgres"]
    assert versions == ["17", "18"]
    names = {postgres["name"].replace("${{ matrix.postgres }}", version) for version in versions}
    assert names == {"postgres (pg17)", "postgres (pg18)"}
    assert postgres["strategy"]["fail-fast"] is False
    assert postgres["services"]["postgres"]["image"] == "pgvector/pgvector:pg${{ matrix.postgres }}"
    assert not postgres.get("continue-on-error", False)
    steps = postgres["steps"]
    assert all(not step.get("continue-on-error", False) for step in steps)
    commands = "\n".join(step.get("run", "") for step in steps)
    for required in (
        "uv run pytest tests/migrations/test_migration_chain.py",
        "uv run alembic upgrade head",
        "uv run alembic downgrade base",
        "uv run pytest packages/maistro-core/tests/persistence",
        "uv run pytest packages/maistro-core/tests/test_container_postgres.py",
        "uv run pytest packages/maistro-core/tests/workspaces",
    ):
        assert required in commands
    workspace = next(step for step in steps if "tests/workspaces" in step.get("run", ""))
    assert workspace["env"]["MAISTRO_REQUIRE_PG_LEGS"] == "1"


def test_postgres_matrix_is_not_filtered_by_pull_request_path_scope() -> None:
    # Same constraint on the other path-scoped event (#1351): the classifier
    # may deselect the postgres leg for a PR, but the matrix job still runs.
    scope = scope_for_event("pull_request", ["docs/ci/MERGE-QUEUE.md"])
    assert scope["postgres"] is False
    postgres = _jobs()["postgres"]
    assert "if" not in postgres
    assert all("if" not in step for step in postgres["steps"])


def test_merge_group_base_targeting_does_not_narrow_the_pr_check_contract() -> None:
    gate = _contract_gate()
    merge_condition = _jobs()["docker-build"]["if"]
    merge_scope = gate._job_scope({"if": merge_condition}, "every PR")
    assert merge_scope == "every PR"

    pr_condition = "github.event_name == 'pull_request' && github.base_ref == 'main'"
    pr_scope = gate._job_scope({"if": pr_condition}, "every PR")
    assert pr_scope == "every PR, job `if:` on base_ref"


def test_scope_producer_reuses_an_existing_required_check() -> None:
    jobs = _jobs()
    assert "specialized-scope" not in jobs
    assert "workflow-lint" in jobs


def test_unconditional_core_jobs_do_not_depend_on_a_new_scope_check() -> None:
    jobs = _jobs()
    core_jobs = ("test", "lint-and-type-check", "workflow-lint", "security")
    for job_name in core_jobs:
        assert jobs[job_name].get("needs") != "specialized-scope", job_name
