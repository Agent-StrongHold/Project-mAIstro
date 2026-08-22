"""Tests for the PR check-name contract gate (#161).

The gate exists because branch protection pins check names as **strings** and
GitHub gives no signal when a rename detaches one from its job. So the property
that matters is the same one every ratchet here needs: the gate must *fail* when
the document and the workflows disagree. A gate that passed on a stale table
would let a required check quietly stop being produced while the protection rule
kept reporting green.

Parsing is exercised on synthetic workflow trees so the tests stay hermetic. Two
tests run against the real `.github/workflows/` — one asserting the shipped table
is in the state the gate wants, one asserting no check regressed onto a
base-branch filter, which is the specific coverage hole #161 closed.
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
        """`on:` is YAML 1.1's boolean `True`, and the gate must read both.

        This is the GitHub Actions footgun that makes a workflow look like it has
        no triggers at all. Treating it as untriggered would drop every job in
        the file from the contract silently — the gate would report fewer checks
        and pass, which is precisely the failure it exists to catch.
        """
        assert gate._pull_request_trigger({True: {"pull_request": None}}) == {}
        assert gate._pull_request_trigger({"on": {"pull_request": None}}) == {}

    def test_a_workflow_with_no_pull_request_trigger_is_not_a_pr_check(self, gate) -> None:
        assert gate._pull_request_trigger({True: {"push": {"branches": ["main"]}}}) is None

    def test_no_filter_is_every_pr(self, gate) -> None:
        assert gate._scope({}) == "every PR"
        assert gate._scope(None) == "every PR"

    def test_a_base_branch_filter_is_reported_as_such(self, gate) -> None:
        """The distinction #161 turns on: `branches:` matches the PR's base."""
        assert gate._scope({"branches": ["main", "develop"]}) == "base `main`, `develop`"

    def test_a_paths_filter_is_reported_separately_from_a_base_filter(self, gate) -> None:
        """A paths filter is a function of the change, so it is not the same
        defect — but it carries its own hazard for a required check, so it must
        not be collapsed into "every PR" either."""
        assert gate._scope({"paths": ["docs/**"]}) == "paths"

    def test_a_branch_filter_wins_over_a_paths_filter(self, gate) -> None:
        assert gate._scope({"branches": ["main"], "paths": ["x"]}).startswith("base")


class TestJobLevelConditions:
    """A job `if:` can undo what the trigger promises (#161).

    Found on PR #167 itself: `security.yml`'s container scan triggers on every
    PR and then declines to run unless the base is `main`, so a trigger-only
    reading reported "every PR" for a check that reports `skipped` on most of
    them.
    """

    def test_a_base_ref_condition_narrows_the_reported_scope(self, gate) -> None:
        job = {"if": "github.event_name == 'pull_request' && github.base_ref == 'main'"}
        assert gate._job_scope(job, "every PR") == "every PR, job `if:` on base_ref"

    def test_a_condition_that_does_not_mention_base_ref_is_left_alone(self, gate) -> None:
        """Narrowing on anything else does not make the check's meaning depend
        on what the PR is stacked on, which is the property under contract."""
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
        """GitHub falls back to the job id, so the contract must too — otherwise
        the documented string would not be the string protection needs."""
        rows = [("W", "job-id", "every PR")]
        assert "`job-id`" in gate.render(rows)


