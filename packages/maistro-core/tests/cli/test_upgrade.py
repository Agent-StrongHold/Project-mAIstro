"""Tests for `maistro upgrade` (maistro.cli._upgrade).

Every supported install type is exercised with the driver invoked from a
directory that is *not* the install root (the core regression #353: upgrade
must resolve its target from the durable install manifest, never the caller's
CWD). The subprocess boundary is the module-level ``_RUN_SUBPROCESS`` symbol,
substituted with a recorder that returns controlled outcomes — no git/uv/docker
is spawned.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import maistro.cli._upgrade as upgrade_mod
from maistro.cli._upgrade import upgrade_main
from maistro.install_manifest import MANIFEST_FILENAME, PLAN_SUBDIR, InstallManifest


class _Recorder:
    """A deterministic stand-in for ``subprocess.run``.

    Returns success for every command unless its argv head matches a name
    registered in ``failures`` — then it returns a failing outcome carrying a
    marker message. Every call is recorded so tests can assert the exact
    command vocabulary and the ``cwd`` each ran under.
    """

    def __init__(self, fail_all: bool = False) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.failures: dict[str, str] = {}
        self.fail_all = fail_all

    def __call__(
        self, argv, *, cwd=None, env=None, capture_output=True, text=True, timeout=None, check=False
    ) -> SimpleNamespace:
        head = argv[0] if argv else ""
        self.calls.append((list(argv), cwd))
        if self.fail_all or head in self.failures:
            msg = self.failures.get(head, "simulated failure")
            return SimpleNamespace(returncode=1, stdout="", stderr=msg)
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(upgrade_mod, "_RUN_SUBPROCESS", rec)
    # `git_revision` (used for backup/rollback/success reporting) lives in
    # install_manifest and calls subprocess.run directly; stub it so upgrades
    # against fake (non-git) roots report a stable revision.
    monkeypatch.setattr(upgrade_mod, "git_revision", lambda root: "deadbeef")
    return rec


@pytest.fixture
def unrelated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory that is deliberately NOT the install root."""
    somewhere = tmp_path / "elsewhere" / "deep"
    somewhere.mkdir(parents=True)
    monkeypatch.chdir(somewhere)
    return somewhere


def _write_manifest(root: Path, manifest: InstallManifest) -> None:
    plan = root / PLAN_SUBDIR
    plan.mkdir(parents=True, exist_ok=True)
    path = plan / MANIFEST_FILENAME
    path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")


def _manifest(root: Path, install_type: str = "git", **extra) -> InstallManifest:
    kwargs: dict = {
        "install_type": install_type,  # type: ignore[arg-type]
        "install_root": str(root),
        "install_surface": "curl",
    }
    if install_type in ("git", "tag"):
        kwargs["image_tag"] = extra.pop("image_tag", "v1.0.0")
        kwargs["delivery_mode"] = extra.pop("delivery_mode", "source_build")
        kwargs["ref"] = extra.pop("ref", "main" if install_type == "git" else "v1.0.0")
        if install_type == "tag":
            kwargs["version"] = extra.pop("version", "v1.0.0")
    elif install_type == "archive":
        kwargs["image_tag"] = extra.pop("image_tag", "v1.0.0")
        kwargs["delivery_mode"] = extra.pop("delivery_mode", "source_build")
        kwargs["ref"] = extra.pop("ref", "v1.0.0")
        kwargs["version"] = extra.pop("version", "v1.0.0")
        kwargs["source_url"] = extra.pop(
            "source_url", "https://github.com/Agent-StrongHold/Project-mAIstro"
        )
    elif install_type == "container":
        kwargs["image_tag"] = extra.pop("image_tag", "v1.0.0")
        kwargs["delivery_mode"] = extra.pop("delivery_mode", "image_pull")
    return InstallManifest(**kwargs)


