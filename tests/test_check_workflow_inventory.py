"""Tests for the workflow inventory gate (#400).

stream1-diagnostic.yml sat pinned to a branch deleted after #373 landed, with
a baseline SHA the repository no longer contained and every step ending in
`|| true` -- unable to run, unable to fail, and reading as an active pattern.
Nothing rejected any of the three conditions. These tests pin the gate that
now does: the inventory closes the set in both directions, dispositions fit
their triggers, trigger branches and pinned commits must be alive, and every
error swallow carries a written reason.
"""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-workflow-inventory.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_workflow_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway git checkout with origin/develop and origin/main."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(
        tmp_path,
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=test",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/develop", head)
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    return tmp_path, head


def _inventory(workflows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "_comment": "test inventory",
        "workflows": workflows,
        "retained_branches": [],
    }


def _active(rel: str, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": "demo",
        "file": rel,
        "disposition": "ACTIVE",
        "triggers": ["push"],
        "rationale": "test workflow",
    }
    entry.update(overrides)
    return entry


def _write(
    root: Path,
    inventory: dict[str, object],
    workflows: dict[str, str],
) -> Path:
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "quality").mkdir(exist_ok=True)
    (root / "quality" / "workflow-inventory.json").write_text(
        json.dumps(inventory), encoding="utf-8"
    )
    for name, text in workflows.items():
        (root / ".github" / "workflows" / name).write_text(text, encoding="utf-8")
    return root


