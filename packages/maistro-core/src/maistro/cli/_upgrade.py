"""`maistro upgrade` subcommand — move an installed maistro-engine to a later release.

Upgrade resolves the authoritative install root and install type from the
durable install manifest (written by ``get.sh`` / ``maistro-install``) and never
from the caller's current directory. Every supported install type has an
explicit, tested upgrade path:

* ``git`` / ``tag`` — a source checkout; upgrade fetches/rechecks out to the
  latest release and syncs the workspace.
* ``archive`` — a tarball extract; upgrade re-downloads, verifies, and swaps
  the tree while preserving ``.env``.
* ``package`` — the ``maistro`` CLI installed via ``uv tool``; upgrade runs
  ``uv tool upgrade``.
* ``container`` — a containerized stack; upgrade pulls the pinned images and
  restarts.

Unsupported combinations fail with actionable instructions. The upgrade is
preflighted (config backup) and rolled back on any failure — it never reports
success over a failing step, never leaves the source tree checked out to a
half-revision, and never leaves a mixed set of running images.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import importlib.metadata as _metadata
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from typer import Typer

from maistro.cli._install_manifest import (
    MANIFEST_FILENAME,
    PLAN_SUBDIR,
    InstallManifest,
    current_version,
    detect_install_type,
    git_revision,
    image_references,
    locate_install_root,
    plan_dir_for_root,
    write_manifest,
)
from maistro.security.warden.sanitizer import strip_terminal_escapes

app = Typer(help="Upgrade maistro to the latest version.")
console = Console()

# The subprocess boundary. The upgrade driver only ever talks to git / uv /
# docker / curl / tar through this one symbol, so tests substitute a fake and
# assert the exact command vocabulary without spawning anything real.
_RUN_SUBPROCESS = subprocess.run

#: Where ``maistro upgrade`` looks if it cannot find a source checkout — the
#: home of a packaged (uv-tool) or containerized install.
_PACKAGED_MANIFEST = Path("~/.maistro").expanduser() / MANIFEST_FILENAME


# Readiness polling. Mirrors the installer (get.sh/install.sh): after
# `compose up -d` the API needs a normal startup interval before /health/ready
# answers, so the probe retries with a bounded budget instead of treating the
# first failed request as an upgrade failure (which would roll back a healthy
# cutover).
_HEALTH_ATTEMPTS = 60
_HEALTH_RETRY_DELAY_S = 2.0


@dataclass
class _Cmd:
    """A single external command the upgrade driver may execute."""

    argv: list[str]
    cwd: str | None = None
    timeout: float = 180.0
    env: dict[str, str] | None = None
    # Transient-failure retries (readiness probes). 1 means run once.
    retries: int = 1
    retry_delay: float = 0.0


@dataclass
class _Outcome:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing: str | None = None


def _run_once(cmd: _Cmd) -> _Outcome:
    """Execute one command attempt, translating OS-level failures into an outcome."""
    try:
        cp = _RUN_SUBPROCESS(
            cmd.argv,
            cwd=cmd.cwd,
            env=cmd.env,
            capture_output=True,
            text=True,
            timeout=cmd.timeout,
            check=False,
        )
        return _Outcome(
            ok=cp.returncode == 0,
            stdout=cp.stdout or "",
            stderr=cp.stderr or "",
        )
    except FileNotFoundError as exc:
        return _Outcome(
            ok=False,
            stderr=f"{exc.filename or cmd.argv[0]}: command not found",
            missing=exc.filename,
        )
    except subprocess.TimeoutExpired as exc:
        return _Outcome(
            ok=False,
            stdout=_coerce(exc.stdout),
            stderr=_coerce(exc.stderr),
            timed_out=True,
        )


def _run(cmd: _Cmd) -> _Outcome:
    """Run a command, retrying transient failures up to ``cmd.retries`` times.

    Only successful outcomes are retried against; a missing executable is a
    permanent error and is surfaced immediately without further attempts.
    """
    attempts = max(1, cmd.retries)
    for attempt in range(1, attempts + 1):
        outcome = _run_once(cmd)
        if outcome.ok or outcome.missing is not None or attempt == attempts:
            return outcome
        time.sleep(cmd.retry_delay)
    return outcome  # pragma: no cover - loop always returns


def _coerce(value: bytes | str | None) -> str:
    """Normalize subprocess captured output to str (timeout partials may be bytes)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _run_sequence(steps: list[_Cmd]) -> _Outcome:
    """Run commands in order; stop and return the first failure."""
    outcome = _Outcome(ok=True)
    for step in steps:
        outcome = _run(step)
        if not outcome.ok:
            return outcome
    return outcome


