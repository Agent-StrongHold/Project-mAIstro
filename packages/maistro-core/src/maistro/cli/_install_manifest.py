"""Durable install metadata that lets `maistro upgrade` resolve its target.

The installer (get.sh / maistro-install materialize) writes
``install-manifest.json`` next to the checkout and the materialized plan. The
manifest records **how** maistro was installed (git checkout, pinned release
tag, source archive, packaged CLI, or container) and the **authoritative**
install root, so `maistro upgrade` resolves the right upgrade path from
metadata rather than guessing from the caller's current directory.

When no manifest is present (e.g. an operator ran install.sh with
``--skip-wizard``, or installed maistro as a packaged tool), `maistro upgrade`
falls back to inspecting the environment and recording what it learns — but it
never trusts the ambient CWD for the authoritative root.
"""

from __future__ import annotations

import datetime as _dt
import importlib.metadata as _metadata
import json
import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

#: Filename of the durable install manifest, written into the install root's
#: plan directory (the same ``.maistro-install/`` the wizard materializes).
MANIFEST_FILENAME = "install-manifest.json"

#: Discriminator for the manifest document itself.
MANIFEST_KIND = "maistro_install_manifest"

#: Monotonic schema version for the manifest; bumped when the shape changes.
MANIFEST_SCHEMA_VERSION = 1

#: How the install was produced. These are the only modes `maistro upgrade`
#: has a supported, tested upgrade path for.
InstallType = Literal["git", "tag", "archive", "package", "container"]

#: Where the install was launched from. ``package``/``container`` describe
#: non-source installs whose provenance is a packaged tool or a container image
#: rather than the curl/checkout source flow.
InstallSurface = Literal["curl", "checkout", "package", "container"]

#: Standard install parent (mirrors get.sh's ``LEGACY_DIR`` / default target).
DEFAULT_INSTALL_PARENT = Path("~/.maistro").expanduser()

#: The default curl-install root: ``~/.maistro/maistro-engine``.
DEFAULT_SOURCE_INSTALL_DIR = DEFAULT_INSTALL_PARENT / "maistro-engine"

#: Subdirectory (relative to the install root) holding the plan + manifest.
PLAN_SUBDIR = ".maistro-install"

#: Marker file an archive install leaves at the install root.
ARCHIVE_MARKER = ".maistro-archive-install"

#: Services that carry ``build:`` keys in the root compose and are published
#: as images — the artifacts ``maistro upgrade`` rebuilds or pulls.
IMAGE_SERVICES: tuple[str, ...] = ("maistro-engine", "hive-conductor")

#: Default registry the image_pull compose pins to.
DEFAULT_IMAGE_REPOSITORY = "ghcr.io/agent-stronghold"


class InstallManifest(BaseModel):
    """Durable install identity + root, versioned for forward compatibility.

    Unknown fields are preserved (``extra="allow"``) so a newer installer never
    breaks an older upgrader that reads the file.
    """

    model_config = {"extra": "allow"}

    kind: str = Field(default=MANIFEST_KIND, description="Manifest discriminator.")
    schema_version: int = Field(
        default=MANIFEST_SCHEMA_VERSION, description="Manifest schema version."
    )

    # --- authoritative identity ---
    install_type: InstallType = Field(description="How the install was produced.")
    install_root: str = Field(description="Absolute path to the install root.")
    install_surface: InstallSurface = Field(default="curl")

    # --- version identity ---
    version: str | None = Field(
        default=None, description="Release tag if tagged (e.g. v1.2.3), else None."
    )
    ref: str | None = Field(default=None, description="Branch name or tag name that was installed.")
    revision: str | None = Field(
        default=None, description="Git HEAD sha (archive installs have none)."
    )
    image_tag: str | None = Field(
        default=None, description="Container tag compose pins to (E5/#298)."
    )
    source_url: str | None = Field(
        default=None,
        description="Canonical source repository URL (archive re-download target).",
    )
    delivery_mode: str | None = Field(
        default=None, description="image_pull | source_build (from install answers)."
    )
    installed_at: str | None = Field(
        default=None, description="ISO-8601 timestamp the install completed."
    )


