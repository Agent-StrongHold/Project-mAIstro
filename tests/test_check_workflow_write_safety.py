"""Tests for the workflow write-safety gate (#262).

The script guards against writes a workflow makes that the gate set cannot see
afterwards. Its findings are all currently zero — `m0-merge-candidate.yml` was
removed before this was written — so the only thing keeping the rules honest is
these tests. A guard with nothing to catch and no tests is a guard nobody knows
is broken.

The cases that matter are the two failure directions. A rule that stops firing
lets the pattern back in silently; a waiver that works without a reason turns
the escape hatch into a bypass.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-workflow-write-safety.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_workflow_write_safety", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workflow(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "wf.yml"
    path.write_text(body, encoding="utf-8")
    return path


class TestTheThreeWrites:
    """Each rule fires on the shape actually found in `m0-merge-candidate.yml`."""

    def test_a_push_is_caught(self, check, tmp_path):
        """AC-1. The push whose heads no workflow can ever run on."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n      - run: git push origin HEAD:chatgpt/m0-closeout\n",
        )
        keys = [f.rule.key for f in check.scan(wf)]
        assert keys == ["git-push"]

    def test_a_blanket_merge_strategy_is_caught(self, check, tmp_path):
        """AC-3. Verbatim from the workflow that discarded the branch's side."""
        wf = _workflow(
            tmp_path,
            'jobs:\n  x:\n    steps:\n      - run: git merge --no-commit --no-ff -X ours "$old_head"\n',
        )
        keys = [f.rule.key for f in check.scan(wf)]
        assert keys == ["blanket-merge-strategy"]

    def test_theirs_is_caught_too(self, check, tmp_path):
        """The mirror image is the same defect pointed the other way."""
        wf = _workflow(tmp_path, "jobs:\n  x:\n    steps:\n      - run: git merge -X theirs main\n")
        assert [f.rule.key for f in check.scan(wf)] == ["blanket-merge-strategy"]

    def test_an_automated_bank_is_caught(self, check, tmp_path):
        """AC-4. `--bank` accepts a fall in the repository's only floor."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n"
            "      - run: python scripts/check-ac-state.py --run-tests --ratchet --bank\n",
        )
        assert [f.rule.key for f in check.scan(wf)] == ["automated-bank"]

    def test_all_three_in_one_file_are_all_reported(self, check, tmp_path):
        """They were found together, and a gate that stopped at the first would
        have sent someone back for a second round."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n"
            "      - run: git merge --no-ff -X ours old\n"
            "      - run: python scripts/check-ac-state.py --ratchet --bank\n"
            "      - run: git push origin HEAD:branch\n",
        )
        assert sorted(f.rule.key for f in check.scan(wf)) == [
            "automated-bank",
            "blanket-merge-strategy",
            "git-push",
        ]


class TestWhatIsAllowed:
    def test_a_dry_run_push_is_not_a_write(self, check, tmp_path):
        """It reports what would happen and changes nothing, which is the
        opposite of the invisible-write problem."""
        wf = _workflow(
            tmp_path, "jobs:\n  x:\n    steps:\n      - run: git push --dry-run origin x\n"
        )
        assert check.scan(wf) == []

    def test_a_named_path_resolution_is_allowed(self, check, tmp_path):
        """`git checkout --ours -- <path>` says which path, in the diff. That is
        the reviewable form the blanket option destroys."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n      - run: git checkout --ours -- quality/ac-state.json\n",
        )
        assert check.scan(wf) == []

    def test_banking_without_the_flag_is_allowed(self, check, tmp_path):
        """Reading the ratchet is not banking it."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n      - run: python scripts/check-ac-state.py --ratchet\n",
        )
        assert check.scan(wf) == []