class _UpgradeError(Exception):
    """A preflight or planning error that aborts before any external command."""


def _resolve_compose_runtime() -> list[str]:
    """The compose front-end to drive the stack with, as an argv prefix."""
    if shutil.which("docker") and shutil.which("podman"):
        # Prefer docker where both exist (most predictable image pinning).
        return ["docker", "compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    if shutil.which("podman"):
        return ["podman", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


def _read_env_port(root: Path) -> str:
    env = root / ".env"
    if not env.is_file():
        return "8000"
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("MAISTRO_PORT="):
            return line.split("=", 1)[1].strip()
    return "8000"


class _Upgrade:
    """Transactional upgrade driver for one install.

    The lifecycle is: preflight (backup) → per-type upgrade phases → verify →
    cutover → verify readiness → commit. Any phase failure runs ``rollback``
    and returns a non-zero exit code, never an implied success.
    """

    #: Extra tag under which the pre-``compose build`` images are retained so
    #: a post-cutover rollback can restore the previous release's images.
    _ROLLBACK_IMAGE_SUFFIX = "-pre-upgrade-rollback"

    def __init__(self, root: Path, manifest: InstallManifest, install_type: str) -> None:
        self.root = root
        self.manifest = manifest
        self.install_type = install_type
        # The installer may have materialized the plan outside the default
        # ``.maistro-install`` (--plan-dir); the manifest records where.
        self.plan_dir = plan_dir_for_root(root, manifest)
        self.backup_dir: Path | None = None
        self._cutover_attempted = False
        self._previous_revision: str | None = None
        self._compose = _resolve_compose_runtime()
        # Archive-swap bookkeeping: the previous release tree is retained as a
        # sibling until the upgrade commits, so any later failure can restore it.
        self._archive_old: Path | None = None
        self._archive_swapped = False

    # -- preflight / rollback -------------------------------------------------

    def preflight(self) -> None:
        """Validate the manifest describes an upgradeable install, before any mutation.

        Binary availability is NOT pre-checked here: a missing git/uv/docker
        surfaces as a ``command not found`` outcome on the offending phase,
        which triggers rollback just like any other failure. That keeps the
        command vocabulary in one place and stays honest on minimal test hosts
        where, e.g., docker is absent but image_pull compose files are still
        being validated. What IS checked up front is the manifest's own shape:
        an archive install without a source_url cannot be re-downloaded, and a
        container/package install without an image reference is not actionable.
        """
        if self.install_type == "archive" and not self.manifest.source_url:
            raise _UpgradeError(
                "Archive installs record no source_url, so `maistro upgrade` "
                "cannot re-fetch the archive. Re-install from the source archive "
                "with get.sh, or run `maistro upgrade` from a git checkout instead."
            )
        if self.install_type == "archive" and not self._archive_target_ref():
            raise _UpgradeError(
                "Archive installs must record the release ref (version) they were "
                "installed from, so `maistro upgrade` can compute the target. "
                "Re-install from the source archive with get.sh."
            )
        if self.install_type == "container" and not self._image_tag():
            raise _UpgradeError(
                "Container installs must record an image_tag to pull. Re-install "
                "so the install manifest pins ghcr.io/.../maistro-engine:<tag>, "
                "then re-run `maistro upgrade`."
            )

    def backup(self) -> None:
        """Snapshot operator config under a timestamped dir before any mutation.

        Only secret-bearing, operator-authored files are copied: ``.env`` and
        the wizard's plan dir (answers, compose override, manifest). The copy
        is local so rollback is a ``cp``, and never touches running containers.

        Package and container installs carry no in-repo operator config, so the
        step is skipped — their rollback is the image/service state itself.
        """
        if self.install_type in ("package", "container"):
            return
        if self.backup_dir is not None:
            return  # already backed up
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M%S")
        backup = self.plan_dir / "backup" / stamp
        backup.mkdir(parents=True, exist_ok=True)
        env_file = self.root / ".env"
        if env_file.is_file():
            shutil.copy2(env_file, backup / ".env")
        for name in ("install-answers.yaml", "compose.override.yml", MANIFEST_FILENAME):
            src = self.plan_dir / name
            if src.is_file():
                shutil.copy2(src, backup / name)
        self._previous_revision = _previous_revision(self.root, self.install_type)
        self.backup_dir = backup
        console.print(f"[dim]Preflight backup at {backup}[/dim]")

    def restore_config(self) -> None:
        """Best-effort restoration of the backed-up config files.

        The install root and plan dir are recreated if a failed archive swap
        left them absent — a rollback must complete its config restore even
        when the tree it is restoring into no longer exists.
        """
        if self.backup_dir is None or not self.backup_dir.is_dir():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.plan_dir.mkdir(parents=True, exist_ok=True)
        env_src = self.backup_dir / ".env"
        if env_src.is_file():
            shutil.copy2(env_src, self.root / ".env")
        for name in ("install-answers.yaml", "compose.override.yml", MANIFEST_FILENAME):
            src = self.backup_dir / name
            if src.is_file():
                shutil.copy2(src, self.plan_dir / name)

    def rollback(self) -> None:
        """Undo an interrupted upgrade to a consistent state.

        Config is restored from the preflight backup, source is rewound to the
        pre-upgrade revision (source installs), and — once a cutover has been
        attempted — the new containers are stopped and the previous image
        restarted. For source builds the previous image is the one snapshotted
        before ``compose build`` retagged the fixed local tags
        (``_image_snapshot_cmd``), restored here before ``up -d``. A failed
        ``compose up -d`` can still have recreated services, so any cutover
        attempt counts as touching the stack. The rollback is best-effort; the
        invariant is that the tree is left internally consistent, never
        half-upgraded.
        """
        console.print("[yellow]Rolling back upgrade...[/yellow]")
        if self._archive_swapped and self._archive_old is not None:
            # The previous release tree was retained by the swap; put it back.
            if self.root.exists():
                shutil.rmtree(self.root, ignore_errors=True)
            if self._archive_old.is_dir():
                _run(_Cmd(["mv", str(self._archive_old), str(self.root)]))
        self.restore_config()
        if self._cutover_attempted:
            _run_sequence(self._compose_cmds("down", "-t", "0"))
        self._rewind_source()
        self._restart_previous_stack()
        if self.backup_dir is not None:
            console.print(f"[dim]Backup retained at {self.backup_dir}[/dim]")

    def _rewind_source(self) -> None:
        """Point a source install back at its pre-upgrade revision."""
        if self._source_rewind_candidate() and self._previous_revision:
            _run(
                _Cmd(["git", "-C", str(self.root), "checkout", "--force", self._previous_revision])
            )

    def _restart_previous_stack(self) -> None:
        """Bring the stack back up on the previous release's artifacts.

        A no-op until a cutover has been attempted: before that boundary no
        phase has touched running containers, so there is nothing to restart.
        """
        if not self._cutover_attempted:
            return
        if self._builds_local_images():
            # `compose build` retagged the live image tags with the new
            # artifacts; restore the pre-upgrade snapshot so `up -d`
            # restarts the previous release, not the failed new one.
            _run(self._image_restore_cmd())
        _run_sequence(self._compose_cmds("up", "-d"))

    def _source_rewind_candidate(self) -> bool:
        return self.install_type in ("git", "tag", "archive")

    def _commit(self) -> None:
        """Drop the backup and the retained previous tree, then report success."""
        if self.backup_dir is not None:
            shutil.rmtree(self.backup_dir, ignore_errors=True)
        if self._archive_old is not None:
            shutil.rmtree(self._archive_old, ignore_errors=True)
        if self._builds_local_images():
            # Committed: the pre-upgrade image snapshot is no longer needed.
            _run(self._image_snapshot_cleanup_cmd())

    # -- command builders ------------------------------------------------------

    def _compose_args(self) -> list[str]:
        """The ``-f`` file list for the stack, anchored at the install root."""
        mode = self.manifest.delivery_mode or "source_build"
        install_compose = self.plan_dir / "compose.install.yml"
        if mode == "image_pull" and install_compose.is_file():
            return ["--project-directory", str(self.root), "-f", str(install_compose)]
        args = ["--project-directory", str(self.root), "-f", str(self.root / "docker-compose.yml")]
        override = self.plan_dir / "compose.override.yml"
        if override.is_file():
            args += ["-f", str(override)]
        return args

    def _compose_cmds(self, *service_args: str) -> list[_Cmd]:
        argv = [*self._compose, *self._compose_args(), *service_args]
        return [_Cmd(argv, cwd=str(self.root))]

    def _image_tag(self) -> str | None:
        return self.manifest.image_tag or os.environ.get("MAISTRO_IMAGE_TAG")

    def _version_probe(self) -> _Cmd:
        """One command whose success proves the running version matches the target."""
        if self.install_type == "archive":
            # Archive trees carry no .git; the manifest re-recorded inside the
            # swapped-in tree by _record_archive_manifest is the version proof.
            manifest_file = self.plan_dir / MANIFEST_FILENAME
            ref = self._archive_target_ref()
            return _Cmd(
                [
                    sys.executable,
                    "-c",
                    f"import json; assert json.load(open({str(manifest_file)!r}))"
                    f".get('version') == {ref!r}",
                ]
            )
        if self.install_type in ("git", "tag"):
            if self.install_type == "tag":
                return _Cmd(
                    ["git", "-C", str(self.root), "describe", "--tags", "--exact-match"],
                    cwd=str(self.root),
                )
            return _Cmd(["git", "-C", str(self.root), "rev-parse", "HEAD"], cwd=str(self.root))
        if self.install_type == "package":
            # The upgraded CLI tool itself; `uv tool upgrade` already re-pinned it.
            return _Cmd(["maistro", "--version"])
        # container: ask the running engine container for its in-image version.
        return _Cmd(
            [
                *self._compose,
                *self._compose_args(),
                "exec",
                "-T",
                "maistro-engine",
                "python",
                "-c",
                "import maistro; print(maistro.__version__)",
            ]
        )

    def _health_probe(self) -> _Cmd:
        """Bounded readiness poll, matching the installer's post-up wait."""
        port = _read_env_port(self.root)
        return _Cmd(
            ["curl", "-fsSL", f"http://127.0.0.1:{port}/health/ready"],
            cwd=str(self.root),
            retries=_HEALTH_ATTEMPTS,
            retry_delay=_HEALTH_RETRY_DELAY_S,
        )

    # -- phases, per install type ---------------------------------------------

    def source_cmds(self) -> list[_Cmd]:
        t = self.install_type
        if t == "git":
            return [
                _Cmd(["git", "-C", str(self.root), "fetch", "--all", "--tags"], cwd=str(self.root)),
                _Cmd(["git", "-C", str(self.root), "pull", "--ff-only"], cwd=str(self.root)),
            ]
        if t == "tag":
            # Resolve the newest fetched release independent of HEAD: HEAD is
            # detached at the previously installed tag, and `describe --tags`
            # only sees tags reachable from it, so it would re-resolve the old
            # release after the fetch and "upgrade" in place. for-each-ref
            # scans the whole ref namespace, so the just-fetched tags win.
            resolve = (
                "git -C "
                + shlex.quote(str(self.root))
                + " for-each-ref refs/tags/ --sort=-creatordate --count=1"
                + ' --format="%(refname:short)"'
            )
            return [
                _Cmd(
                    ["git", "-C", str(self.root), "fetch", "--tags", "--force"],
                    cwd=str(self.root),
                ),
                _Cmd(
                    [
                        "bash",
                        "-c",
                        f'tag="$({resolve})" && [ -n "$tag" ] '
                        f'&& git -C {shlex.quote(str(self.root))} checkout --force "$tag"',
                    ],
                    cwd=str(self.root),
                ),
            ]
        return []

    def _archive_target_ref(self) -> str:
        """The release ref this archive upgrade moves to (preflight-validated)."""
        return (self.manifest.version or self.manifest.ref or "").strip()

    def _archive_download_cmds(self) -> list[_Cmd]:
        """Re-download the archive for the target ref into a sibling temp dir.

        Everything here happens off to the side of the live install: a failure
        aborts with the current tree untouched. Stale temp/backup siblings from
        an interrupted earlier run are removed first so releases never mix.
        """
        url = (self.manifest.source_url or "").removesuffix(".git")
        ref = self._archive_target_ref()
        if not url or not ref:
            raise _UpgradeError(
                "Cannot upgrade an archive install without a source_url and a "
                "release ref in the install manifest. Re-install from the source "
                "archive with get.sh."
            )
        archive_url = f"{url.rstrip('/')}/archive/refs/tags/{ref}.tar.gz"
        work = self.root.with_name(self.root.name + ".upgrade-tmp")
        old = self.root.with_name(self.root.name + ".upgrade-old")
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        work.mkdir(parents=True)
        self._archive_old = old
        return [
            _Cmd(["curl", "-fsSL", archive_url, "-o", str(work / "archive.tar.gz")]),
            _Cmd(
                [
                    "tar",
                    "-xzf",
                    str(work / "archive.tar.gz"),
                    "-C",
                    str(work),
                    "--strip-components=1",
                ]
            ),
            _Cmd(
                [
                    "bash",
                    "-c",
                    # Carry operator credentials into the extracted tree so the
                    # swap inherits them. The old tree keeps its own .env for
                    # rollback.
                    f"cp {shlex.quote(str(self.root))}/.env {shlex.quote(str(work))}/ "
                    "2>/dev/null || true",
                ],
                cwd=str(self.root),
            ),
        ]

    def _archive_swap_cmds(self) -> list[_Cmd]:
        """Swap the extracted tree in via rename, retaining the previous release.

        Plain ``mv`` swaps (same filesystem — the siblings sit next to the
        root) replace the tree stepwise; ``rm -rf`` is never aimed at the live
        tree. The previous release is retained at ``<root>.upgrade-old`` until
        :meth:`_commit` so any later phase failure can roll the whole tree
        back, and the operator's plan directory is carried into the
        swapped-in tree so the durable manifest survives.
        """
        work = self.root.with_name(self.root.name + ".upgrade-tmp")
        old = self._archive_old or self.root.with_name(self.root.name + ".upgrade-old")
        self._archive_old = old
        q_root, q_work, q_old = (
            shlex.quote(str(self.root)),
            shlex.quote(str(work)),
            shlex.quote(str(old)),
        )
        # The plan directory lives under the (now renamed) previous root until
        # the copy below; honor a custom --plan-dir recorded in the manifest.
        try:
            plan_rel = self.plan_dir.relative_to(self.root)
        except ValueError:
            plan_rel = Path(self.plan_dir.name)
        q_plan = shlex.quote(str(old / plan_rel))
        return [
            _Cmd(
                [
                    "bash",
                    "-c",
                    # If either rename fails, put the previous tree back and
                    # fail: the root path is never left dangling or half-filled.
                    f"if mv {q_root} {q_old}; then "
                    f"if mv {q_work} {q_root}; then "
                    f"cp -a {q_plan} {q_root}/ 2>/dev/null || true; "
                    f"else mv {q_old} {q_root}; exit 1; fi; "
                    "else exit 1; fi",
                ],
                cwd=str(self.root.parent),
            ),
        ]

    def _record_archive_manifest(self) -> None:
        """Re-record the install manifest inside the swapped-in tree.

        The swap carried the old plan directory across; its version/ref still
        name the previous release. Update them so the durable metadata names
        what is actually on disk (the version-readiness probe reads this).
        """
        ref = self._archive_target_ref()
        self.manifest.version = ref
        self.manifest.ref = ref
        self.manifest.revision = None  # archive trees carry no git metadata
        # Non-fatal: the swapped tree itself is the release proof; the
        # readiness probe below fails honestly if the file cannot be written.
        # Write into the plan directory the probe reads, and keep the canonical
        # discovery pointer current when the two differ (--plan-dir installs).
        with contextlib.suppress(OSError):
            self.plan_dir.mkdir(parents=True, exist_ok=True)
            (self.plan_dir / MANIFEST_FILENAME).write_text(
                json.dumps(self.manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if self.plan_dir != self.root / PLAN_SUBDIR:
                write_manifest(self.root, self.manifest)

    def sync_cmds(self) -> list[_Cmd]:
        return [_Cmd(["uv", "sync", "--all-extras"], cwd=str(self.root))]

    def _builds_local_images(self) -> bool:
        """True when artifacts come from ``compose build`` under fixed local image tags."""
        if self.install_type in ("container", "package"):
            return False
        return (self.manifest.delivery_mode or "source_build") != "image_pull"

    def _image_snapshot_cmd(self) -> _Cmd:
        """Retag the currently deployed images onto rollback tags before ``compose build``.

        A source build retags the fixed local image tags with the newly built
        artifacts. Without this snapshot, a post-cutover rollback (``down`` +
        ``up -d``) would restart the NEW images instead of the previous
        release. Best-effort: on a first install there is nothing to snapshot,
        and per-image failures never block the upgrade.
        """
        compose = " ".join(shlex.quote(a) for a in [*self._compose, *self._compose_args()])
        engine = shlex.quote(self._compose[0])
        sfx = self._ROLLBACK_IMAGE_SUFFIX
        script = (
            f"for img in $({compose} config --images); do "
            f'{engine} tag "$img" "${{img}}{sfx}" 2>/dev/null || true; done; exit 0'
        )
        return _Cmd(["bash", "-c", script], cwd=str(self.root))

    def _image_restore_cmd(self) -> _Cmd:
        """Retag the pre-upgrade snapshot back onto the live tags (rollback path)."""
        compose = " ".join(shlex.quote(a) for a in [*self._compose, *self._compose_args()])
        engine = shlex.quote(self._compose[0])
        sfx = self._ROLLBACK_IMAGE_SUFFIX
        script = (
            f"for img in $({compose} config --images); do "
            f'old="${{img}}{sfx}"; '
            f'if {engine} image inspect "$old" >/dev/null 2>&1; then '
            f'{engine} tag "$old" "$img" 2>/dev/null || true; '
            f'{engine} rmi "$old" >/dev/null 2>&1 || true; fi; done; exit 0'
        )
        return _Cmd(["bash", "-c", script], cwd=str(self.root))

    def _image_snapshot_cleanup_cmd(self) -> _Cmd:
        """Drop the rollback tags once the upgrade has committed."""
        compose = " ".join(shlex.quote(a) for a in [*self._compose, *self._compose_args()])
        engine = shlex.quote(self._compose[0])
        sfx = self._ROLLBACK_IMAGE_SUFFIX
        script = (
            f"for img in $({compose} config --images); do "
            f'{engine} rmi "${{img}}{sfx}" >/dev/null 2>&1 || true; done; exit 0'
        )
        return _Cmd(["bash", "-c", script], cwd=str(self.root))

    def build_cmds(self) -> list[_Cmd]:
        """Rebuild (source) or pull (image_pull / container) the new artifacts BEFORE cutover."""
        if self.install_type == "container":
            return self._compose_cmds("pull")
        mode = self.manifest.delivery_mode or "source_build"
        if mode == "image_pull":
            return self._compose_cmds("pull")
        # `compose build --pull` is a boolean flag (always refresh base
        # images); plain `build` rebuilds the services from the upgraded tree.
        # The snapshot runs first so the pre-upgrade images survive the
        # retagging and the advertised rollback can actually restore them.
        return [self._image_snapshot_cmd(), *self._compose_cmds("build")]

    def verify_assets_cmds(self) -> list[_Cmd]:
        """Confirm the rebuilt/pulled images are present and correctly tagged.

        For image-based installs (image_pull / container) a ``docker inspect``
        on each pinned service reference proves the registry actually holds the
        target digest — build/pull succeeding only means the local engine
        accepted the request, not that the right bits landed. For source
        builds the local images are validated with ``compose images``.
        """
        tag = self._image_tag()
        mode = self.manifest.delivery_mode or "source_build"
        if self.install_type == "container" or mode == "image_pull":
            refs = image_references(tag or "latest")
            runtime = self._compose[0]
            return [_Cmd([runtime, "inspect", ref]) for ref in refs.values()]
        return self._compose_cmds("images")

    def cutover_cmds(self) -> list[_Cmd]:
        if self.install_type == "package":
            return [_Cmd(["uv", "tool", "upgrade", "maistro-core"])]
        return self._compose_cmds("up", "-d")

    def readiness_cmds(self) -> list[_Cmd]:
        """Post-cutover proof that the running artifacts match the target release."""
        if self.install_type in ("git", "tag", "archive"):
            return [self._health_probe(), self._version_probe()]
        if self.install_type == "package":
            return [self._version_probe()]
        if self.install_type == "container":
            return [self._health_probe(), self._version_probe()]
        return []

    def phases(self) -> list[tuple[str, list[_Cmd]]]:
        """The ordered, named phases for this install type.

        Each phase is run in full before the next starts; a failure in any
        phase triggers ``rollback`` and aborts. The cutover phase is the
        boundary — nothing before it touches running containers.
        """
        if self.install_type == "archive":
            return [
                ("download-archive", self._archive_download_cmds()),
                ("swap-tree", self._archive_swap_cmds()),
                ("sync-deps", self.sync_cmds()),
                ("build-artifacts", self.build_cmds()),
                ("verify-assets", self.verify_assets_cmds()),
                ("cutover", self.cutover_cmds()),
                ("verify-readiness", self.readiness_cmds()),
            ]
        if self.install_type in ("git", "tag"):
            return [
                ("update-source", self.source_cmds()),
                ("sync-deps", self.sync_cmds()),
                ("build-artifacts", self.build_cmds()),
                ("verify-assets", self.verify_assets_cmds()),
                ("cutover", self.cutover_cmds()),
                ("verify-readiness", self.readiness_cmds()),
            ]
        if self.install_type == "package":
            return [
                ("cutover", self.cutover_cmds()),
                ("verify-readiness", self.readiness_cmds()),
            ]
        if self.install_type == "container":
            return [
                ("build-artifacts", self.build_cmds()),
                ("verify-assets", self.verify_assets_cmds()),
                ("cutover", self.cutover_cmds()),
                ("verify-readiness", self.readiness_cmds()),
            ]
        return []

    # -- orchestration --------------------------------------------------------

    def run(self) -> int:
        try:
            self.preflight()
            self.backup()
        except (_UpgradeError, OSError) as exc:
            console.print(f"[red]Preflight failed: {exc}. No changes were made.[/red]")
            return 1

        for name, cmds in self.phases():
            outcome = _run_sequence(cmds)
            if name == "cutover":
                # Cutover is the first phase that touches running containers;
                # a failed `compose up -d` may still have recreated services,
                # so rollback must run from the first attempt, success or not.
                self._cutover_attempted = True
            if name == "swap-tree" and outcome.ok:
                self._archive_swapped = True
                self._record_archive_manifest()
            if not outcome.ok:
                detail = strip_terminal_escapes((outcome.stderr or outcome.stdout).strip())
                console.print(f"[red]Upgrade failed during '{name}': {detail}[/red]")
                self.rollback()
                return 1

        self._commit()
        self._report_success()
        return 0

    def _report_success(self) -> None:
        version = current_version() or "(unknown)"
        tag = self._image_tag()
        image = f", image tag {tag}" if tag else ""
        console.print(
            f"[green]Upgrade complete: {self.install_type} install at {self.root} "
            f"(version {version}{image}).[/green]"
        )
        if self._source_rewind_candidate():
            rev = git_revision(self.root)
            if rev:
                console.print(f"[dim]source revision {rev}[/dim]")


def _previous_revision(root: Path, install_type: str) -> str | None:
    """The revision to rewind to on rollback (the pre-upgrade HEAD for source installs)."""
    if install_type not in ("git", "tag"):
        return None
    return git_revision(root)


def _looks_like_checkout(path: Path) -> bool:
    return (path / "docker-compose.yml").is_file() or (path.parent / "pyproject.toml").is_file()


def _detect_packaged_or_container() -> tuple[str | None, Path | None, InstallManifest | None]:
    """Fallback for installs that left no source checkout (package / container).

    Reads the manifest ``~/.maistro/install-manifest.json`` written by a
    packaged or containerized install. If even that is absent, the CLI probes
    its own provenance: a booted container is detected via ``/.dockerenv`` or
    ``MAISTRO_CONTAINER``; an importable ``maistro-core`` that does not sit in a
    checkout becomes a ``package`` install.
    """
    if _PACKAGED_MANIFEST.is_file():
        try:
            data = json.loads(_PACKAGED_MANIFEST.read_text(encoding="utf-8"))
            manifest = InstallManifest.model_validate(data)
        except (OSError, ValueError):
            return None, None, None
        root = Path(manifest.install_root).expanduser().resolve() if manifest.install_root else None
        return manifest.install_type, root, manifest
    if Path("/.dockerenv").exists() or os.environ.get("MAISTRO_CONTAINER") == "1":
        root = Path("/maistro-engine")
        manifest = InstallManifest(
            install_type="container", install_root=str(root), install_surface="container"
        )
        return "container", root, manifest
    try:
        from importlib.metadata import distribution

        dist = distribution("maistro-core")
        here = Path(str(dist.locate_file(""))).resolve()
        if here and not _looks_like_checkout(here):
            root = here
            manifest = InstallManifest(
                install_type="package", install_root=str(root), install_surface="package"
            )
            return "package", root, manifest
    except _metadata.PackageNotFoundError:
        return None, None, None
    return None, None, None


def _unsupported_instructions(kind: str | None) -> str:
    """Actionable next steps for an install type ``maistro upgrade`` cannot handle."""
    if kind is None:
        return (
            "maistro could not find an install: no source checkout, packaged "
            "CLI, or container was detected, and there is no install manifest.\n"
            "Set MAISTRO_REPO_ROOT to a maistro-engine checkout, or re-run the "
            "installer (get.sh) so an install manifest is recorded."
        )
    return (
        f"maistro could not determine how this install (type={kind}) was "
        "installed. Re-install with get.sh, or pin this install type with an "
        "~/.maistro/install-manifest.json recording install_type, install_root, "
        "and image_tag, then re-run `maistro upgrade`."
    )


def _resolve_target() -> tuple[Path, InstallManifest, str] | None:
    """Resolve the upgrade target from durable metadata, never the caller's CWD.

    Returns ``(root, manifest, install_type)``, or ``None`` when no supported
    install can be resolved — the caller turns that into the actionable
    "could not find an install" error. Durable manifests win over tree
    detection, which wins over the packaged/container fallback.
    """
    root, manifest = locate_install_root()
    if manifest is not None and root is not None:
        # A manifest always lands with its root; the pair is the authoritative
        # identity of this install.
        return root, manifest, manifest.install_type
    if root is not None:
        # A checkout found by the parent walk that never recorded a manifest:
        # detect the install type from the tree itself and record what was
        # learned in an in-memory manifest. Writing durable metadata stays the
        # installer's job — upgrade must not mutate the tree before preflight.
        detected = detect_install_type(root)
        if detected is not None:
            return (
                root,
                InstallManifest(
                    install_type=detected,
                    install_root=str(root),
                    install_surface="checkout",
                    revision=git_revision(root),
                ),
                detected,
            )
    # No source manifest and no checkout shape: try package / container.
    kind, pkg_root, pkg_manifest = _detect_packaged_or_container()
    if kind and pkg_root is not None and pkg_manifest is not None:
        return pkg_root, pkg_manifest, kind
    console.print(f"[red]{_unsupported_instructions(kind)}[/red]")
    return None


@app.callback(invoke_without_command=True)
def upgrade_main() -> None:
    """Pull the latest updates for this install, preserving operator config."""
    console.print("[bold]maistro upgrade[/bold]")

    target = _resolve_target()
    if target is None:
        sys.exit(1)
    root, manifest, install_type = target

    if install_type not in ("git", "tag", "archive", "package", "container"):
        console.print(f"[red]{_unsupported_instructions(install_type)}[/red]")
        sys.exit(1)

    code = _Upgrade(root, manifest, install_type).run()
    if code != 0:
        sys.exit(code)
