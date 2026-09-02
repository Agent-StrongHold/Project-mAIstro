from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-autonomous-merge.py"
SPEC = importlib.util.spec_from_file_location("check_autonomous_merge", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def cf(path: str, status: str = "M", old_path: str | None = None):
    return mod.ChangedFile(status=status, path=path, old_path=old_path)


def test_agent_prefix_is_autonomous():
    assert mod.is_autonomous("claude/issue-1", [])


def test_chatgpt_prefix_is_autonomous():
    assert mod.is_autonomous("refs/heads/chatgpt/fix", [])


def test_human_branch_is_not_autonomous():
    assert not mod.is_autonomous("feature/fix", [])


def test_label_can_mark_a_human_named_branch_autonomous():
    assert mod.is_autonomous("feature/fix", ["autonomous-merge"])


def test_force_marks_change_autonomous():
    assert mod.is_autonomous("feature/fix", [], force=True)


def test_name_status_parses_modify_and_delete():
    rows = mod.parse_name_status("M\ta.py\nD\tb.py\n")
    assert [(row.status, row.path) for row in rows] == [("M", "a.py"), ("D", "b.py")]


def test_name_status_parses_rename():
    [row] = mod.parse_name_status("R100\told.py\tnew.py\n")
    assert row.old_path == "old.py" and row.path == "new.py"


def test_bad_name_status_fails_closed():
    with pytest.raises(ValueError):
        mod.parse_name_status("M\n")


def test_trusted_workflow_change_is_red():
    result = mod.assess([cf(".github/workflows/ci.yml")], "", head_ref="claude/x")
    assert result.risk == "red" and not result.eligible


def test_trusted_script_change_is_red():
    result = mod.assess([cf("scripts/check-required-checks.py")], "", head_ref="chatgpt/x")
    assert result.risk == "red" and not result.eligible


def test_cage_change_is_red():
    result = mod.assess(
        [cf("packages/hive-conductor/cage/foo.py")],
        "",
        head_ref="agent/x",
    )
    assert result.risk == "red"


def test_rename_out_of_trusted_surface_stays_red():
    result = mod.assess(
        [cf("docs/old-ci.yml", "R100", ".github/workflows/old.yml")],
        "",
        head_ref="claude/x",
    )
    assert result.risk == "red"


def test_dependency_change_is_yellow_for_agent():
    result = mod.assess([cf("uv.lock")], "", head_ref="claude/x")
    assert result.risk == "yellow" and not result.eligible


def test_execution_change_is_yellow_for_agent():
    result = mod.assess(
        [cf("packages/maistro-core/src/maistro/execution/runtime.py")],
        "",
        head_ref="claude/x",
    )
    assert result.risk == "yellow" and not result.eligible


def test_canonical_container_change_is_yellow_for_agent():
    result = mod.assess(
        [cf("packages/maistro-core/src/maistro/container.py")],
        "",
        head_ref="chatgpt/x",
    )
    assert result.risk == "yellow" and not result.eligible


def test_low_risk_app_change_is_green_and_eligible():
    result = mod.assess(
        [cf("packages/hive-conductor/frontend/src/App.tsx")],
        "",
        head_ref="claude/x",
    )
    assert result.risk == "green" and result.eligible


def test_human_red_change_is_not_blocked_by_autonomy_gate():
    result = mod.assess(
        [cf(".github/workflows/ci.yml")],
        "",
        head_ref="feature/human",
    )
    assert result.risk == "red" and result.eligible


def test_new_skip_is_integrity_finding():
    patch = "+++ b/tests/test_x.py\n+@pytest.mark.skip(reason='later')\n"
    result = mod.assess([cf("tests/test_x.py")], patch, head_ref="claude/x")
    assert result.risk == "yellow" and result.integrity_reasons and not result.eligible


def test_new_noqa_is_integrity_finding():
    patch = "+++ b/a.py\n+x = 1  # noqa: F841\n"
    assert mod.integrity_findings(patch, [cf("a.py")])


def test_removed_test_definition_is_integrity_finding():
    patch = "+++ b/tests/test_x.py\n-def test_thing():\n"
    assert mod.integrity_findings(patch, [cf("tests/test_x.py")])


def test_deleted_test_file_is_integrity_finding():
    findings = mod.integrity_findings("", [cf("tests/test_x.py", "D")])
    assert findings == ["test file deleted: tests/test_x.py"]


@pytest.mark.ac("SPEC-083126-5e62/AC-3")
def test_merge_group_blocks_trusted_surface_regardless_of_identity():
    result = mod.assess([cf(".github/workflows/ci.yml")], "", merge_group=True)
    assert not result.eligible


def test_merge_group_allows_yellow_after_pr_time_policy():
    result = mod.assess([cf("uv.lock")], "", merge_group=True)
    assert result.risk == "yellow" and result.eligible


def test_risk_check_never_vetoes_by_itself():
    result = mod.assess([cf(".github/workflows/ci.yml")], "", head_ref="claude/x")
    assert mod.exit_ok(result, "risk")


def test_trusted_slice_vetoes_autonomous_red():
    result = mod.assess([cf(".github/workflows/ci.yml")], "", head_ref="claude/x")
    assert not mod.exit_ok(result, "trusted")


def test_integrity_slice_vetoes_autonomous_suppression():
    patch = "+++ b/tests/test_x.py\n+# type: ignore\n"
    result = mod.assess([cf("tests/test_x.py")], patch, head_ref="claude/x")
    assert not mod.exit_ok(result, "integrity")


def test_labels_json_accepts_json_and_csv():
    assert mod._labels('["a", "b"]') == ["a", "b"]
    assert mod._labels("a,b") == ["a", "b"]


def test_labels_json_accepts_null_as_no_labels():
    assert mod._labels("null") == []


def test_labels_json_rejects_non_string_items():
    with pytest.raises(ValueError):
        mod._labels('["a", 1]')


def test_render_contains_reason_sections():
    result = mod.assess([cf("uv.lock")], "", head_ref="claude/x")
    text = mod.render(result)
    assert "risk=yellow" in text and "YELLOW:" in text


def test_assess_git_reads_exact_two_dot_diff(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"],
        check=True,
    )
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    base = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "head"], check=True)
    head = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    result = mod.assess_git(tmp_path, base, head, head_ref="claude/x")
    assert result.changed_files == ["a.py"] and result.eligible


def test_main_writes_json_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    expected = mod.Assessment(True, "green", True, False, ["a.py"])
    monkeypatch.setattr(mod, "assess_git", lambda *args, **kwargs: expected)
    out = tmp_path / "report.json"
    rc = mod.main(["--base", "a", "--head", "b", "--json-output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text())["eligible"] is True


def test_main_fails_closed_when_git_cannot_answer(monkeypatch: pytest.MonkeyPatch):
    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "assess_git", fail)
    assert mod.main(["--base", "a", "--head", "b"]) == 2
