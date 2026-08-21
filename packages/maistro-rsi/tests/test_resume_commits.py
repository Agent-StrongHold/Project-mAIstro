"""Regression test for the resume-commit bug: ``_load_saved_patches()`` must
COMMIT the reapplied patches onto ``baseline_branch``, not just modify the
working tree — otherwise every subsequent cycle's variant worktree (created
via ``git worktree add <dir> baseline_branch``) checks out the stale
pre-resume commit, and the resumed code is invisible to the whole run even
though the files sit dirty in the main baseline checkout. This exact bug
silently discarded 32 patches' worth of promoted work across a real restart,
and simultaneously made the rolling export shrink back down to only the
current launch's own promotions (export_promotions ranges from
``_start_ref``, which only advances once the resume is actually committed).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from maistro_rsi.local_loop import LocalRsiConfig, LocalRsiLoop, _git


def _git_run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git_run(path, "init", "-q")
    _git_run(path, "config", "user.email", "rsi@test.local")
    _git_run(path, "config", "user.name", "RSI Test")
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    _git_run(path, "add", "-A")
    _git_run(path, "commit", "-q", "-m", "init")
    return path


_ADD_FILE_PATCH = (
    "diff --git a/new_file.txt b/new_file.txt\n"
    "new file mode 100644\n"
    "index 0000000..b4de394\n"
    "--- /dev/null\n"
    "+++ b/new_file.txt\n"
    "@@ -0,0 +1 @@\n"
    "+resumed content\n"
)


def test_resumed_patch_is_visible_in_a_new_variant_worktree(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "0001-resume.patch").write_text(_ADD_FILE_PATCH, encoding="utf-8")

    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=1,
        export_patches=str(export_dir),
    )
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    loop._load_saved_patches()

    # The critical assertion: baseline_branch must have ADVANCED past
    # start_ref — the resume landed as a commit, not just a dirty working tree.
    count = _git(
        loop._baseline,
        "rev-list",
        "--count",
        f"{loop._start_ref}..{config.baseline_branch}",
    ).stdout.strip()
    assert int(count) == 1, "resume must land as a commit on baseline_branch"

    # The real-world failure mode: a NEW worktree checked out from
    # baseline_branch (exactly what every cycle's _run_variant does) must see
    # the resumed file — not just the main baseline checkout's working tree.
    variant_dir = tmp_path / "variant"
    _git(
        loop._baseline,
        "worktree",
        "add",
        "-q",
        "-b",
        "probe",
        str(variant_dir),
        config.baseline_branch,
    )
    assert (variant_dir / "new_file.txt").is_file()
    assert (variant_dir / "new_file.txt").read_text(encoding="utf-8") == "resumed content\n"


# A patch whose FIRST file applies cleanly (new_file.txt) but whose SECOND file
# is stale (value.txt hunk context "999" never matches the real "0"). Under
# `git apply --reject` the first file would be written and a value.txt.rej left
# behind before a non-zero return; plain (atomic) apply writes nothing.
_PARTIALLY_STALE_PATCH = (
    "diff --git a/new_file.txt b/new_file.txt\n"
    "new file mode 100644\n"
    "index 0000000..b4de394\n"
    "--- /dev/null\n"
    "+++ b/new_file.txt\n"
    "@@ -0,0 +1 @@\n"
    "+resumed content\n"
    "diff --git a/value.txt b/value.txt\n"
    "index 0000000..1111111 100644\n"
    "--- a/value.txt\n"
    "+++ b/value.txt\n"
    "@@ -1 +1 @@\n"
    "-999\n"
    "+changed\n"
)


def test_stale_patch_does_not_partially_poison_baseline(tmp_path: Path) -> None:
    # Codex P1 (#239): --reject would leave the clean hunk + a .rej file in the
    # tree, which the resume commit then swept into the baseline. Atomic apply
    # must write NOTHING and leave no .rej when a patch doesn't fully apply.
    repo = _make_repo(tmp_path / "src")
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "0001-stale.patch").write_text(_PARTIALLY_STALE_PATCH, encoding="utf-8")

    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=1,
        export_patches=str(export_dir),
    )
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    start = loop._start_ref
    loop._load_saved_patches()

    # No hunk was applied: the clean-but-orphaned new_file.txt must NOT exist,
    # no .rej litter, and baseline_branch must not have advanced.
    assert not (loop._baseline / "new_file.txt").exists()
    assert not list(loop._baseline.rglob("*.rej"))
    assert _git(loop._baseline, "rev-parse", config.baseline_branch).stdout.strip() == start


def test_load_saved_patches_is_noop_when_export_dir_missing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "src")
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=1,
        export_patches=str(tmp_path / "export"),  # does not exist yet
    )
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    start = loop._start_ref
    loop._load_saved_patches()
    assert _git(loop._baseline, "rev-parse", "HEAD").stdout.strip() == start


def test_already_applied_patches_produce_no_spurious_commit(tmp_path: Path) -> None:
    # Second resume in the same baseline (e.g. a checkpoint mid-run re-reading
    # its own export dir) must not create an empty/duplicate commit when every
    # patch is already applied — git apply fails gracefully and `applied`
    # stays 0, so the commit guard must skip cleanly.
    repo = _make_repo(tmp_path / "src")
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "0001-resume.patch").write_text(_ADD_FILE_PATCH, encoding="utf-8")

    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=1,
        export_patches=str(export_dir),
    )
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    loop._load_saved_patches()
    after_first = _git(loop._baseline, "rev-parse", "HEAD").stdout.strip()

    loop._load_saved_patches()  # re-run: patch already applied, must be a no-op
    after_second = _git(loop._baseline, "rev-parse", "HEAD").stdout.strip()
    assert after_first == after_second