BRANCH_WORKFLOW = """\
name: demo
on:
  push:
    branches: [develop]
jobs:
  job:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""


# --------------------------------------------------------------------------
# the inventory closes the set
# --------------------------------------------------------------------------


class TestTheInventoryClosesTheSet:
    def test_a_workflow_with_no_entry_fails(self, gate, repo):
        root, _ = repo
        _write(root, _inventory([]), {"demo.yml": BRANCH_WORKFLOW})
        failures = gate.check(root)
        assert any("demo.yml: no entry" in f for f in failures)

    def test_an_entry_naming_no_file_fails(self, gate, repo):
        root, _ = repo
        _write(root, _inventory([_active(".github/workflows/ghost.yml")]), {})
        failures = gate.check(root)
        assert any("ghost.yml does not exist" in f for f in failures)

    def test_a_retired_file_on_disk_is_a_resurrection(self, gate, repo):
        root, _ = repo
        retired = _active(
            ".github/workflows/old.yml",
            disposition="RETIRED",
            replaced_by=["ci.yml"],
            removal_owner="@someone",
            removal_issue=400,
        )
        _write(root, _inventory([retired]), {"old.yml": "name: old\non: push\njobs: {}\n"})
        failures = gate.check(root)
        assert any("RETIRED but" in f and "exists on disk" in f for f in failures)

    def test_retired_needs_successor_owner_and_issue(self, gate, repo):
        root, _ = repo
        retired = _active(".github/workflows/old.yml", disposition="RETIRED")
        _write(root, _inventory([retired]), {})
        failures = gate.check(root)
        assert any("RETIRED needs `removal_owner`" in f for f in failures)
        assert any("RETIRED needs `replaced_by`" in f for f in failures)
        assert any("positive integer `removal_issue`" in f for f in failures)


# --------------------------------------------------------------------------
# dispositions fit their triggers
# --------------------------------------------------------------------------


class TestDispositions:
    def test_manual_diagnostic_with_event_trigger_is_rejected(self, gate, repo):
        root, _ = repo
        manual = _active(
            ".github/workflows/demo.yml",
            disposition="MANUAL_DIAGNOSTIC",
            triggers=["push", "workflow_dispatch"],
        )
        _write(root, _inventory([manual]), {"demo.yml": BRANCH_WORKFLOW})
        failures = gate.check(root)
        assert any("MANUAL_DIAGNOSTIC must be workflow_dispatch-only" in f for f in failures)

    def test_active_dispatch_only_is_rejected(self, gate, repo):
        root, _ = repo
        active = _active(".github/workflows/demo.yml", triggers=["workflow_dispatch"])
        _write(
            root, _inventory([active]), {"demo.yml": "name: d\non: workflow_dispatch\njobs: {}\n"}
        )
        failures = gate.check(root)
        assert any("ACTIVE but the file declares no trigger" in f for f in failures)

    def test_declared_triggers_must_match_the_file(self, gate, repo):
        root, _ = repo
        entry = _active(".github/workflows/demo.yml", triggers=["schedule"])
        _write(root, _inventory([entry]), {"demo.yml": BRANCH_WORKFLOW})
        failures = gate.check(root)
        assert any("do not match the file's actual" in f for f in failures)

    def test_matching_triggers_pass(self, gate, repo):
        root, _ = repo
        _write(
            root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": BRANCH_WORKFLOW}
        )
        assert gate.check(root) == []


# --------------------------------------------------------------------------
# dead references
# --------------------------------------------------------------------------


class TestDeadBranches:
    def test_a_dead_trigger_branch_fails(self, gate, repo):
        root, _ = repo
        workflow = BRANCH_WORKFLOW.replace("branches: [develop]", "branches: [feat/gone-373]")
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        failures = gate.check(root)
        assert any("trigger branch `feat/gone-373` does not exist" in f for f in failures)

    def test_a_live_trigger_branch_passes(self, gate, repo):
        root, _ = repo
        _write(
            root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": BRANCH_WORKFLOW}
        )
        assert gate.check(root) == []

    def test_a_glob_branch_cannot_rot(self, gate, repo):
        root, _ = repo
        workflow = BRANCH_WORKFLOW.replace("branches: [develop]", "branches: [feat/*]")
        entry = _active(".github/workflows/demo.yml")
        _write(root, _inventory([entry]), {"demo.yml": workflow})
        assert gate.check(root) == []

    def test_a_retained_branch_needs_owner_and_reason(self, gate, repo):
        root, _ = repo
        workflow = BRANCH_WORKFLOW.replace("branches: [develop]", "branches: [integration]")
        inventory = _inventory([_active(".github/workflows/demo.yml")])
        inventory["retained_branches"] = [{"branch": "integration"}]
        _write(root, inventory, {"demo.yml": workflow})
        failures = gate.check(root)
        assert any("needs `owner`" in f for f in failures)
        assert any("needs `reason`" in f for f in failures)

    def test_a_reviewed_retained_branch_passes(self, gate, repo):
        root, _ = repo
        workflow = BRANCH_WORKFLOW.replace("branches: [develop]", "branches: [integration]")
        inventory = _inventory([_active(".github/workflows/demo.yml")])
        inventory["retained_branches"] = [
            {"branch": "integration", "owner": "@someone", "reason": "retired; reviewed"}
        ]
        _write(root, inventory, {"demo.yml": workflow})
        assert gate.check(root) == []


class TestDeadShas:
    def _workflow_with(self, body: str) -> str:
        return (
            "name: demo\non: push\njobs:\n  job:\n    runs-on: ubuntu-latest\n    steps:\n" + body
        )

    def test_a_dead_pinned_sha_fails(self, gate, repo):
        root, _ = repo
        dead = "a" * 40
        workflow = self._workflow_with(f"      - run: git worktree add /tmp/b {dead}\n")
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        failures = gate.check(root)
        assert any(f"commit {dead} does not exist" in f for f in failures)

    def test_a_live_pinned_sha_passes(self, gate, repo):
        root, head = repo
        workflow = self._workflow_with(f"      - run: git checkout -q {head}\n")
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []

    def test_an_external_action_pin_is_not_checked(self, gate, repo):
        root, _ = repo
        external = "b" * 40
        workflow = self._workflow_with(f"      - uses: owner/action@{external}\n")
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []

    def test_the_null_sha_sentinel_is_exempt(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with(
            '      - run: \'[ "$SHA" != "0000000000000000000000000000000000000000" ]\'\n'
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []

    def test_a_sha256_checksum_is_not_matched(self, gate, repo):
        root, _ = repo
        checksum = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
        assert len(checksum) == 64
        workflow = self._workflow_with(
            f"      - run: echo '{checksum}  tool.tgz' | sha256sum --check\n"
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []


# --------------------------------------------------------------------------
# swallowing needs a written reason
# --------------------------------------------------------------------------


class TestSwallowing:
    def _workflow_with(self, steps: str) -> str:
        return (
            "name: demo\non: push\njobs:\n  job:\n    runs-on: ubuntu-latest\n    steps:\n" + steps
        )

    def test_a_bare_or_true_fails(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with("      - run: could-fail || true\n")
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        failures = gate.check(root)
        assert any("error swallow with no written reason" in f for f in failures)

    def test_a_same_line_reason_passes(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with("      - run: could-fail || true # tolerated on purpose\n")
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []

    def test_a_reason_within_the_window_passes(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with(
            "      - run: |\n"
            "          # why: the verdict comes from the step above\n"
            "          could-fail || true\n"
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []

    def test_a_reason_seven_lines_above_does_not_reach(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with(
            "      - run: |\n"
            "          # why: the verdict comes from the step above\n"
            "          a\n"
            "          b\n"
            "          c\n"
            "          d\n"
            "          e\n"
            "          f\n"
            "          g\n"
            "          could-fail || true\n"
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        failures = gate.check(root)
        assert any("error swallow with no written reason" in f for f in failures)

    def test_prose_about_swallowing_is_not_a_swallow(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with(
            "      - run: |\n"
            "          # `|| true` tolerates a *failed* apt, not a wedged one\n"
            "          ok-command\n"
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []

    def test_or_colon_and_or_exit_zero_are_caught(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with(
            "      - run: |\n          could-fail || :\n          other-fail || exit 0\n"
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        failures = gate.check(root)
        assert len([f for f in failures if "no written reason" in f]) == 2

    def test_continue_on_error_needs_a_reason(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with(
            "      - uses: owner/action@v1\n"
            "        continue-on-error: true\n"
            "      - run: echo done\n"
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        failures = gate.check(root)
        assert any("no written reason" in f for f in failures)

    def test_continue_on_error_with_reason_passes(self, gate, repo):
        root, _ = repo
        workflow = self._workflow_with(
            "      - uses: owner/action@v1\n"
            "        continue-on-error: true # best-effort scope evidence\n"
            "      - run: echo done\n"
        )
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": workflow})
        assert gate.check(root) == []


# --------------------------------------------------------------------------
# fail-closed plumbing and the real tree
# --------------------------------------------------------------------------


class TestTheRepository:
    def test_without_git_the_gate_fails_closed(self, gate, tmp_path_factory):
        # A sibling of tmp_path, so git's upward repository discovery cannot
        # find the test runner's own repos through a parent directory.
        bare = tmp_path_factory.mktemp("no-git-root")
        _write(
            bare, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": BRANCH_WORKFLOW}
        )
        failures = gate.check(bare)
        assert any("no git repository" in f for f in failures)

    def test_the_current_tree_is_clean(self, gate):
        assert gate.check(ROOT) == []

    def test_main_exits_zero_on_the_real_tree(self, gate, capsys):
        assert gate.main([]) == 0
        assert "clean" in capsys.readouterr().out

    def test_main_fails_and_explains(self, gate, repo, capsys, monkeypatch):
        root, _ = repo
        monkeypatch.setattr(gate, "ROOT", root)
        _write(root, _inventory([]), {"demo.yml": BRANCH_WORKFLOW})
        assert gate.main([]) == 1
        out = capsys.readouterr().out
        assert "finding(s)" in out and "demo.yml" in out


# --------------------------------------------------------------------------
# the error paths are pinned, not just the happy path
# --------------------------------------------------------------------------


class TestParseErrorPaths:
    """A workflow or inventory the gate cannot read is a finding, not a skip.

    stream1-diagnostic.yml could not fail partly because nothing checked the
    shapes a parser can meet and refuse; these cases walk each refusal.
    """

    def test_workflows_dir_missing_means_no_orphans(self, gate, tmp_path):
        assert gate.workflows_on_disk(tmp_path) == set()

    def test_invalid_yaml_is_a_failure_not_a_crash(self, gate, repo):
        root, _ = repo
        _write(root, _inventory([_active(".github/workflows/demo.yml")]), {"demo.yml": "a: [b\n"})
        failures = gate.check(root)
        assert any("not valid YAML" in f for f in failures)

    def test_load_workflow_raises_on_invalid_yaml(self, gate, tmp_path):
        path = tmp_path / "w.yml"
        path.write_text("a: [b\n", encoding="utf-8")
        with pytest.raises(gate.WorkflowError, match="not valid YAML"):
            gate.load_workflow(path)

    def test_load_workflow_raises_on_a_non_mapping_document(self, gate, tmp_path):
        path = tmp_path / "w.yml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(gate.WorkflowError, match="not a YAML mapping"):
            gate.load_workflow(path)

    def test_trigger_keys_of_a_workflow_without_on_is_empty(self, gate):
        assert gate.trigger_keys({"name": "d", "jobs": {}}) == []

    def test_trigger_keys_reads_the_list_form(self, gate):
        doc = gate.yaml.safe_load("on: [pull_request, push]\njobs: {}\n")
        assert gate.trigger_keys(doc) == ["pull_request", "push"]

    def test_trigger_keys_refuses_an_unreadable_on(self, gate):
        doc = gate.yaml.safe_load("on: 5\njobs: {}\n")
        with pytest.raises(gate.WorkflowError, match="cannot be read"):
            gate.trigger_keys(doc)

    def test_a_swallow_on_the_first_line_has_no_window_to_reach(self, gate):
        # index 0: the reason scan steps above the file's top and must stop,
        # not wrap around or crash (the `break` on the window floor).
        assert gate.swallow_findings(["could-fail || true"], "w.yml") != []

    def test_a_missing_inventory_is_reported_by_check(self, gate, repo):
        root, _ = repo
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "demo.yml").write_text(BRANCH_WORKFLOW)
        assert gate.check(root) == ["quality/workflow-inventory.json is missing"]

    def test_load_inventory_raises_on_a_missing_file(self, gate, tmp_path):
        with pytest.raises(gate.WorkflowError, match="is missing"):
            gate.load_inventory(tmp_path)

    def test_load_inventory_raises_on_invalid_json(self, gate, tmp_path):
        (tmp_path / "quality").mkdir()
        (tmp_path / "quality" / "workflow-inventory.json").write_text("{oops", encoding="utf-8")
        with pytest.raises(gate.WorkflowError, match="not valid JSON"):
            gate.load_inventory(tmp_path)

    def test_load_inventory_raises_on_a_json_array(self, gate, tmp_path):
        (tmp_path / "quality").mkdir()
        (tmp_path / "quality" / "workflow-inventory.json").write_text("[]", encoding="utf-8")
        with pytest.raises(gate.WorkflowError, match="not a JSON object"):
            gate.load_inventory(tmp_path)

    def test_an_empty_comment_is_a_finding(self, gate, repo):
        root, _ = repo
        inventory = _inventory([_active(".github/workflows/demo.yml")])
        inventory["_comment"] = "   "
        _write(root, inventory, {"demo.yml": BRANCH_WORKFLOW})
        assert any("`_comment` is empty" in f for f in gate.check(root))


class TestEntryShapeRejections:
    """Malformed inventory entries fail with the reason, and are never reads."""

    def test_an_entry_that_is_not_an_object(self, gate, repo):
        root, _ = repo
        _write(root, _inventory(["not-a-mapping"]), {})
        failures = gate.check(root)
        assert any("every entry must be an object" in f for f in failures)

    def test_an_unknown_disposition(self, gate, repo):
        root, _ = repo
        entry = _active(".github/workflows/demo.yml", disposition="ARCHIVED")
        _write(root, _inventory([entry]), {"demo.yml": BRANCH_WORKFLOW})
        failures = gate.check(root)
        assert any("disposition 'ARCHIVED' is not one of" in f for f in failures)

    def test_an_empty_rationale(self, gate, repo):
        root, _ = repo
        entry = _active(".github/workflows/demo.yml", rationale="")
        _write(root, _inventory([entry]), {"demo.yml": BRANCH_WORKFLOW})
        failures = gate.check(root)
        assert any("`rationale` is empty" in f for f in failures)

    def test_a_file_outside_the_workflows_directory(self, gate, repo):
        root, _ = repo
        entry = _active("workflows/demo.yml")
        _write(root, _inventory([entry]), {})
        failures = gate.check(root)
        assert any("is not under .github/workflows/" in f for f in failures)

    def test_triggers_that_are_not_a_list_of_names(self, gate, repo):
        root, _ = repo
        entry = _active(".github/workflows/demo.yml", triggers="push")
        _write(root, _inventory([entry]), {"demo.yml": BRANCH_WORKFLOW})
        failures = gate.check(root)
        assert any("`triggers` must be a list of event names" in f for f in failures)

    def test_a_workflows_value_that_is_not_a_list(self, gate, repo):
        root, _ = repo
        inventory = _inventory([])
        inventory["workflows"] = "everything"
        _write(root, inventory, {})
        failures = gate.check(root)
        assert any("`workflows` must be a list" in f for f in failures)

    def test_one_file_claimed_by_two_entries(self, gate, repo):
        root, _ = repo
        first = _active(".github/workflows/demo.yml")
        first["id"] = "first"
        second = _active(".github/workflows/demo.yml")
        second["id"] = "second"
        _write(root, _inventory([first, second]), {"demo.yml": BRANCH_WORKFLOW})
        failures = gate.check(root)
        assert any("already dispositioned by first" in f for f in failures)


class TestTheConsoleEntry:
    def test_main_reports_an_unreadable_inventory_as_a_finding(
        self, gate, repo, capsys, monkeypatch
    ):
        root, _ = repo
        (root / "quality").mkdir()
        (root / "quality" / "workflow-inventory.json").write_text("{oops", encoding="utf-8")
        monkeypatch.setattr(gate, "ROOT", root)
        assert gate.main([]) == 1
        out = capsys.readouterr().out
        assert "finding(s)" in out and "not valid JSON" in out

    def test_main_reports_a_raising_check_on_stderr(self, gate, capsys, monkeypatch):
        """check() returns findings for every refusal it knows how to produce;
        the one escape hatch left is an environment error it cannot name, and
        main's contract for that is FAIL on stderr with exit 1 -- never a
        traceback past the console entry, never a 0."""
        monkeypatch.setattr(gate, "ROOT", Path("/nonexistent-root"))

        def raising_check(_root):
            raise gate.WorkflowError("environment refused to answer")

        monkeypatch.setattr(gate, "check", raising_check)
        assert gate.main([]) == 1
        assert "FAIL: environment refused to answer" in capsys.readouterr().err

    def test_the_main_guard_exits_zero_in_process(self, gate, monkeypatch):
        """The guard line itself, executed: `run_name="__main__"` runs the file
        the way the interpreter does, and `sys.exit(main())` is the exit path.
        The real tree is clean, so the guard carries a 0."""
        monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(SCRIPT), run_name="__main__")
        assert excinfo.value.code == 0
