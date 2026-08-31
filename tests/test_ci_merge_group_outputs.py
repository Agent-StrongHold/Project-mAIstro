from __future__ import annotations

import subprocess

from scripts import ci_merge_group_scope as helper


def test_pull_request_keeps_every_specialized_leg_enabled() -> None:
    assert all(helper.scope_for_event("pull_request", ["docs/README.md"]).values())


def test_merge_group_uses_changed_paths() -> None:
    scope = helper.scope_for_event("merge_group", ["docs/ci/BRANCH-PROTECTION.md"])
    assert scope["docker_build"] is True
    assert scope["postgres"] is False
    assert scope["object_storage"] is False
    assert scope["hive_e2e"] is False


def test_missing_merge_group_diff_fails_closed() -> None:
    assert all(helper.scope_for_event("merge_group", None).values())


def test_render_outputs_contains_each_leg_and_scope_json() -> None:
    scope = helper.scope_for_event("merge_group", ["docs/ci/BRANCH-PROTECTION.md"])
    rendered = helper.render_outputs(scope)
    for leg in helper.LEGS:
        assert f"{leg}=" in rendered
    assert "scope_json=" in rendered


def test_git_diff_disables_rename_detection_to_keep_source_paths(monkeypatch) -> None:
    seen: list[str] = []

    def fake_run(argv, **kwargs):
        seen.extend(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="old/path.py\nnew/path.py\n", stderr="")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper.changed_paths_from_git("a" * 40) == ["old/path.py", "new/path.py"]
    assert "--no-renames" in seen