class TestTheEscapeHatch:
    """A rule with no exception gets deleted the first time someone needs it —
    but an exception that costs nothing to claim is not an exception, it is an
    off switch."""

    def test_a_waiver_on_the_same_line_suppresses(self, check, tmp_path):
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n"
            "      - run: git push origin main  # workflow-write-safety: allow pushes with a PAT\n",
        )
        assert check.scan(wf) == []

    def test_a_waiver_on_the_line_above_suppresses(self, check, tmp_path):
        """YAML line length pushes comments up as often as it leaves room at the
        end; a rule accepting only one placement is one people reformat around."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n"
            "      # workflow-write-safety: allow pushes with a PAT, see #262\n"
            "      - run: git push origin main\n",
        )
        assert check.scan(wf) == []

    def test_a_waiver_without_a_reason_does_not_suppress(self, check, tmp_path):
        """The reason is the whole mechanism. A bare marker would let the silent
        behaviour back in under a token that reads as review but records nothing."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n"
            "      - run: git push origin main  # workflow-write-safety: allow\n",
        )
        assert [f.rule.key for f in check.scan(wf)] == ["git-push"]

    def test_a_waiver_two_lines_above_does_not_reach(self, check, tmp_path):
        """Otherwise one waiver drifts over unrelated steps as a file grows."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n"
            "      # workflow-write-safety: allow something else entirely\n"
            "      - run: echo unrelated\n"
            "      - run: git push origin main\n",
        )
        assert [f.rule.key for f in check.scan(wf)] == ["git-push"]

    def test_the_waiver_comment_is_not_itself_a_finding(self, check, tmp_path):
        """The marker's own text contains the words it waives; a scanner that
        read comments would flag its own escape hatch."""
        wf = _workflow(
            tmp_path,
            "jobs:\n  x:\n    steps:\n"
            "      # note: never use -X ours here, and never git push\n"
            "      - run: echo fine\n",
        )
        assert check.scan(wf) == []


class TestTheRepository:
    def test_the_current_tree_is_clean(self, check):
        """The state this gate was written to preserve. If this ever fails, a
        workflow started writing where the gate set cannot follow."""
        findings = [f for path in check.workflow_files() for f in check.scan(path)]
        assert findings == [], "\n".join(f.render() for f in findings)

    def test_the_script_exits_zero_on_the_real_tree(self):
        """End to end, the way `workflow-lint` invokes it."""
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "make no writes the gate set cannot see" in proc.stdout

    def test_a_finding_renders_the_fix_not_just_the_complaint(self, check, tmp_path):
        """A gate that says only "no" gets worked around rather than followed."""
        wf = _workflow(tmp_path, "jobs:\n  x:\n    steps:\n      - run: git push origin main\n")
        (finding,) = check.scan(wf)
        rendered = finding.render()
        assert "why:" in rendered
        assert "instead:" in rendered
        assert "or waive:" in rendered


class TestTheReport:
    def test_main_fails_and_explains_when_a_workflow_writes(
        self, check, tmp_path, monkeypatch, capsys
    ):
        """The output is the gate's actual interface: someone reads it and
        either fixes the workflow or waives the rule."""
        wf = _workflow(tmp_path, "jobs:\n  x:\n    steps:\n      - run: git push origin main\n")
        monkeypatch.setattr(check, "workflow_files", lambda: [wf])
        assert check.main() == 1
        out = capsys.readouterr().out
        assert "did not" not in out.split("\n")[0]
        assert "the gate set cannot see" in out
        assert "instead:" in out

    def test_main_passes_on_a_clean_set(self, check, tmp_path, monkeypatch, capsys):
        wf = _workflow(tmp_path, "jobs:\n  x:\n    steps:\n      - run: echo hello\n")
        monkeypatch.setattr(check, "workflow_files", lambda: [wf])
        assert check.main() == 0
        assert "make no writes" in capsys.readouterr().out

    def test_finding_no_workflows_at_all_is_a_failure(self, check, monkeypatch):
        """An empty scan would otherwise report "ok: 0 workflows", which is the
        same false green as a gate that never ran."""
        monkeypatch.setattr(check, "workflow_files", list)
        assert check.main() == 1
