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

import maistro.install_manifest as manifest_mod
from maistro.install_manifest import (
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
        )
        path = write_manifest(engine_checkout, original)
        assert path.is_file()
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
