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
from maistro.cli._install_manifest import (
    MANIFEST_FILENAME,
    PLAN_SUBDIR,
    InstallManifest,
    load_manifest,
)
from maistro.cli._upgrade import upgrade_main


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
        # When set, the compose-capability probe (#407) answers with this
        # version string even under fail_all — models a healthy Compose v2
        # next to whatever the failing phase is.
        self.compose_version_stdout: str | None = None

    def __call__(
        self, argv, *, cwd=None, env=None, capture_output=True, text=True, timeout=None, check=False
    ) -> SimpleNamespace:
        head = argv[0] if argv else ""
        self.calls.append((list(argv), cwd))
        if (
            self.compose_version_stdout is not None
            and argv[-1] == "version"
            and argv[:2] in (["docker", "compose"], ["podman", "compose"])
        ):
            return SimpleNamespace(returncode=0, stdout=self.compose_version_stdout, stderr="")
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
    kwargs.update(extra)
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
    # The target must be resolved independent of HEAD (a tagged install is
    # detached at the *previous* release, which `describe --tags` would
    # re-resolve after the fetch, silently upgrading nothing).
    checkout = next(c for c in flat if "checkout --force" in c)
    assert "for-each-ref" in checkout
    assert "describe" not in checkout
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


def test_upgrade_honors_custom_plan_dir_for_compose_artifacts(
    tmp_path: Path, unrelated_cwd: Path
) -> None:
    """Upgrading a ``--plan-dir`` install keeps its manifest and overrides.

    Regression (review): discovery and the compose command builder hardcoded
    ``<root>/.maistro-install``, so a custom plan-dir install's manifest was
    never found (git fell back to guessed defaults, archive was rejected) and
    its generated compose.override.yml was ignored in favor of regeneration.
    """
    root = tmp_path / "maistro-engine"
    root.mkdir()
    plan = root / "plans" / "prod"
    plan.mkdir(parents=True)
    (plan / "compose.override.yml").write_text(
        'services:\n  maistro-engine:\n    ports: ["7000:8000"]\n', encoding="utf-8"
    )
    (root / "docker-compose.yml").write_text(
        "services:\n  maistro-engine:\n    image: maistro-engine\n", encoding="utf-8"
    )
    (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
    _write_manifest(root, _manifest(root, install_type="git", plan_dir="plans/prod"))

    # The installer leaves the manifest at the canonical location; upgrade
    # resolves the artifact directory from the recorded plan_dir.
    loaded = load_manifest(root)
    assert loaded is not None and loaded.plan_dir == "plans/prod"
    driver = upgrade_mod._Upgrade(root, loaded, "git")
    assert driver.plan_dir == plan
    assert any(str(plan / "compose.override.yml") in a for a in driver._compose_args())


def test_archive_swap_carries_custom_plan_dir_and_manifest_round_trips(
    tmp_path: Path,
) -> None:
    """Archive upgrades of custom plan-dir installs survive the tree swap."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    plan = root / "plans" / "prod"
    plan.mkdir(parents=True)
    (plan / MANIFEST_FILENAME).write_text("{}\n", encoding="utf-8")
    manifest = _manifest(
        root, install_type="archive", ref="v2.0.0", version="v2.0.0", plan_dir="plans/prod"
    )
    driver = upgrade_mod._Upgrade(root, manifest, "archive")

    (swap_cmd,) = driver._archive_swap_cmds()
    assert "plans/prod" in swap_cmd.argv[2], "swap must carry the recorded plan dir"

    # The refreshed manifest is written where the version probe reads it —
    # the custom plan dir — and the canonical pointer stays current.
    driver._record_archive_manifest()
    refreshed = json.loads((plan / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert refreshed["version"] == "v2.0.0"
    canonical = json.loads((root / PLAN_SUBDIR / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert canonical["plan_dir"] == "plans/prod"


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
    # ...except the compose capability probe (#407): the regression here is a
    # failing *phase*, so the front-end itself is healthy Compose v2. Without
    # this the upgrade refuses at preflight — correct new behavior, but a
    # different boundary than the one this test pins.
    recorder.compose_version_stdout = "Docker Compose version v2.39.2"
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


# -- subprocess boundary: transient failures, timeouts, retries ----------------


def _cmd(**extra: object) -> upgrade_mod._Cmd:
    return upgrade_mod._Cmd(["true"], **extra)  # type: ignore[arg-type]


def test_run_retries_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """A retriable command runs up to ``retries`` times; delay is slept between."""
    calls: list[list[str]] = []
    slept: list[float] = []

    def flaky(argv: list[str], **k: object) -> SimpleNamespace:
        calls.append(list(argv))
        if len(calls) < 3:
            return SimpleNamespace(returncode=1, stdout="", stderr="transient")
        return SimpleNamespace(returncode=0, stdout="fine", stderr="")

    monkeypatch.setattr(upgrade_mod, "_RUN_SUBPROCESS", flaky)
    monkeypatch.setattr(upgrade_mod.time, "sleep", slept.append)
    outcome = upgrade_mod._run(_cmd(retries=3, retry_delay=2.0))

    assert outcome.ok
    assert len(calls) == 3
    assert slept == [2.0, 2.0]


def test_run_missing_binary_is_permanent_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing executable surfaces immediately: no retry can install it."""
    calls: list[list[str]] = []

    def absent(argv: list[str], **k: object) -> SimpleNamespace:
        calls.append(list(argv))
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(upgrade_mod, "_RUN_SUBPROCESS", absent)
    outcome = upgrade_mod._run(_cmd(retries=5))

    assert not outcome.ok
    assert outcome.missing == "true"
    assert "command not found" in outcome.stderr
    assert len(calls) == 1


def test_run_timeout_partial_output_is_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout partials may be bytes; they are decoded, never raised past _run."""

    def slow(argv: list[str], **k: object) -> object:
        raise subprocess.TimeoutExpired(cmd=argv[0], timeout=0.1, output=b"partial")

    monkeypatch.setattr(upgrade_mod, "_RUN_SUBPROCESS", slow)
    outcome = upgrade_mod._run(_cmd())

    assert not outcome.ok
    assert outcome.timed_out
    assert outcome.stdout == "partial"
    assert upgrade_mod._coerce(None) == ""
    assert upgrade_mod._coerce(b"raw") == "raw"
    assert upgrade_mod._coerce("text") == "text"


def test_read_env_port_defaults_when_unset(tmp_path: Path) -> None:
    """A .env without MAISTRO_PORT (or absent entirely) falls back to 8000."""
    (tmp_path / ".env").write_text("TOKEN=secret\nOTHER=1\n", encoding="utf-8")
    assert upgrade_mod._read_env_port(tmp_path) == "8000"
    (tmp_path / ".env").write_text("MAISTRO_PORT=9001\n", encoding="utf-8")
    assert upgrade_mod._read_env_port(tmp_path) == "9001"


def test_source_cmds_unknown_type_plan_nothing(tmp_path: Path) -> None:
    """Non-source install types have no source-update phase at all."""
    driver = upgrade_mod._Upgrade(
        tmp_path, InstallManifest(install_type="package", install_root=str(tmp_path)), "package"
    )
    assert driver.source_cmds() == []


@pytest.mark.parametrize(
    ("which", "expected"),
    [
        ({"docker": "/usr/bin/docker", "podman": "/usr/bin/podman"}, "docker compose"),
        ({"docker": "/usr/bin/docker"}, "docker compose"),
        ({"podman": "/usr/bin/podman"}, "podman compose"),
        # No Compose v1 fallback (#407): a host with only the legacy
        # `docker-compose` binary resolves to the default v2 front-end, and
        # the preflight capability probe refuses it with upgrade
        # instructions instead of letting a phase fail mid-upgrade.
        ({"docker-compose": "/usr/bin/docker-compose"}, "docker compose"),
        ({}, "docker compose"),
    ],
)
def test_compose_runtime_resolution(
    monkeypatch: pytest.MonkeyPatch, which: dict[str, str], expected: str
) -> None:
    monkeypatch.setattr(
        upgrade_mod.shutil,
        "which",
        lambda name: which.get(name),  # type: ignore[arg-type,return-value]
    )
    assert " ".join(upgrade_mod._resolve_compose_runtime()) == expected


# -- compose capability probe (#407) --------------------------------------------


class _ComposeFake:
    """A stand-in for ``_RUN_SUBPROCESS`` that answers the compose probes.

    The ``<compose> version`` probe returns ``version_output``; a ``missing``
    fake raises ``FileNotFoundError`` like an absent binary would. Every other
    command (the ``compose config`` schema probe, then all phases) returns
    ``config_ok`` / success respectively.
    """

    def __init__(
        self,
        version_output: str | None = None,
        *,
        config_ok: bool = True,
        missing: bool = False,
        config_stderr: str = "services.depends_on contains an invalid type",
    ) -> None:
        self.version_output = version_output
        self.config_ok = config_ok
        self.missing = missing
        self.config_stderr = config_stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs: object):
        self.calls.append(list(argv))
        if argv[-1] == "version" and argv[:2] in (["docker", "compose"], ["podman", "compose"]):
            if self.missing:
                raise FileNotFoundError(2, "No such file or directory", argv[0])
            return SimpleNamespace(
                returncode=0 if self.version_output is not None else 1,
                stdout=self.version_output or "",
                stderr="",
            )
        if argv[-2:] == ["config", "--quiet"]:
            return SimpleNamespace(
                returncode=0 if self.config_ok else 1,
                stdout="",
                stderr=self.config_stderr,
            )
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")


@pytest.fixture
def compose_fake(monkeypatch: pytest.MonkeyPatch):
    """Install a ``_ComposeFake`` and pin the platform hint to plain Linux so
    assertions on the upgrade instructions are host-independent (this repo's
    dev boxes are WSL, CI runners are not)."""

    def _install(fake: _ComposeFake) -> _ComposeFake:
        monkeypatch.setattr(upgrade_mod, "_RUN_SUBPROCESS", fake)
        monkeypatch.setattr(upgrade_mod.platform, "system", lambda: "Linux")
        monkeypatch.setattr(upgrade_mod.platform, "release", lambda: "6.8.0-generic")
        return fake

    return _install


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Docker Compose version v2.39.2", (2, 39, 2)),
        ("Docker Compose version v2.17.0", (2, 17, 0)),
        ("v2.24.6-desktop.1", (2, 24, 6)),
        ("2.5", (2, 5, 0)),
        ("podman-compose version 1.0.6", (1, 0, 6)),
        ("docker-compose version 1.29.2, build 5becea4c", (1, 29, 2)),
        ("", None),
        ("compose ready", None),
    ],
)
def test_parse_compose_version_extracts_dotted_tokens(
    text: str, expected: tuple[int, int, int] | None
) -> None:
    assert upgrade_mod._parse_compose_version(text) == expected


def test_a_below_floor_compose_is_refused_with_upgrade_instructions(
    compose_fake,
) -> None:
    fake = compose_fake(_ComposeFake("Docker Compose version v2.16.0"))
    error = upgrade_mod._compose_support_error(["docker", "compose"], ["-f", "stack.yml"])
    assert error is not None
    assert "2.17.0" in error
    assert "2.16.0" in error
    assert "re-run `maistro upgrade`" in error
    # Only the read-only probe ran; no config fallback was needed.
    assert fake.calls == [["docker", "compose", "version"]]


@pytest.mark.parametrize("version", ["v2.17.0", "Docker Compose version v2.24.6", "v3.0.0"])
def test_compose_at_or_above_the_floor_is_accepted(compose_fake, version: str) -> None:
    compose_fake(_ComposeFake(f"Docker Compose version {version}"))
    assert upgrade_mod._compose_support_error(["docker", "compose"], ["-f", "stack.yml"]) is None


def test_an_unparseable_version_feature_detects_the_schema_parse(compose_fake) -> None:
    """Version strings are unreliable across front-ends; when none can be read,
    the stack's own compose files decide: a frontend that parses the schema is
    exactly the capability the version floor stands in for."""
    compose_fake(_ComposeFake(""))
    assert upgrade_mod._compose_support_error(["docker", "compose"], ["-f", "stack.yml"]) is None


def test_an_unparseable_version_with_an_unparseable_schema_is_refused(
    compose_fake,
) -> None:
    compose_fake(_ComposeFake("", config_ok=False))
    error = upgrade_mod._compose_support_error(["docker", "compose"], ["-f", "stack.yml"])
    assert error is not None
    assert "conditional depends_on" in error
    assert "2.17.0" in error
    assert "docker compose" in error
    # The refusal surfaces the compose error itself, so a missing .env
    # variable is distinguishable from a v1-generation engine's schema gap.
    assert "services.depends_on contains an invalid type" in error


def test_an_absent_frontend_is_left_to_the_phase_time_error(compose_fake) -> None:
    """A host with no compose at all fails its phases with the normal
    ``command not found`` outcome; stacking a second refusal on top would
    only obscure it."""
    compose_fake(_ComposeFake(missing=True))
    assert upgrade_mod._compose_support_error(["docker", "compose"], ["-f", "stack.yml"]) is None


@pytest.mark.parametrize(
    ("system", "release", "fragment"),
    [
        ("Darwin", "24.0.0", "On macOS"),
        ("Windows", "11", "On Windows"),
        ("Linux", "5.15.167.4-microsoft-standard-WSL2", "In WSL2"),
        ("Linux", "6.8.0-generic", "On Linux"),
    ],
)
def test_the_upgrade_hint_names_the_operators_platform(
    monkeypatch: pytest.MonkeyPatch, system: str, release: str, fragment: str
) -> None:
    monkeypatch.setattr(upgrade_mod.platform, "system", lambda: system)
    monkeypatch.setattr(upgrade_mod.platform, "release", lambda: release)
    hint = upgrade_mod._compose_upgrade_hint()
    assert fragment in hint
    # Every platform's pointer names a concrete upgrade source.
    assert "docker-compose-plugin" in hint or "Docker Desktop" in hint


def test_a_silent_config_failure_still_refuses_and_says_so(compose_fake) -> None:
    """A config probe that fails without any diagnostic still refuses, and the
    message says no compose error was captured rather than inventing one."""
    compose_fake(_ComposeFake("", config_ok=False, config_stderr=""))
    error = upgrade_mod._compose_support_error(["docker", "compose"], ["-f", "stack.yml"])
    assert error is not None
    assert "The compose error was: none." in error


def test_preflight_refuses_a_below_floor_compose_before_any_phase(
    tmp_path: Path,
    unrelated_cwd: Path,
    recorder: _Recorder,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The definition of done: an upgrade must abort before it moves the
    source tree when the compose engine cannot run the stack."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _write_manifest(root, _manifest(root, "git"))
    # Pin the front-end resolution so the probe argv is deterministic.
    monkeypatch.setattr(
        upgrade_mod.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None
    )
    # The version probe must return a real (below-floor) version string, so a
    # targeted fake answers only that command; every other command goes to the
    # recorder — and must never be reached.
    version_fake = _ComposeFake("Docker Compose version v2.16.0")

    def dispatcher(argv, **kwargs: object):
        if argv[-1] == "version" and argv[:2] == ["docker", "compose"]:
            return version_fake(argv, **kwargs)
        return recorder(argv, **kwargs)

    monkeypatch.setattr(upgrade_mod, "_RUN_SUBPROCESS", dispatcher)  # type: ignore[arg-type]

    with pytest.raises(SystemExit) as exc_info:
        _drive(root, recorder)

    assert exc_info.value.code == 1
    out = " ".join(capsys.readouterr().out.split())
    assert "Preflight failed" in out
    assert "No changes were made" in out
    assert "2.16.0" in out
    assert recorder.calls == []


# Package cutover is `uv tool upgrade`; its phases never drive compose, so a
# package-only host is not asked for one — enforced by the existing
# test_package_upgrade_runs_uv_tool_upgrade assertion that no recorded call
# mentions compose at all.


# -- preflight rejections per install type -------------------------------------


def test_preflight_archive_without_release_ref_aborts(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    """An archive install must record the ref it targets, or upgrade cannot plan."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    bad = InstallManifest(
        install_type="archive",
        install_root=str(root),
        install_surface="curl",
        image_tag="v1.0.0",
        delivery_mode="source_build",
        source_url="https://github.com/Agent-StrongHold/Project-mAIstro",
    )
    _write_manifest(root, bad)

    with pytest.raises(SystemExit) as exc_info:
        _drive(root, recorder)
    assert exc_info.value.code == 1
    assert not recorder.calls
    assert "No changes were made" in capsys.readouterr().out


