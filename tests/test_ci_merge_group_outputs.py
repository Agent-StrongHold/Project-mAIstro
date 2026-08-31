from __future__ import annotations

import subprocess

import pytest
from scripts import ci_merge_group_scope as helper


def test_pull_request_keeps_every_specialized_leg_enabled() -> None:
    assert all(helper.scope_for_event("pull_request", ["docs/README.md"]).values())
    assert all(helper.scope_from_environment("pull_request").values())


def test_merge_group_uses_changed_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = helper.scope_for_event("merge_group", ["docs/ci/BRANCH-PROTECTION.md"])
    assert scope["docker_build"] is True
    assert scope["postgres"] is False
    assert scope["object_storage"] is False
    assert scope["hive_e2e"] is False

    monkeypatch.setattr(helper, "resolve_base_revision_from_env", lambda: "a" * 40)
    monkeypatch.setattr(
        helper,
        "changed_paths_from_git",
        lambda _base: ["docs/ci/BRANCH-PROTECTION.md"],
    )
    measured = helper.scope_from_environment("merge_group")
    assert measured == scope


def test_missing_merge_group_diff_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert all(helper.scope_for_event("merge_group", None).values())

    def fail_base() -> str:
        raise helper.BaseRevisionError("missing base")

    monkeypatch.setattr(helper, "resolve_base_revision_from_env", fail_base)
    assert all(helper.scope_from_environment("merge_group").values())
    assert "enabling every specialized leg" in capsys.readouterr().err


def test_render_outputs_contains_each_leg_and_scope_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scope = helper.scope_for_event("merge_group", ["docs/ci/BRANCH-PROTECTION.md"])
    rendered = helper.render_outputs(scope)
    for leg in helper.LEGS:
        assert f"{leg}=" in rendered
    assert "scope_json=" in rendered

    monkeypatch.setattr("sys.argv", ["ci_merge_group_scope.py", "--github-outputs"])
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    assert helper.main() == 0
    captured = capsys.readouterr()
    assert "GITHUB_EVENT_NAME is missing" in captured.err
    output_lines = captured.out.splitlines()
    assert output_lines[:-1] == [f"{leg}=true" for leg in helper.LEGS]
    assert output_lines[-1].startswith("scope_json=")

    monkeypatch.setattr("sys.argv", ["ci_merge_group_scope.py", "--github-outputs", "--json"])
    with pytest.raises(SystemExit):
        helper.main()


def test_git_diff_disables_rename_detection_to_keep_source_paths(monkeypatch) -> None:
    seen: list[str] = []

    def fake_run(argv, **kwargs):
        seen.extend(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="old/path.py\nnew/path.py\n", stderr="")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper.changed_paths_from_git("a" * 40) == ["old/path.py", "new/path.py"]
    assert "--no-renames" in seen