class TestAgainstTheRealWorkflows:
    def test_the_shipped_table_matches_the_workflows(self, gate) -> None:
        assert gate.main() == 0

    def test_only_the_documented_exclusions_depend_on_the_base_branch(self, gate) -> None:
        """#161's acceptance, asserted rather than described.

        Both spellings count — a `branches:` filter on the trigger and a
        `base_ref` test in the job's `if:` are the same coupling at different
        depths, and the second is the one that hides. Two checks are allowed
        here and both are named in the doc's "Deliberate exclusions" table;
        anything else means a PR's tick depends on what it is stacked on.
        """
        assert gate.base_coupled(gate.collect()) == {
            ("CodeQL Advanced", "Analyze (actions)"),
            ("CodeQL Advanced", "Analyze (javascript-typescript)"),
            ("CodeQL Advanced", "Analyze (python)"),
            ("security", "Container scan + SBOM + cosign"),
        }

    def test_every_unfiltered_pr_workflow_cancels_superseded_runs(self, gate) -> None:
        """The cost answer #161 gives instead of skipping jobs on drafts.

        Dropping the base filter multiplies runner time by the push rate on every
        stacked branch. Per-PR cancellation is what pays for that: a branch
        pushed ten times costs one run, not ten. If an unfiltered workflow joins
        the PR set without it, the trade silently stops holding.

        Scoped to unfiltered workflows on purpose. `cage-guard` (paths) and
        `codeql` (base `main`) run on a small minority of PRs and were not
        widened by #161, so requiring it of them would be this test inventing
        scope rather than defending the change.

        Either per-PR expression counts: for a `pull_request` event `github.ref`
        is `refs/pull/N/merge`, which is already unique per PR — `registry.yml`
        keys on that and is correct.
        """
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
    """`on:` has more legal forms than one, and the others were dropped (found
    in review). A workflow this parser does not recognise leaves *every* check
    it produces outside the contract, and `--update` then writes a table that
    passes CI while those checks still gate merges."""

    def test_the_sequence_form_is_a_pr_trigger(self, gate) -> None:
        assert gate._pull_request_trigger({True: ["push", "pull_request"]}) == {}

    def test_a_sequence_without_pull_request_is_not(self, gate) -> None:
        assert gate._pull_request_trigger({True: ["push"]}) is None

    def test_the_bare_string_form_is_a_pr_trigger(self, gate) -> None:
        assert gate._pull_request_trigger({True: "pull_request"}) == {}


class TestIgnoreFilters:
    """`branches-ignore` is base coupling stated in the negative.

    Falling through to "every PR" would have left the generated table and
    `base_coupled()` both green while a workflow excluded whole bases — the
    exact hole #161 closed, reintroduced in a spelling the gate did not read.
    """

    def test_branches_ignore_is_reported_as_base_coupled(self, gate) -> None:
        scope = gate._scope({"branches-ignore": ["experimental"]})
        assert scope.startswith("base")
        assert gate.base_coupled([("W", "c", scope)]) == {("W", "c")}

    def test_paths_ignore_is_reported_as_filtered(self, gate) -> None:
        assert gate._scope({"paths-ignore": ["docs/**"]}) == "paths"


class TestMatrixExpansion:
    """A matrix job does not emit the name written in the YAML.

    GitHub evaluates `job.name` once per combination, so recording the
    unevaluated string handed branch protection a name no run ever produces —
    and changing the matrix would have altered three real check names with the
    gate reporting no change at all.
    """

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
        """Refusing beats recording a plausible wrong string: the wrong string
        gets banked into the table and read as the truth afterwards."""
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
        """Branch protection keys checks by bare name, not by workflow, so a
        collision gives the rule an ambiguous status to wait on — which reads
        as a stuck check rather than as a naming problem."""
        rows = [("A", "test", "every PR"), ("B", "test", "every PR")]
        with pytest.raises(gate.ContractError, match="two workflows emit"):
            gate._refuse_duplicates(rows)

    def test_one_workflow_repeating_a_name_is_not_a_collision(self, gate) -> None:
        """A matrix expanding to the same name twice is deduplicated upstream,
        not a cross-workflow ambiguity."""
        gate._refuse_duplicates([("A", "test", "every PR"), ("A", "test", "every PR")])

    def test_the_real_workflows_have_no_collisions(self, gate) -> None:
        gate._refuse_duplicates(gate.collect())


class TestWorkflowDiscovery:
    def test_both_extensions_are_scanned(self, gate) -> None:
        """GitHub honours `.yaml` too. Scanning only `.yml` meant a renamed
        workflow left every check it produces outside the contract."""
        import inspect

        source = inspect.getsource(gate._workflow_files)
        assert "*.yml" in source and "*.yaml" in source