def test_preflight_container_without_image_tag_aborts(
    tmp_path: Path,
    unrelated_cwd: Path,
    recorder: _Recorder,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container install without a pinned tag has nothing verifiable to pull."""
    monkeypatch.delenv("MAISTRO_IMAGE_TAG", raising=False)
    root = tmp_path / "maistro-engine"
    root.mkdir()
    bad = InstallManifest(
        install_type="container",
        install_root=str(root),
        install_surface="container",
    )
    _write_manifest(root, bad)

    with pytest.raises(SystemExit) as exc_info:
        _drive(root, recorder)
    assert exc_info.value.code == 1
    assert not recorder.calls
    assert "No changes were made" in capsys.readouterr().out


# -- transactional internals ---------------------------------------------------


def test_backup_is_idempotent_per_run(tmp_path: Path) -> None:
    """A second backup call must not fork a second snapshot of operator config."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
    driver = upgrade_mod._Upgrade(root, _manifest(root, "git"), "git")
    driver.backup()
    first = driver.backup_dir
    assert first is not None and first.is_dir()
    driver.backup()
    assert driver.backup_dir == first


def test_rollback_without_retained_archive_tree_restores_config(tmp_path: Path) -> None:
    """Rollback tolerates a vanished root/retained tree: config restore still runs."""
    root = tmp_path / "vanished-root"
    driver = upgrade_mod._Upgrade(root, _manifest(root, "archive"), "archive")
    driver.backup_dir = tmp_path / "backup"
    driver.backup_dir.mkdir()
    (driver.backup_dir / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
    driver._archive_swapped = True
    driver._archive_old = tmp_path / "vanished-old"

    driver.rollback()  # must not raise

    assert (root / ".env").is_file(), "config restored even with no tree to swap back"


def test_readiness_failure_after_cutover_rolls_back_the_stack(
    tmp_path: Path,
    unrelated_cwd: Path,
    recorder: _Recorder,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed readiness probe AFTER cutover stops the new stack and restarts the old.

    The health probe polls with a bounded budget (matching the installer's
    post-up wait); when it still fails, rollback stops the stack and brings it
    back up from the rewound source. No success is ever printed.
    """
    monkeypatch.setattr(upgrade_mod.time, "sleep", lambda _s: None)
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    _write_manifest(root, _manifest(root, install_type="git"))

    recorder.failures["curl"] = "connection refused"
    with pytest.raises(SystemExit) as exc_info:
        _drive(root, recorder)
    assert exc_info.value.code == 1

    out = capsys.readouterr().out
    assert "Upgrade complete" not in out
    assert "Rolling back" in out
    flat = [" ".join(a) for a, _ in recorder.calls]
    # Rollback stopped the (new) stack and brought the rewound source back up.
    assert any("compose" in c and " down" in c for c in flat)
    assert any("compose" in c and "up -d" in c for c in flat)
    # The health probe polled with its bounded budget before giving up.
    assert sum(1 for c in flat if "health/ready" in c) == upgrade_mod._HEALTH_ATTEMPTS


def test_source_build_rollback_restores_pre_upgrade_images(
    tmp_path: Path,
    unrelated_cwd: Path,
    recorder: _Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source build must not destroy the previous release's images.

    ``compose build`` retags the fixed local image tags before cutover; a
    later rollback that just runs ``down`` + ``up -d`` would restart the NEW
    images. The pre-upgrade images are therefore snapshotted under rollback
    tags before the build and retagged back before the post-rollback ``up``.
    """
    monkeypatch.setattr(upgrade_mod.time, "sleep", lambda _s: None)
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    _write_manifest(root, _manifest(root, install_type="git"))

    recorder.failures["curl"] = "connection refused"
    with pytest.raises(SystemExit) as exc_info:
        _drive(root, recorder)
    assert exc_info.value.code == 1

    seq = [" ".join(a) for a, _ in recorder.calls]
    snap_i = next(i for i, c in enumerate(seq) if "pre-upgrade-rollback" in c and " tag " in c)
    build_i = next(i for i, c in enumerate(seq) if "compose" in c and " build" in c)
    restore_i = next(i for i, c in enumerate(seq) if "image inspect" in c)
    up_i = max(i for i, c in enumerate(seq) if "up -d" in c)
    assert snap_i < build_i, "images must be snapshotted before compose build retags them"
    assert restore_i < up_i, "snapshot must be restored before the post-rollback restart"


def test_committed_source_build_drops_image_snapshot_tags(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder
) -> None:
    """On success the rollback tags are cleaned up, not left to accumulate."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    _seed_compose_and_env(root)
    _write_manifest(root, _manifest(root, install_type="git"))

    _drive(root, recorder)

    seq = [" ".join(a) for a, _ in recorder.calls]
    up_i = max(i for i, c in enumerate(seq) if "up -d" in c)
    cleanup = [c for c in seq[up_i:] if "pre-upgrade-rollback" in c and " rmi " in c]
    assert cleanup, "commit must remove the pre-upgrade rollback tags"


def test_compose_args_prefer_install_compose_for_image_pull(tmp_path: Path) -> None:
    """image_pull replay uses the wizard's standalone file; source build layers the override."""
    root = tmp_path / "maistro-engine"
    plan = root / PLAN_SUBDIR
    plan.mkdir(parents=True)
    install_compose = plan / "compose.install.yml"
    install_compose.write_text("services: {}\n", encoding="utf-8")

    pull = upgrade_mod._Upgrade(root, _manifest(root, "tag", delivery_mode="image_pull"), "tag")
    assert str(install_compose) in " ".join(pull._compose_args())

    install_compose.unlink()
    override = plan / "compose.override.yml"
    override.write_text("services: {}\n", encoding="utf-8")
    build = upgrade_mod._Upgrade(root, _manifest(root, "git"), "git")
    args = " ".join(build._compose_args())
    assert str(root / "docker-compose.yml") in args
    assert str(override) in args


@pytest.mark.parametrize("kind", ["weird", ""])
def test_unknown_install_type_has_no_phases_or_readiness(kind: str) -> None:
    """An unclassifiable install plans nothing rather than improvising commands."""
    root = Path("/tmp/maistro-engine-does-not-exist")
    driver = upgrade_mod._Upgrade(
        root,
        InstallManifest(install_type="git", install_root=str(root)),
        kind,
    )
    assert driver.phases() == []
    assert driver.readiness_cmds() == []


def test_archive_planner_refuses_to_fetch_without_a_target(tmp_path: Path) -> None:
    """Defense in depth: the archive planner itself refuses a targetless refetch."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    manifest = InstallManifest(
        install_type="archive",
        install_root=str(root),
        install_surface="curl",
        image_tag="v1.0.0",
        delivery_mode="source_build",
        source_url=" ",  # whitespace passes the truthiness preflight...
    )
    driver = upgrade_mod._Upgrade(root, manifest, "archive")
    with pytest.raises(upgrade_mod._UpgradeError, match="source_url"):
        driver._archive_download_cmds()


def test_archive_success_without_git_metadata_skips_revision_line(
    tmp_path: Path,
    unrelated_cwd: Path,
    recorder: _Recorder,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive trees have no HEAD; success reports no source revision."""
    root = tmp_path / "maistro-engine"
    root.mkdir()
    (root / ".env").write_text("MAISTRO_PORT=8000\n", encoding="utf-8")
    _write_manifest(root, _manifest(root, install_type="archive", ref="v1.1.0", version="v1.1.0"))
    monkeypatch.setattr(upgrade_mod, "git_revision", lambda _root: None)

    _drive(root, recorder)

    out = capsys.readouterr().out
    assert "Upgrade complete" in out
    assert "source revision" not in out


# -- packaged / container provenance detection ---------------------------------


def test_detect_packaged_from_manifest_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "install-manifest.json"
    manifest = InstallManifest(
        install_type="package", install_root=str(tmp_path / "tools"), install_surface="package"
    )
    packaged.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", packaged)
    kind, root, loaded = upgrade_mod._detect_packaged_or_container()
    assert kind == "package"
    assert root == (tmp_path / "tools").resolve()
    assert loaded is not None and loaded.install_type == "package"


def test_detect_packaged_manifest_with_empty_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "install-manifest.json"
    manifest = InstallManifest(install_type="package", install_root="", install_surface="package")
    packaged.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", packaged)
    kind, root, loaded = upgrade_mod._detect_packaged_or_container()
    assert kind == "package"
    assert root is None
    assert loaded is not None


def test_detect_corrupt_packaged_manifest_is_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = tmp_path / "install-manifest.json"
    packaged.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", packaged)
    monkeypatch.delenv("MAISTRO_CONTAINER", raising=False)
    monkeypatch.setattr(upgrade_mod.Path, "exists", lambda self: False)  # /.dockerenv probe
    assert upgrade_mod._detect_packaged_or_container() == (None, None, None)


def test_detect_booted_container_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", tmp_path / "absent.json")
    monkeypatch.setenv("MAISTRO_CONTAINER", "1")
    monkeypatch.setattr(upgrade_mod.Path, "exists", lambda self: False)
    kind, root, manifest = upgrade_mod._detect_packaged_or_container()
    assert kind == "container"
    assert root == Path("/maistro-engine")
    assert manifest is not None and manifest.install_surface == "container"


def test_detect_packaged_cli_via_distribution_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An importable maistro-core outside any checkout is a packaged install."""
    import importlib.metadata as im

    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", tmp_path / "absent.json")
    monkeypatch.delenv("MAISTRO_CONTAINER", raising=False)
    monkeypatch.setattr(upgrade_mod.Path, "exists", lambda self: False)

    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()

    class _FakeDist:
        def locate_file(self, path: object) -> object:
            return site_packages

    monkeypatch.setattr(im, "distribution", lambda _name: _FakeDist())
    kind, root, manifest = upgrade_mod._detect_packaged_or_container()
    assert kind == "package"
    assert root == site_packages.resolve()
    assert manifest is not None and manifest.install_surface == "package"


def test_detect_distribution_inside_a_checkout_is_not_a_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.metadata as im

    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", tmp_path / "absent.json")
    monkeypatch.delenv("MAISTRO_CONTAINER", raising=False)
    monkeypatch.setattr(upgrade_mod.Path, "exists", lambda self: False)

    checkout = tmp_path / "engine"
    checkout.mkdir()
    (checkout / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    class _FakeDist:
        def locate_file(self, path: object) -> object:
            return checkout

    monkeypatch.setattr(im, "distribution", lambda _name: _FakeDist())
    assert upgrade_mod._detect_packaged_or_container() == (None, None, None)


def test_detect_without_distribution_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.metadata as im

    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", tmp_path / "absent.json")
    monkeypatch.delenv("MAISTRO_CONTAINER", raising=False)
    monkeypatch.setattr(upgrade_mod.Path, "exists", lambda self: False)

    def absent(_name: str) -> object:
        raise im.PackageNotFoundError("maistro-core")

    monkeypatch.setattr(im, "distribution", absent)
    assert upgrade_mod._detect_packaged_or_container() == (None, None, None)


def test_booted_container_is_upgraded_from_detection_alone(
    unrelated_cwd: Path,
    recorder: _Recorder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No checkout, no manifest, but running in a container: upgrade the image stack."""
    monkeypatch.setattr(upgrade_mod, "locate_install_root", lambda start=None: (None, None))
    monkeypatch.setattr(upgrade_mod, "_PACKAGED_MANIFEST", tmp_path / "absent.json")
    monkeypatch.setenv("MAISTRO_CONTAINER", "1")
    monkeypatch.setenv("MAISTRO_IMAGE_TAG", "v1.2.3")
    monkeypatch.setattr(upgrade_mod.Path, "exists", lambda self: False)

    upgrade_main()

    flat = [" ".join(a) for a, _ in recorder.calls]
    assert any("compose" in c and " pull" in c for c in flat)
    assert any("health/ready" in c for c in flat)


def test_manifest_without_root_falls_through_to_detection(
    tmp_path: Path, unrelated_cwd: Path, recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest whose root vanished is not a target; the packaged fallback decides."""
    ghost = InstallManifest(install_type="git", install_root=str(tmp_path / "ghost"))
    monkeypatch.setattr(upgrade_mod, "locate_install_root", lambda start=None: (None, ghost))
    monkeypatch.setattr(upgrade_mod, "_detect_packaged_or_container", lambda: (None, None, None))

    with pytest.raises(SystemExit) as exc_info:
        upgrade_main()
    assert exc_info.value.code == 1
    assert not recorder.calls


def test_undetectable_checkout_reports_missing_install(
    tmp_path: Path,
    unrelated_cwd: Path,
    recorder: _Recorder,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A found checkout whose type cannot be detected is not silently upgraded."""
    shapeless = tmp_path / "not-a-checkout"
    shapeless.mkdir()
    monkeypatch.setattr(upgrade_mod, "locate_install_root", lambda start=None: (shapeless, None))
    monkeypatch.setattr(upgrade_mod, "_detect_packaged_or_container", lambda: (None, None, None))

    with pytest.raises(SystemExit) as exc_info:
        upgrade_main()
    assert exc_info.value.code == 1
    assert not recorder.calls
    assert "could not find an install" in capsys.readouterr().out
