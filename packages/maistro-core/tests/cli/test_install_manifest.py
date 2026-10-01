"""Tests for the durable install manifest (`maistro.upgrade` targets).

Covers install-type detection, manifest load/write round-trips, and root
location from an *unrelated* working directory (the core regression #353:
upgrade must never resolve its target from the ambient CWD).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import maistro.cli._install_manifest as manifest_mod
from maistro.cli._install_manifest import (
    ARCHIVE_MARKER,
    MANIFEST_FILENAME,
    PLAN_SUBDIR,
    InstallManifest,
    detect_install_type,
    git_revision,
    is_engine_checkout,
    load_manifest,
    locate_install_root,
    write_manifest,
)


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def engine_checkout(tmp_path: Path) -> Path:
    """A real maistro-engine checkout (git + matching compose + pyproject)."""
    _git(["init", "-q"], tmp_path)
    _git(["config", "user.email", "t@t.t"], tmp_path)
    _git(["config", "user.name", "t"], tmp_path)
    _git(
        ["remote", "add", "origin", "https://github.com/Agent-StrongHold/Project-mAIstro.git"],
        tmp_path,
    )
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  maistro-engine:\n    image: maistro-engine\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "maistro-workspace"\n', encoding="utf-8"
    )
    (tmp_path / "README").write_text("source\n", encoding="utf-8")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-qm", "init"], tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the default install parent at a temp dir so tests never touch ~."""
    monkeypatch.setattr(manifest_mod, "DEFAULT_INSTALL_PARENT", tmp_path / "maistro")
    monkeypatch.setattr(
        manifest_mod, "DEFAULT_SOURCE_INSTALL_DIR", tmp_path / "maistro" / "maistro-engine"
    )
    monkeypatch.setenv("MAISTRO_REPO_ROOT", "")