def _run_git(
    args: list[str], root: Path, timeout: float = 10.0
) -> subprocess.CompletedProcess[str] | None:
    """Run git in ``root``; return None if git is unavailable or it stalls.

    A thin wrapper so tests can substitute a fake git without patching
    ``subprocess.run`` at every call site.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def has_working_tree(root: Path) -> bool:
    """True when ``root`` is inside (or is) a git repository."""
    cp = _run_git(["rev-parse", "--git-dir"], root=root, timeout=5.0)
    if cp is None:
        return False
    return cp.returncode == 0


def git_revision(root: Path) -> str | None:
    """The HEAD sha of ``root``, or None if it is not a git checkout."""
    cp = _run_git(["rev-parse", "HEAD"], root=root)
    if cp is None or cp.returncode != 0:
        return None
    rev = cp.stdout.strip()
    return rev or None


def git_exact_tag(root: Path) -> str | None:
    """The tag pointing at HEAD, if HEAD is exactly tagged (a release checkout)."""
    cp = _run_git(["describe", "--tags", "--exact-match"], root=root)
    if cp is None or cp.returncode != 0:
        return None
    tag = cp.stdout.strip()
    return tag or None


def detect_install_type(root: Path) -> InstallType | None:
    """Infer the install type from the checkout itself.

    Resolution order matters: an archive install leaves a marker but no ``.git``;
    a tagged install leaves ``.git`` *and* a tag annotation on HEAD; a branch
    install leaves ``.git`` with no tag on HEAD. A checkout that is neither
    git-tagged nor archive-marked cannot be auto-upgraded and returns ``None``.
    """
    if (root / ARCHIVE_MARKER).is_file():
        return "archive"
    if has_working_tree(root):
        if git_exact_tag(root) is not None:
            return "tag"
        return "git"
    return None


def is_engine_checkout(root: Path) -> bool:
    """True when ``root`` is a maistro-engine checkout (for parent-walk discovery)."""
    compose = root / "docker-compose.yml"
    if not compose.is_file():
        return False
    try:
        text = compose.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "maistro-engine:" not in text:
        return False
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return True
    try:
        pp = pyproject.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return 'name = "maistro-workspace"' in pp


def manifest_path_for_root(root: Path) -> Path:
    """Where the durable manifest lives relative to an install root."""
    return root / PLAN_SUBDIR / MANIFEST_FILENAME


def _load_at(path: Path) -> InstallManifest | None:
    """Parse a manifest from an arbitrary path, tolerating absence/corruption.

    The root is normalized here — at the one boundary where on-disk data enters
    the model — rather than in a field validator, and a manifest written by a
    *newer* installer (higher ``schema_version``) is treated as absent so the
    caller reports "no install found" and points the operator at the installer
    instead of guessing at an unknown schema.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("kind") != MANIFEST_KIND:
        return None
    try:
        manifest = InstallManifest.model_validate(data)
    except ValidationError:
        return None
    if manifest.schema_version > MANIFEST_SCHEMA_VERSION:
        return None
    # Operator-editable files must never leak a relative or ``~`` root into
    # upgrade's target resolution: every consumer treats install_root as
    # authoritative and absolute.
    manifest.install_root = str(Path(manifest.install_root).expanduser().resolve())
    return manifest


def load_manifest(root: Path) -> InstallManifest | None:
    """Read the durable manifest recorded at ``root``, or None."""
    return _load_at(manifest_path_for_root(root))


def write_manifest(root: Path, manifest: InstallManifest) -> Path:
    """Persist ``manifest`` next to the install root; returns the path written."""
    if manifest.installed_at is None:
        manifest.installed_at = _dt.datetime.now(_dt.UTC).isoformat()
    path = manifest_path_for_root(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def locate_install_root(
    start: Path | None = None,
) -> tuple[Path | None, InstallManifest | None]:
    """Resolve the authoritative install root and its manifest.

    Search order — durable metadata first, environment override second, and
    only as a last resort a parent walk for a checkout. The caller's CWD is
    never trusted as the install root; it is only used as the starting point
    for the walk.

    Returns ``(root, manifest)``. ``manifest`` is None when a checkout was found
    but never recorded one (the upgrade command then detects the install type
    itself from the tree). Returns ``(None, None)`` when no install can be
    found, which the caller turns into an actionable error.
    """
    start = (start or Path.cwd()).resolve()

    # 1) Explicit operator override — the authoritative root.
    env = os.environ.get("MAISTRO_REPO_ROOT", "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if root.is_dir():
            return root, load_manifest(root)

    # 2) Walk up from the caller looking for a manifest, then an engine checkout.
    for directory in [start, *start.parents]:
        manifest = load_manifest(directory)
        if manifest is not None:
            return directory, manifest
        if is_engine_checkout(directory):
            return directory, None

    # 3) The default curl-install location (~/.maistro/maistro-engine).
    if DEFAULT_SOURCE_INSTALL_DIR.is_dir():
        return DEFAULT_SOURCE_INSTALL_DIR, load_manifest(DEFAULT_SOURCE_INSTALL_DIR)

    # 4) A packaged or containerized install records a manifest in ~/.maistro.
    packaged = DEFAULT_INSTALL_PARENT / MANIFEST_FILENAME
    manifest = _load_at(packaged)
    if manifest is not None and manifest.install_root:
        root = Path(manifest.install_root).expanduser().resolve()
        return root, manifest

    return None, None


def current_version() -> str | None:
    """The version of the installed ``maistro-core`` CLI package.

    Used as the post-upgrade readiness proof: after a source upgrade the
    freshly ``uv sync``-ed CLI must report the target release, not whatever
    commit the operator last built.
    """
    try:
        return _metadata.version("maistro-core")
    except _metadata.PackageNotFoundError:
        return None


def image_references(image_tag: str | None = None) -> dict[str, str]:
    """The pinned image references for the services that have ``build:`` keys.

    ``image_tag`` follows E5/#298: a tagged install pins the matching tag, a
    branch install uses ``latest``.
    """
    tag = (image_tag or "").strip() or "latest"
    return {name: f"{DEFAULT_IMAGE_REPOSITORY}/{name}:{tag}" for name in IMAGE_SERVICES}