def _seed_compose_and_env(root: Path, kinds: str | tuple = ("git", "tag")) -> None:
    if isinstance(kinds, str):
        kinds = (kinds,)
    (root / "docker-compose.yml").write_text(
        "services:\n  maistro-engine:\n    image: maistro-engine\n", encoding="utf-8"
    )
    (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")


def _drive(root: Path, recorder: _Recorder) -> None:
    os.environ["MAISTRO_REPO_ROOT"] = str(root)
    try:
        upgrade_main()
    finally:
        os.environ.pop("MAISTRO_REPO_ROOT", None)


# -- discovery / unsupported --------------------------------------------------


def test_no_install_found_fails_with_actionable_instructions(
    unrelated_cwd: Path, monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    monkeypatch.setattr(upgrade_mod, "locate_install_root", lambda start=None: (None, None))
    monkeypatch.setattr(upgrade_mod, "_detect_packaged_or_container", lambda: (None, None, None))
    with pytest.raises(SystemExit) as exc:
        upgrade_main()
    assert exc.value.code == 1
    assert not recorder.calls, "no external command should run when no install is found"


def test_unsupported_install_type_fails_with_actionable_instructions(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(upgrade_mod, "locate_install_root", lambda start=None: (None, None))
    monkeypatch.setattr(
        upgrade_mod,
        "_detect_packaged_or_container",
        lambda: (
            "something_else",
            tmp_path,
            InstallManifest(install_type="git", install_root=str(tmp_path)),
        ),
    )
    with pytest.raises(SystemExit) as exc:
        upgrade_main()
    assert exc.value.code == 1
    assert not recorder.calls


# -- per-type upgrade paths, all from an unrelated CWD ------------------------


def test_git_upgrade_uses_install_root_not_cwd(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    _write_manifest(root, _manifest(root, install_type="git"))

    _drive(root, recorder)

    assert recorder.calls, "no commands were issued"
    # Every external command runs inside the install root.
    for argv, cwd in recorder.calls:
        assert cwd == str(root), f"command {argv} ran in {cwd}, not the install root"
    flat = [" ".join(a) for a, _ in recorder.calls]
    assert any("fetch" in c for c in flat)
    assert any("pull" in c for c in flat)  # `git pull --ff-only`
    assert any("uv sync" in c for c in flat)
    assert any("up" in c for c in flat)


def test_tag_upgrade_checks_out_latest_release_not_pull(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    _write_manifest(root, _manifest(root, install_type="tag", delivery_mode="source_build"))

    _drive(root, recorder)

    flat = [" ".join(a) for a, _ in recorder.calls]
    # A tagged upgrade fetches tags and checks out the latest resolved tag.
    assert any("fetch" in c and "tags" in c for c in flat)
    assert any("checkout --force" in c for c in flat)
    # It must NOT run an in-place `git pull` (the historical bug over an unknown CWD).
    assert not any(c.startswith("git ") and "pull" in c for c in flat)


def test_archive_upgrade_redownloads_and_preserves_env(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    root = tmp_path / "maistro-engine"
    root.mkdir()
    (root / ".env").write_text("MAISTRO_PORT=8000\nTOKEN=secret\n", encoding="utf-8")
    _write_manifest(root, _manifest(root, install_type="archive", ref="v1.1.0", version="v1.1.0"))

    _drive(root, recorder)

    flat = [" ".join(a) for a, _ in recorder.calls]
    assert any("curl" in c and "v1.1.0.tar.gz" in c for c in flat)
    # The swap carries .env across (secrets preserved) while replacing the tree.
    assert any("cp" in c and ".env" in c for c in flat)
    # No external command is ever aimed at deleting the live tree: the swap is
    # rename-based and `rm -rf` only happens in-process after a full commit.
    assert not any("rm -rf" in c for c in flat)
    # The swapped-in manifest is the version proof (archive trees have no .git).
    assert any("install-manifest.json" in c for c in flat)
    # The recorded .env survives because the swap step is the only .env writer.
    assert (root / ".env").read_text(encoding="utf-8") == "MAISTRO_PORT=8000\nTOKEN=secret\n"


def test_archive_swap_is_rename_based_and_retains_previous_tree(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    """The archive swap must mv the old tree aside, never rm it in place.

    Regression for the concatenated-`rm -rf` bug: the old swap step built
    ``rm -rf <root>/. cp -a <work>/. <root>`` — a missing ``&&`` turned the
    copy into extra arguments of the delete, and GNU rm refuses ``rm -rf
    dir/.`` outright. Either way the install was destroyed with no rollback.
    """
    root = tmp_path / "maistro-engine"
    root.mkdir()
    (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
    _write_manifest(root, _manifest(root, install_type="archive", ref="v1.1.0", version="v1.1.0"))

    _drive(root, recorder)

    argv = [a for a, _ in recorder.calls]
    swap = next(a for a in argv if a[:2] == ["bash", "-c"] and " mv " in a[2])
    old = root.with_name(root.name + ".upgrade-old")
    work = root.with_name(root.name + ".upgrade-tmp")
    # root -> old (retained), work -> root, and a failed rename restores root.
    assert f"mv {shlex.quote(str(root))} {shlex.quote(str(old))}" in swap[2]
    assert f"mv {shlex.quote(str(work))} {shlex.quote(str(root))}" in swap[2]
    assert f"else mv {shlex.quote(str(old))} {shlex.quote(str(root))}; exit 1" in swap[2]
    assert "rm -rf" not in swap[2]


def test_archive_swap_and_rollback_execute_for_real(tmp_path: Path) -> None:
    """Run the swap and rollback with a real shell: the tree ends whole.

    The recorder proves command vocabulary; this proves the composed bash
    actually works — new tree live at the root, previous release retained for
    rollback, plan dir (and its manifest) carried across, and rollback
    restoring the previous release wholesale.
    """
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(upgrade_mod, "_RUN_SUBPROCESS", subprocess.run)
        root = tmp_path / "maistro-engine"
        root.mkdir()
        (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
        (root / "old-release-marker").write_text("old", encoding="utf-8")
        plan = root / PLAN_SUBDIR
        plan.mkdir()
        (plan / MANIFEST_FILENAME).write_text("{}\n", encoding="utf-8")
        work = root.with_name(root.name + ".upgrade-tmp")
        work.mkdir()
        (work / "new-release-marker").write_text("new", encoding="utf-8")
        (work / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")

        manifest = _manifest(root, install_type="archive", ref="v2.0.0", version="v2.0.0")
        driver = upgrade_mod._Upgrade(root, manifest, "archive")
        (swap_cmd,) = driver._archive_swap_cmds()
        cp = subprocess.run(swap_cmd.argv, cwd=swap_cmd.cwd, capture_output=True, text=True)
        assert cp.returncode == 0, cp.stderr

        assert (root / "new-release-marker").is_file()
        assert not (root / "old-release-marker").exists()
        old = root.with_name(root.name + ".upgrade-old")
        assert old.is_dir(), "previous release must be retained until commit"
        assert (old / "old-release-marker").is_file()
        assert (root / PLAN_SUBDIR / MANIFEST_FILENAME).is_file()

        driver._archive_swapped = True
        driver.rollback()
        assert (root / "old-release-marker").is_file(), "rollback restores previous release"
        assert (root / ".env").read_text(encoding="utf-8") == "MAISTRO_PORT=8000\n"
        assert not old.exists(), "retained tree is consumed by the rollback"
    finally:
        mp.undo()


def test_checkout_without_manifest_is_upgraded_from_detected_type(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout with no recorded manifest must not crash with a bare assert.

    The parent walk finds the engine checkout and upgrade detects the install
    type from the tree itself (regression: `assert manifest is not None` turned
    the documented no-manifest fallback into an AssertionError traceback).
    """
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    monkeypatch.delenv("MAISTRO_REPO_ROOT", raising=False)
    # Run from *inside* the checkout, like an operator in a repo subdirectory.
    inner = root / "docs" / "notes"
    inner.mkdir(parents=True)
    monkeypatch.chdir(inner)

    upgrade_main()  # must not raise SystemExit or AssertionError

    assert recorder.calls, "no commands were issued"
    for argv, cwd in recorder.calls:
        assert cwd == str(root), f"command {argv} ran in {cwd}, not the detected install root"
    flat = [" ".join(a) for a, _ in recorder.calls]
    assert any("fetch" in c for c in flat)


def test_image_pull_upgrade_pulls_and_verifies_before_cutover(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    _write_manifest(
        root, _manifest(root, install_type="tag", delivery_mode="image_pull", image_tag="v2.0.0")
    )

    _drive(root, recorder)

    argv = [a for a, _ in recorder.calls]
    pull_idx = next(i for i, a in enumerate(argv) if "compose" in a and a[-1] == "pull")
    inspect_idx = next(
        i for i, a in enumerate(argv) if a[0] in ("docker", "podman") and a[1] == "inspect"
    )
    up_idx = next(i for i, a in enumerate(argv) if a[-1] == "-d" and a[-2] == "up")
    # Images are pulled and verified BEFORE the cutover (compose up).
    assert pull_idx < inspect_idx < up_idx


def test_package_upgrade_runs_uv_tool_upgrade(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    root = tmp_path / "maistro-tool"
    root.mkdir()
    _write_manifest(root, _manifest(root, install_type="package"))

    _drive(root, recorder)

    argv = [a for a, _ in recorder.calls]
    assert any(a[0] == "uv" and "tool" in a and "upgrade" in a for a in argv)
    flat = [" ".join(a) for a, _ in recorder.calls]
    # A package install never touches git source or the compose stack.
    assert not any("git " in c for c in flat)
    assert not any("compose" in c for c in flat)


def test_container_upgrade_pulls_images_and_restarts(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _write_manifest(
        root,
        _manifest(root, install_type="container", image_tag="v1.0.0", delivery_mode="image_pull"),
    )

    _drive(root, recorder)

    flat = [" ".join(a) for a, _ in recorder.calls]
    assert any("compose" in c and " pull" in c for c in flat)
    assert any("up" in c and "-d" in c for c in flat)
    assert any("health/ready" in c for c in flat)


@pytest.mark.parametrize("kind", ["git", "tag", "archive", "package", "container"])
def test_every_supported_type_completes_from_an_unrelated_dir(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder, kind: str
) -> None:
    root = tmp_path / "maistro-engine"
    root.mkdir()
    manifest = _manifest(root, install_type=kind)
    if kind in ("git", "tag"):
        _seed_compose_and_env(root)
    elif kind == "archive":
        (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
    _write_manifest(root, manifest)

    _drive(root, recorder)

    assert recorder.calls, f"no commands issued for install_type={kind}"


# -- transactional guarantees -------------------------------------------------


@pytest.mark.parametrize("kind", ["git", "tag", "archive", "package", "container"])
def test_failure_aborts_without_false_success(
    tmp_path: Path,
    unrelated_cwd: Path,
    recorder: _Recorder,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    """A failing step must NOT print success and must roll back."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    manifest = _manifest(root, install_type=kind)
    if kind in ("git", "tag"):
        _seed_compose_and_env(root)
    elif kind == "archive":
        (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
    _write_manifest(root, manifest)

    recorder.fail_all = True  # every external command fails
    with pytest.raises(SystemExit) as exc_info:
        _drive(root, recorder)
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Upgrade complete" not in out
    assert "Rolling back" in out


def test_preflight_failure_aborts_before_any_external_command(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """An archive install with no source_url cannot be re-fetched; abort cleanly."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    bad = InstallManifest(
        install_type="archive",
        install_root=str(root),
        install_surface="curl",
        image_tag="v1.0.0",
        delivery_mode="source_build",
    )
    _write_manifest(root, bad)

    with pytest.raises(SystemExit) as exc_info:
        _drive(root, recorder)
    assert exc_info.value.code == 1

    assert not recorder.calls, "no external command should run before a clean preflight failure"
    out = capsys.readouterr().out
    assert "No changes were made" in out
    assert "Upgrade complete" not in out


def test_success_prints_version_and_revision(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    _write_manifest(root, _manifest(root, install_type="git"))

    _drive(root, recorder)

    out = capsys.readouterr().out
    assert "Upgrade complete" in out
    assert "source revision deadbeef" in out