class TestDetectInstallType:
    def test_git_checkout_is_git(self, engine_checkout: Path) -> None:
        assert detect_install_type(engine_checkout) == "git"

    def test_tagged_checkout_is_tag(self, engine_checkout: Path) -> None:
        _git(["tag", "v1.0.0"], engine_checkout)
        assert detect_install_type(engine_checkout) == "tag"
        assert git_revision(engine_checkout) is not None

    def test_archive_marker_is_archive(self, tmp_path: Path) -> None:
        (tmp_path / ARCHIVE_MARKER).write_text("", encoding="utf-8")
        assert detect_install_type(tmp_path) == "archive"

    def test_plain_directory_is_unsupported(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
        assert detect_install_type(tmp_path) is None


class TestEngineCheckout:
    def test_real_checkout_is_detected(self, engine_checkout: Path) -> None:
        assert is_engine_checkout(engine_checkout) is True

    def test_plain_directory_is_not_an_engine_checkout(self, tmp_path: Path) -> None:
        assert is_engine_checkout(tmp_path) is False

    def test_unrelated_compose_file_is_not_an_engine_checkout(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text("services:\n  other: {}\n", encoding="utf-8")
        assert is_engine_checkout(tmp_path) is False

    def test_marker_without_pyproject_is_still_a_checkout(self, tmp_path: Path) -> None:
        """compose with the marker and no pyproject: checkout shape, engine assumed."""
        (tmp_path / "docker-compose.yml").write_text(
            "services:\n  maistro-engine:\n    image: x\n", encoding="utf-8"
        )
        assert is_engine_checkout(tmp_path) is True

    def test_unreadable_pyproject_still_assumes_engine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A compose that names the engine is enough when pyproject can't be read."""
        compose = tmp_path / "docker-compose.yml"
        pyproject = tmp_path / "pyproject.toml"
        compose.write_text("services:\n  maistro-engine:\n    image: x\n", encoding="utf-8")
        pyproject.write_text("[project]\n", encoding="utf-8")
        real_read = Path.read_text

        def raising_for_pyproject(self: Path, *a: object, **k: object) -> str:
            if self.name == "pyproject.toml":
                raise OSError("simulated unreadable file")
            return real_read(self, *a, **k)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", raising_for_pyproject)
        assert is_engine_checkout(tmp_path) is True

    def test_unreadable_compose_is_not_an_engine_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the compose itself can't be read, no engine shape can be proven."""
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services:\n  maistro-engine:\n", encoding="utf-8")
        real_read = Path.read_text

        def raising_for_compose(self: Path, *a: object, **k: object) -> str:
            if self.name == "docker-compose.yml":
                raise OSError("simulated unreadable file")
            return real_read(self, *a, **k)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", raising_for_compose)
        assert is_engine_checkout(tmp_path) is False


class TestGitProbeFailurePaths:
    """git unavailable/stalled: probes degrade to None/False, never raise."""

    def test_run_git_timeout_returns_none(
        self, engine_checkout: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess as sp

        def stalling(*a: object, **k: object) -> object:
            raise sp.TimeoutExpired(cmd="git", timeout=0.1)

        monkeypatch.setattr(manifest_mod.subprocess, "run", stalling)
        assert manifest_mod.has_working_tree(engine_checkout) is False
        assert manifest_mod.git_revision(engine_checkout) is None

    def test_failing_git_revparse_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess as sp

        cp = sp.CompletedProcess(args=[], returncode=128, stdout="", stderr="not a repo")
        monkeypatch.setattr(manifest_mod, "_run_git", lambda *a, **k: cp)
        assert manifest_mod.has_working_tree(tmp_path) is False
        assert manifest_mod.git_revision(tmp_path) is None

    def test_current_version_missing_package_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import importlib.metadata as im

        def missing(name: str) -> str:
            raise im.PackageNotFoundError(name)

        monkeypatch.setattr(manifest_mod._metadata, "version", missing)
        assert manifest_mod.current_version() is None


class TestManifestRoundTrip:
    def test_write_then_load_preserves_fields(self, engine_checkout: Path) -> None:
        original = InstallManifest(
            install_type="tag",
            install_root=str(engine_checkout),
            install_surface="curl",
            version="v1.0.0",
            ref="v1.0.0",
            revision="abc123",
            image_tag="v1.0.0",
            delivery_mode="image_pull",
            source_url="https://github.com/Agent-StrongHold/Project-mAIstro",
            installed_at="2026-01-01T00:00:00Z",
        )
        path = write_manifest(engine_checkout, original)
        assert path.is_file()
        # An already-recorded timestamp is authoritative; write must not bump it.
        assert original.installed_at == "2026-01-01T00:00:00Z"
        loaded = load_manifest(engine_checkout)
        assert loaded is not None
        assert loaded.install_type == "tag"
        assert loaded.install_root == str(engine_checkout.resolve())
        assert loaded.version == "v1.0.0"
        assert loaded.image_tag == "v1.0.0"
        assert loaded.delivery_mode == "image_pull"
        assert loaded.source_url == original.source_url
        assert loaded.installed_at is not None

    def test_load_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        assert load_manifest(tmp_path) is None

    def test_load_corrupt_manifest_returns_none(self, tmp_path: Path) -> None:
        plan = tmp_path / PLAN_SUBDIR
        plan.mkdir()
        (plan / MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
        assert load_manifest(tmp_path) is None

    def test_load_invalid_schema_returns_none(self, tmp_path: Path) -> None:
        plan = tmp_path / PLAN_SUBDIR
        plan.mkdir()
        (plan / MANIFEST_FILENAME).write_text(
            json.dumps({"kind": "wrong", "install_type": "git"}),
            encoding="utf-8",
        )
        assert load_manifest(tmp_path) is None

    def test_load_unknown_install_type_is_rejected(self, tmp_path: Path) -> None:
        """A valid-kind manifest with an unsupported install_type fails validation."""
        plan = tmp_path / PLAN_SUBDIR
        plan.mkdir()
        (plan / MANIFEST_FILENAME).write_text(
            json.dumps({"kind": "maistro_install_manifest", "install_type": "floppy"}),
            encoding="utf-8",
        )
        assert load_manifest(tmp_path) is None

    def test_load_newer_schema_version_is_treated_as_absent(self, tmp_path: Path) -> None:
        """A manifest from a NEWER installer must not be guessed at.

        Forward compatibility: an older upgrader reading an unknown schema
        treats the manifest as absent, so the caller reports "no install found"
        and points the operator at the installer instead of misreading fields it
        does not understand.
        """
        plan = tmp_path / PLAN_SUBDIR
        plan.mkdir()
        future = {
            "kind": "maistro_install_manifest",
            "schema_version": manifest_mod.MANIFEST_SCHEMA_VERSION + 1,
            "install_type": "git",
            "install_root": str(tmp_path),
        }
        (plan / MANIFEST_FILENAME).write_text(json.dumps(future), encoding="utf-8")
        assert load_manifest(tmp_path) is None
        # The current schema version still loads.
        future["schema_version"] = manifest_mod.MANIFEST_SCHEMA_VERSION
        (plan / MANIFEST_FILENAME).write_text(json.dumps(future), encoding="utf-8")
        assert load_manifest(tmp_path) is not None

    def test_load_normalizes_tilde_and_relative_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator-editable manifest must never leak a ``~``/relative root."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        plan = tmp_path / "checkout" / PLAN_SUBDIR
        plan.mkdir(parents=True)
        raw = {
            "kind": "maistro_install_manifest",
            "install_type": "git",
            "install_root": "~/checkout",
        }
        (plan / MANIFEST_FILENAME).write_text(json.dumps(raw), encoding="utf-8")
        loaded = load_manifest(tmp_path / "checkout")
        assert loaded is not None
        expected = (tmp_path / "home" / "checkout").resolve()
        assert loaded.install_root == str(expected)


class TestLocateInstallRoot:
    def test_locates_via_env_override(
        self, engine_checkout: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_manifest(engine_checkout, _tag_manifest(engine_checkout))
        monkeypatch.setenv("MAISTRO_REPO_ROOT", str(engine_checkout))
        root, manifest = locate_install_root()
        assert root == engine_checkout.resolve()
        assert manifest is not None
        assert manifest.install_type == "tag"

    def test_locates_from_unrelated_subdir_via_parent_walk(
        self, engine_checkout: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression: upgrading from a directory that is NOT the install root."""
        write_manifest(engine_checkout, _tag_manifest(engine_checkout))
        unrelated = engine_checkout / "subdir" / "elsewhere"
        unrelated.mkdir(parents=True)
        monkeypatch.chdir(unrelated)
        root, manifest = locate_install_root()
        assert root == engine_checkout.resolve()
        assert manifest is not None
        assert manifest.install_root == str(engine_checkout.resolve())

    def test_locates_default_source_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Run from a neutral dir so the parent walk cannot find the maistro repo.
        monkeypatch.chdir(tmp_path)
        parent = manifest_mod.DEFAULT_INSTALL_PARENT
        source = parent / "maistro-engine"
        source.mkdir(parents=True)
        write_manifest(source, _git_manifest(source))
        root, manifest = locate_install_root()
        assert root == source.resolve()
        assert manifest is not None
        assert manifest.install_type == "git"

    def test_locates_packaged_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        parent = manifest_mod.DEFAULT_INSTALL_PARENT
        parent.mkdir(parents=True, exist_ok=True)
        packaged = InstallManifest(
            install_type="package",
            install_root="/opt/maistro",
            install_surface="package",
        )
        parent.joinpath(MANIFEST_FILENAME).write_text(
            json.dumps(packaged.model_dump(mode="json")), encoding="utf-8"
        )
        root, manifest = locate_install_root()
        assert root == Path("/opt/maistro").resolve()
        assert manifest is not None
        assert manifest.install_type == "package"

    def test_env_override_pointing_nowhere_falls_through_to_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale MAISTRO_REPO_ROOT must not win; the parent walk still resolves."""
        monkeypatch.setenv("MAISTRO_REPO_ROOT", str(tmp_path / "vanished"))
        checkout = tmp_path / "maistro-engine"
        inner = checkout / "docs" / "notes"
        inner.mkdir(parents=True)
        write_manifest(checkout, _git_manifest(checkout))
        monkeypatch.chdir(inner)
        root, manifest = locate_install_root()
        assert root == checkout.resolve()
        assert manifest is not None

    def test_returns_none_when_no_install_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        root, manifest = locate_install_root()
        assert root is None
        assert manifest is None


class TestVersionAndImages:
    def test_current_version_is_present(self) -> None:
        assert manifest_mod.current_version() is not None

    def test_image_references_pin_tag(self) -> None:
        refs = manifest_mod.image_references("v1.2.3")
        assert refs["maistro-engine"] == "ghcr.io/agent-stronghold/maistro-engine:v1.2.3"
        assert refs["hive-conductor"] == "ghcr.io/agent-stronghold/hive-conductor:v1.2.3"

    def test_image_references_default_to_latest(self) -> None:
        refs = manifest_mod.image_references(None)
        assert refs["maistro-engine"] == "ghcr.io/agent-stronghold/maistro-engine:latest"


# -- helpers ------------------------------------------------------------------


def _tag_manifest(root: Path) -> InstallManifest:
    return InstallManifest(
        install_type="tag",
        install_root=str(root),
        version="v1.0.0",
        ref="v1.0.0",
        image_tag="v1.0.0",
        delivery_mode="image_pull",
    )


def _git_manifest(root: Path) -> InstallManifest:
    return InstallManifest(
        install_type="git",
        install_root=str(root),
        ref="main",
        image_tag="latest",
        delivery_mode="source_build",
    )
