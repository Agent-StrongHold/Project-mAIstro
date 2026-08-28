"""Tests for the PR check-name contract gate (#161).

The gate exists because branch protection pins check names as **strings** and
GitHub gives no signal when a rename detaches one from its job. So the property
that matters is the same one every ratchet here needs: the gate must *fail* when
the document and the workflows disagree. A gate that passed on a stale table
would let a required check quietly stop being produced while the protection rule
kept reporting green.

Parsing is exercised on synthetic workflow trees so the tests stay hermetic. The
real-workflow tests also prove that every ordinary check required on `develop`
can report on GitHub's synthetic merge-group SHA.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-required-checks.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_required_checks", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workflow(**triggers) -> dict:
    return {"name": "W", "on": triggers, "jobs": {"j": {"name": "J"}}}


class TestTriggerParsing:
    def test_on_parsed_as_yaml_true_is_still_read(self, gate) -> None:
        assert gate._pull_request_trigger({True: {"pull_request": None}}) == {}
        assert gate._pull_request_trigger({"on": {"pull_request": None}}) == {}

    def test_a_workflow_with_no_pull_request_trigger_is_not_a_pr_check(self, gate) -> None:
        assert gate._pull_request_trigger({True: {"push": {"branches": ["main"]}}}) is None

    def test_no_filter_is_every_pr(self, gate) -> None:
        assert gate._scope({}) == "every PR"
        assert gate._scope(None) == "every PR"

    def test_a_base_branch_filter_is_reported_as_such(self, gate) -> None:
        assert gate._scope({"branches": ["main", "develop"]}) == "base `main`, `develop`"

    def test_a_paths_filter_is_reported_separately_from_a_base_filter(self, gate) -> None:
        assert gate._scope({"paths": ["docs/**"]}) == "paths"

    def test_a_branch_filter_wins_over_a_paths_filter(self, gate) -> None:
        assert gate._scope({"branches": ["main"], "paths": ["x"]}).startswith("base")

    def test_merge_group_checks_requested_is_queue_capable(self, gate) -> None:
        doc = {True: {"merge_group": {"types": ["checks_requested"]}}}
        assert gate._merge_group_trigger(doc) == {"types": ["checks_requested"]}

    def test_merge_group_with_the_wrong_type_is_not_queue_capable(self, gate) -> None:
        doc = {True: {"merge_group": {"types": ["destroyed"]}}}
        assert gate._merge_group_trigger(doc) is None

    def test_absent_merge_group_is_not_queue_capable(self, gate) -> None:
        assert gate._merge_group_trigger({True: {"pull_request": None}}) is None


class TestJobLevelConditions:
    def test_a_base_ref_condition_narrows_the_reported_scope(self, gate) -> None:
        job = {"if": "github.event_name == 'pull_request' && github.base_ref == 'main'"}
        assert gate._job_scope(job, "every PR") == "every PR, job `if:` on base_ref"

    def test_a_condition_that_does_not_mention_base_ref_is_left_alone(self, gate) -> None:
        assert gate._job_scope({"if": "always()"}, "every PR") == "every PR"

    def test_a_job_with_no_condition_keeps_its_trigger_scope(self, gate) -> None:
        assert gate._job_scope({}, "every PR") == "every PR"

    def test_base_coupled_reports_both_spellings(self, gate) -> None:
        rows = [
            ("A", "by-trigger", "base `main`"),
            ("B", "by-job-if", "every PR, job `if:` on base_ref"),
            ("C", "clean", "every PR"),
            ("D", "paths", "paths"),
        ]
        assert gate.base_coupled(rows) == {("A", "by-trigger"), ("B", "by-job-if")}


class TestRendering:
    def test_a_job_without_a_name_is_listed_by_its_id(self, gate) -> None:
        rows = [("W", "job-id", "every PR")]
        assert "`job-id`" in gate.render(rows)


class TestAgainstTheRealWorkflows:
    def test_the_shipped_table_matches_the_workflows(self, gate) -> None:
        assert gate.main() == 0

    def test_all_required_develop_producers_are_merge_queue_capable(self, gate) -> None:
        assert gate.merge_group_gaps(gate.collect()) == []

    def test_only_the_documented_exclusions_depend_on_the_base_branch(self, gate) -> None:
        assert gate.base_coupled(gate.collect()) == {
            ("CodeQL Advanced", "Analyze (actions)"),
            ("CodeQL Advanced", "Analyze (javascript-typescript)"),
            ("CodeQL Advanced", "Analyze (python)"),
            ("security", "Container scan + SBOM + cosign"),
        }

    def test_every_unfiltered_pr_workflow_cancels_superseded_runs(self, gate) -> None:
        offenders = []
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            doc = yaml.safe_load(path.read_text()) or {}
            pull_request = gate._pull_request_trigger(doc)
            if pull_request is None or gate._scope(pull_request) != "every PR":
                continue
            concurrency = doc.get("concurrency") or {}
            group = str(concurrency.get("group", ""))
            per_pr = "pull_request.number" in group or "github.ref" in group
            cancels = str(concurrency.get("cancel-in-progress", "")).lower() not in ("", "false")
            if not (per_pr and cancels):
                offenders.append(path.name)
        assert offenders == [], f"unfiltered PR workflows without per-PR cancellation: {offenders}"


class TestTriggerSpellings:
    def test_the_sequence_form_is_a_pr_trigger(self, gate) -> None:
        assert gate._pull_request_trigger({True: ["push", "pull_request"]}) == {}

    def test_a_sequence_without_pull_request_is_not(self, gate) -> None:
        assert gate._pull_request_trigger({True: ["push"]}) is None

    def test_the_bare_string_form_is_a_pr_trigger(self, gate) -> None:
        assert gate._pull_request_trigger({True: "pull_request"}) == {}

    def test_the_sequence_form_can_include_merge_group(self, gate) -> None:
        assert gate._merge_group_trigger({True: ["pull_request", "merge_group"]}) == {}


class TestIgnoreFilters:
    def test_branches_ignore_is_reported_as_base_coupled(self, gate) -> None:
        scope = gate._scope({"branches-ignore": ["experimental"]})
        assert scope.startswith("base")
        assert gate.base_coupled([("W", "c", scope)]) == {("W", "c")}

    def test_paths_ignore_is_reported_as_filtered(self, gate) -> None:
        assert gate._scope({"paths-ignore": ["docs/**"]}) == "paths"


class TestMatrixExpansion:
    def test_an_include_matrix_expands_to_one_name_each(self, gate) -> None:
        job = {
            "name": "Analyze (${{ matrix.language }})",
            "strategy": {"matrix": {"include": [{"language": "python"}, {"language": "actions"}]}},
        }
        assert gate._check_names("analyze", job) == ["Analyze (python)", "Analyze (actions)"]

    def test_axes_expand_as_a_product(self, gate) -> None:
        job = {
            "name": "t (${{ matrix.os }}, ${{ matrix.py }})",
            "strategy": {"matrix": {"os": ["linux", "mac"], "py": ["3.12"]}},
        }
        assert gate._check_names("t", job) == ["t (linux, 3.12)", "t (mac, 3.12)"]

    def test_a_literal_name_is_left_alone(self, gate) -> None:
        assert gate._check_names("j", {"name": "plain"}) == ["plain"]

    def test_a_job_with_no_name_uses_its_id(self, gate) -> None:
        assert gate._check_names("job-id", {}) == ["job-id"]

    def test_an_unresolvable_expression_is_refused_not_guessed(self, gate) -> None:
        with pytest.raises(gate.ContractError, match="cannot resolve"):
            gate._check_names("j", {"name": "x (${{ github.sha }})"})

    def test_matrix_exclude_is_refused_rather_than_approximated(self, gate) -> None:
        job = {
            "name": "t (${{ matrix.os }})",
            "strategy": {"matrix": {"os": ["a", "b"], "exclude": [{"os": "b"}]}},
        }
        with pytest.raises(gate.ContractError, match="exclude"):
            gate._check_names("t", job)


class TestDuplicateNames:
    def test_two_workflows_emitting_one_name_are_refused(self, gate) -> None:
        rows = [("A", "test", "every PR"), ("B", "test", "every PR")]
        with pytest.raises(gate.ContractError, match="two workflows emit"):
            gate._refuse_duplicates(rows)

    def test_one_workflow_repeating_a_name_is_not_a_collision(self, gate) -> None:
        gate._refuse_duplicates([("A", "test", "every PR"), ("A", "test", "every PR")])

    def test_the_real_workflows_have_no_collisions(self, gate) -> None:
        gate._refuse_duplicates(gate.collect())


class TestWorkflowDiscovery:
    def test_both_extensions_are_scanned(self, gate) -> None:
        import inspect

        source = inspect.getsource(gate._workflow_files)
        assert "*.yml" in source and "*.yaml" in source
