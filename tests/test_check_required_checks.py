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
import json
import sys
from pathlib import Path
from typing import ClassVar

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
        assert gate.base_coupled(rows) == {
            ("A", "by-trigger"),
            ("B", "by-job-if"),
        }


class TestRendering:
    def test_a_job_without_a_name_is_listed_by_its_id(self, gate) -> None:
        rows = [("W", "job-id", "every PR")]
        assert "`job-id`" in gate.render(rows)


class TestMergeQueueRatchet:
    @staticmethod
    def _write_contracts(
        tmp_path: Path,
        *,
        method: str = "SQUASH",
        max_merge: object = 1,
        min_merge: object = 1,
        wait_minutes: object = 2,
        grouping: object = "ALLGREEN",
    ):
        """Default to the reviewed batching posture; override one knob per test.

        The queue knobs are typed ``object`` because the fail-closed tests must
        be able to write values GitHub would never accept (strings, floats,
        booleans) and prove the gate refuses them anyway.
        """
        protection = tmp_path / "protection.json"
        protection.write_text(
            json.dumps({"branches": {"develop": {"required_status_checks": {"contexts": ["J"]}}}}),
            encoding="utf-8",
        )
        queue = tmp_path / "queue.json"
        queue.write_text(
            json.dumps(
                {
                    "branches": {
                        "develop": {
                            "merge_method": method,
                            "min_entries_to_merge": min_merge,
                            "max_entries_to_merge": max_merge,
                            "min_entries_to_merge_wait_minutes": wait_minutes,
                            "grouping_strategy": grouping,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return protection, queue

    @staticmethod
    def _queue_capable_workflow(tmp_path: Path) -> Path:
        workflow = tmp_path / "w.yml"
        workflow.write_text(
            yaml.safe_dump(
                {
                    "name": "W",
                    "on": {"merge_group": {"types": ["checks_requested"]}},
                    "jobs": {"j": {"name": "J"}},
                }
            ),
            encoding="utf-8",
        )
        return workflow

    def _policy_gaps(self, gate, tmp_path, monkeypatch, **policy) -> list[str]:
        """Gaps for a queue contract carrying only policy-level violations."""
        protection, queue = self._write_contracts(tmp_path, **policy)
        workflow = self._queue_capable_workflow(tmp_path)
        monkeypatch.setattr(gate, "PROTECTION", protection)
        monkeypatch.setattr(gate, "MERGE_QUEUE", queue)
        monkeypatch.setattr(gate, "_workflow_files", lambda: [workflow])
        return gate.merge_group_gaps([("W", "J", "every PR")])

    def test_missing_protection_contract_fails_closed(self, gate, tmp_path, monkeypatch) -> None:
        queue = tmp_path / "queue.json"
        queue.write_text("{}\n", encoding="utf-8")
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(gate, "PROTECTION", tmp_path / "protection.json")
        monkeypatch.setattr(gate, "MERGE_QUEUE", queue)

        assert gate.merge_group_gaps([]) == ["protection.json does not exist"]

    def test_missing_merge_queue_contract_fails_closed(self, gate, tmp_path, monkeypatch) -> None:
        protection = tmp_path / "protection.json"
        protection.write_text("{}\n", encoding="utf-8")
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(gate, "PROTECTION", protection)
        monkeypatch.setattr(gate, "MERGE_QUEUE", tmp_path / "queue.json")

        assert gate.merge_group_gaps([]) == ["queue.json does not exist"]

    def test_a_required_producer_without_merge_group_is_rejected(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        protection, queue = self._write_contracts(tmp_path)
        workflow = tmp_path / "w.yml"
        workflow.write_text(
            yaml.safe_dump(
                {
                    "name": "W",
                    "on": {"pull_request": None},
                    "jobs": {"j": {"name": "J"}},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "PROTECTION", protection)
        monkeypatch.setattr(gate, "MERGE_QUEUE", queue)
        monkeypatch.setattr(gate, "_workflow_files", lambda: [workflow])
        assert gate.merge_group_gaps([("W", "J", "every PR")]) == [
            "'J' is required on develop but 'W' has no merge_group gate"
        ]

    def test_squash_is_required(self, gate, tmp_path, monkeypatch) -> None:
        assert "develop merge queue must use merge_method=SQUASH" in self._policy_gaps(
            gate, tmp_path, monkeypatch, method="MERGE"
        )

    def test_batching_up_to_three_prs_per_group_is_the_reviewed_posture(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        assert self._policy_gaps(gate, tmp_path, monkeypatch, max_merge=3, wait_minutes=2) == []

    def test_the_shipped_conservative_group_size_remains_valid(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        assert self._policy_gaps(gate, tmp_path, monkeypatch, max_merge=1, wait_minutes=0) == []

    @pytest.mark.parametrize("max_merge", [0, 4, "3", 2.0, True])
    def test_a_group_size_outside_the_reviewed_range_fails_closed(
        self, gate, tmp_path, monkeypatch, max_merge
    ) -> None:
        gaps = self._policy_gaps(gate, tmp_path, monkeypatch, max_merge=max_merge)
        assert any("PRs per group" in gap for gap in gaps)

    def test_min_entries_above_max_entries_is_rejected(self, gate, tmp_path, monkeypatch) -> None:
        gaps = self._policy_gaps(gate, tmp_path, monkeypatch, max_merge=3, min_merge=4)
        assert any("min_entries_to_merge" in gap for gap in gaps)

    def test_a_zero_min_entry_group_is_rejected(self, gate, tmp_path, monkeypatch) -> None:
        gaps = self._policy_gaps(gate, tmp_path, monkeypatch, min_merge=0)
        assert any("min_entries_to_merge" in gap for gap in gaps)

    @pytest.mark.parametrize("wait_minutes", [0, 2, 3, 5])
    def test_every_reviewed_wait_value_is_accepted(
        self, gate, tmp_path, monkeypatch, wait_minutes
    ) -> None:
        assert self._policy_gaps(gate, tmp_path, monkeypatch, wait_minutes=wait_minutes) == []

    @pytest.mark.parametrize("wait_minutes", [1, 4, 30, "2", True])
    def test_an_unreviewed_wait_value_fails_closed(
        self, gate, tmp_path, monkeypatch, wait_minutes
    ) -> None:
        gaps = self._policy_gaps(gate, tmp_path, monkeypatch, wait_minutes=wait_minutes)
        assert any("min_entries_to_merge_wait_minutes" in gap for gap in gaps)

    @pytest.mark.parametrize("grouping", ["HEADGREEN", "allgreen", None, True])
    def test_any_grouping_other_than_allgreen_fails_closed(
        self, gate, tmp_path, monkeypatch, grouping
    ) -> None:
        """Batching is safe only because ALLGREEN judges every member on its own
        entry. HEADGREEN would merge a whole group on the head entry's checks,
        so the strategy is part of the reviewed posture the gate pins."""
        gaps = self._policy_gaps(gate, tmp_path, monkeypatch, grouping=grouping)
        assert gaps == [
            "develop merge queue must use grouping_strategy=ALLGREEN "
            f"(every grouped candidate must pass its own checks); got {grouping!r}"
        ]

    def test_a_malformed_queue_contract_fails_closed(self, gate, tmp_path, monkeypatch) -> None:
        protection, _queue = self._write_contracts(tmp_path)
        queue = tmp_path / "queue.json"
        queue.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(gate, "PROTECTION", protection)
        monkeypatch.setattr(gate, "MERGE_QUEUE", queue)
        gaps = gate.merge_group_gaps([])
        assert len(gaps) == 1 and "is not readable JSON" in gaps[0]

    def test_a_malformed_protection_contract_fails_closed(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        _protection, queue = self._write_contracts(tmp_path)
        protection = tmp_path / "protection.json"
        protection.write_text("[", encoding="utf-8")
        monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(gate, "PROTECTION", protection)
        monkeypatch.setattr(gate, "MERGE_QUEUE", queue)
        gaps = gate.merge_group_gaps([])
        assert len(gaps) == 1 and "is not readable JSON" in gaps[0]


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
            ("DevSkim", "DevSkim"),
            ("security", "Container scan + SBOM + cosign"),
            ("DevSkim", "DevSkim"),
        }

    def test_advisory_devskim_is_not_required_on_either_branch(self, gate) -> None:
        protection = json.loads((ROOT / ".github" / "branch-protection.json").read_text())
        assert protection["advisory"]["DevSkim"]
        for branch in ("develop", "main"):
            contexts = protection["branches"][branch]["required_status_checks"]["contexts"]
            assert "DevSkim" not in contexts

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
            cancels = str(concurrency.get("cancel-in-progress", "")).lower() not in (
                "",
                "false",
            )
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
        assert gate._check_names("analyze", job) == [
            "Analyze (python)",
            "Analyze (actions)",
        ]

    def test_axes_expand_as_a_product(self, gate) -> None:
        job = {
            "name": "t (${{ matrix.os }}, ${{ matrix.py }})",
            "strategy": {"matrix": {"os": ["linux", "mac"], "py": ["3.12"]}},
        }
        assert gate._check_names("t", job) == [
            "t (linux, 3.12)",
            "t (mac, 3.12)",
        ]

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


class TestPathsFilters:
    """The `paths:` filter map check-gates-ran.py consumes to excuse a
    path-filtered producer's absence (#2059). The globs stay raw here: the
    evaluator owns the match semantics, this module owns the trigger
    contract, and a filter the contract cannot express fails loudly."""

    #: The shipped tree's one path-filtered producer. Hard-coded on purpose:
    #: a change to mutation.yml's filter is a change to which PRs see the
    #: gate at all, and must come with this list updated under review.
    #:
    #: Synced with develop's row as synced at the #2059 develop-sync merge:
    #: #2120 added the image-pin registry, #2371 the grant ledger and the
    #: testing-inventory notes, #2432 gate scripts, #2345 dev-tool
    #: requirements and repair notes, #2450 lock/manifest metadata and the
    #: Trivy suppression registry, #2442 npm dependency metadata at any
    #: packages/ depth (its react bump lives in
    #: packages/hive-conductor/tests/e2e), #2485 the same npm metadata for
    #: package frontends (its @eslint/js bump lives in
    #: packages/hive-conductor/frontend) -- each a PR surface class that
    #: otherwise never triggered the producer and left its required row
    #: permanently absent (rationale in mutation.yml itself).
    SHIPPED: ClassVar[dict[str, list[str]]] = {
        "Mutation gate (changed critical lines)": [
            "packages/**/*.py",
            "quality/mutation-critical-files.json",
            "quality/mutation-baseline.json",
            "quality/image-pins.json",
            "quality/ratchet-authorizations.json",
            "docs/testing/inventory-notes/**",
            "scripts/**/*.py",
            ".github/workflows/mutation.yml",
            "requirements-dev-tools.txt",
            "REPAIR-NOTES-*.md",
            "uv.lock",
            "packages/**/pyproject.toml",
            ".trivyignore.yaml",
            "packages/**/package.json",
            "packages/**/package-lock.json",
        ]
    }

    def test_the_shipped_mutation_filter_is_discovered(self, gate) -> None:
        assert gate.paths_filters() == self.SHIPPED

    @staticmethod
    def _gh_paths_filter_matches(globs: list[str], path: str) -> bool:
        """Model GitHub's pull_request.paths filter semantics for the subset
        the shipped globs use: literal path segments, `*` inside one segment
        (never crossing `/`), and `**` as a whole segment (zero or more
        directories). Anything else fails loudly instead of guessing, so a
        future filter entry the model cannot express breaks this pin rather
        than silently weakening it."""
        import re

        def compile_one(g: str) -> str:
            segments = g.split("/")
            pieces: list[str] = []
            for i, segment in enumerate(segments):
                if segment == "**":
                    # A trailing `**` also matches files directly under the
                    # prefix, not only deeper directories; an interior one
                    # spans zero or more whole directories.
                    pieces.append("(?:[^/]+/)*.+" if i == len(segments) - 1 else "(?:[^/]+/)*")
                    continue
                if "**" in segment or any(ch in segment for ch in "?[]{}"):
                    raise ValueError(f"unmodeled glob segment: {g!r}")
                pieces.append("".join("[^/]*" if ch == "*" else re.escape(ch) for ch in segment))
                if i < len(segments) - 1:
                    pieces.append("/")
            return "".join(pieces)

        patterns = [re.compile(compile_one(g) + r"\Z") for g in globs]
        return any(p.fullmatch(path) for p in patterns)

    def test_npm_dependency_metadata_is_inside_the_mutation_producer_trigger(self, gate) -> None:
        """Replay of the #2442 incident (head 251b4e2e71eb, react 19.2.0 ->
        19.3.1 in packages/hive-conductor/tests/e2e). The bump touched only
        packages/**/package.json + package-lock.json, so mutation.yml's
        paths filter never fired: 73/74 required checks landed green and
        `Mutation gate (changed critical lines)` stayed absent, leaving the
        gates-ran publisher permanently pending ("commit status not
        successful"). The filter must cover the whole npm-metadata class
        under GitHub's own match semantics, while staying class-separated
        from the mutation-critical Python sources it must never silently
        widen to."""
        globs = self.SHIPPED["Mutation gate (changed critical lines)"]
        matches = self._gh_paths_filter_matches
        # The exact incident envelope, plus the other npm surfaces in the
        # repo (three manifests and three lockfiles across packages/).
        for covered in (
            "packages/hive-conductor/tests/e2e/package.json",
            "packages/hive-conductor/tests/e2e/package-lock.json",
            "packages/hive-conductor/frontend/package.json",
            "packages/hive-conductor/frontend/package-lock.json",
            "packages/maistro-canvas/frontend/package.json",
            "packages/maistro-canvas/frontend/package-lock.json",
            # An existing single-segment glob, so the matcher itself is
            # proven on shipped syntax rather than only on the new entries.
            "REPAIR-NOTES-cr-2442.md",
        ):
            assert matches(globs, covered), covered
        # Wrong-reason guards: the npm globs must not swallow neighbouring
        # classes. A critical Python source is covered by the filter (the
        # producer must fire there too), but never by the npm-metadata
        # entries; a sibling test asset is not covered at all.
        assert not matches(
            ["packages/**/package.json", "packages/**/package-lock.json"],
            "packages/maistro-core/src/maistro/privilege.py",
        )
        assert matches(globs, "packages/maistro-core/src/maistro/privilege.py")
        assert not matches(
            globs,
            "packages/hive-conductor/tests/e2e/agents-rsi-keyboard.spec.ts",
        )
        # Every shipped glob stays expressible in the modeled subset, so a
        # future entry outside it fails here instead of dodging the pin.
        for glob in globs:
            try:
                matches([glob], "x")
            except ValueError as exc:  # pragma: no cover - failure path
                raise AssertionError(f"unmodelable shipped glob: {glob}") from exc

    def test_every_filtered_check_is_a_collected_pr_check(self, gate) -> None:
        collected = {name for _workflow, name, _scope in gate.collect()}
        assert set(gate.paths_filters()) <= collected

    def test_a_workflow_without_paths_is_absent_from_the_map(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        workflow = tmp_path / "w.yml"
        workflow.write_text(
            yaml.safe_dump(
                {"name": "W", "on": {"pull_request": None}, "jobs": {"j": {"name": "J"}}}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "_workflow_files", lambda: [workflow])
        assert gate.paths_filters() == {}

    def test_a_malformed_paths_filter_fails_closed(self, gate, tmp_path, monkeypatch) -> None:
        # `paths: null` is YAML for "no filter" and must not fail -- only a
        # present-but-unusable filter is a contract error.
        for bad in ("docs/**", ["docs/**", 3], [], [""]):
            workflow = tmp_path / "w.yml"
            workflow.write_text(
                yaml.safe_dump(
                    {
                        "name": "W",
                        "on": {"pull_request": {"paths": bad}},
                        "jobs": {"j": {"name": "J"}},
                    }
                ),
                encoding="utf-8",
            )
            monkeypatch.setattr(gate, "_workflow_files", lambda workflow=workflow: [workflow])
            with pytest.raises(gate.ContractError):
                gate.paths_filters()

    def test_two_workflows_disagreeing_on_one_name_fail_closed(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        first = tmp_path / "a.yml"
        second = tmp_path / "b.yml"
        first.write_text(
            yaml.safe_dump(
                {
                    "name": "A",
                    "on": {"pull_request": {"paths": ["docs/**"]}},
                    "jobs": {"j": {"name": "J"}},
                }
            ),
            encoding="utf-8",
        )
        second.write_text(
            yaml.safe_dump(
                {
                    "name": "B",
                    "on": {"pull_request": {"paths": ["src/**"]}},
                    "jobs": {"j": {"name": "J"}},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "_workflow_files", lambda: [first, second])
        with pytest.raises(gate.ContractError):
            gate.paths_filters()

    def test_a_matrix_job_maps_every_concrete_name(self, gate, tmp_path, monkeypatch) -> None:
        workflow = tmp_path / "w.yml"
        workflow.write_text(
            yaml.safe_dump(
                {
                    "name": "W",
                    "on": {"pull_request": {"paths": ["docs/**"]}},
                    "jobs": {
                        "j": {
                            "name": "J ${{ matrix.os }}",
                            "strategy": {"matrix": {"os": ["ubuntu", "macos"]}},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "_workflow_files", lambda: [workflow])
        assert gate.paths_filters() == {
            "J ubuntu": ["docs/**"],
            "J macos": ["docs/**"],
        }
