"""ADR-093 sandbox: run the agent's edits and commands inside a container.

`LocalWorktreeSandbox` operates on the host filesystem — fine for trusted use,
but ADR-093 mandates hardware-VM-class isolation for *untrusted agent code*
(the architecture-fit judge flagged the local path as violating it). This is the
Docker-backed implementation ADR-093 names as satisfying the isolation contract
today (Firecracker/E2B/gVisor remain an open backend choice): the repo is copied
into an ephemeral container and every read/write/edit/command the agent issues
runs *there*, so agent-controlled code never executes against the host.

Same `BuilderSandbox` protocol as the local sandbox, so it's a drop-in — the
agent loop and TUI don't change. Sync the container's work back to the host with
`sync_to_host()` when a caller (e.g. the RSI loop) needs to commit the result.

Talks to Docker through the `docker` CLI with argv lists (no shell on the host),
so it stays synchronous like the rest of the builder sandbox interface.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from maistro_bootstrap.builders.errors import SandboxEscapeError

DEFAULT_IMAGE = "maistro-builders:latest"
_WORKDIR = "/workspace"
_DEFAULT_TIMEOUT = 120
# Hardening for the ephemeral container: the agent has a shell inside it, so
# these are the boundary that actually matters (never trust the untrusted
# side to self-limit). Values mirror maistro.tools.sandbox.docker's
# SandboxSettings defaults, sized up since builder runs (installs, test
# suites) are heavier than a single code-exec call.
_MEMORY_LIMIT = "2g"
_PIDS_LIMIT = "512"


def _docker(
    args: list[str],
    *,
    stdin: str | None = None,
    check: bool = True,
    timeout: int = _DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["docker", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc


class ContainerBuilderSandbox:
    """A `BuilderSandbox` whose operations execute inside an ephemeral container.

    Use as a context manager: entering creates the container and copies the repo
    in; exiting force-removes the container (nothing persists). The host repo is
    only read once (to seed the container) and only written by an explicit
    `sync_to_host()` — the agent itself never touches it.
    """

    def __init__(self, repo_root: Path, *, image: str = DEFAULT_IMAGE) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._image = image
        self._cid: str | None = None

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> ContainerBuilderSandbox:
        cid = _docker(
            [
                "run",
                "-d",
                "--workdir",
                _WORKDIR,
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                f"--memory={_MEMORY_LIMIT}",
                f"--pids-limit={_PIDS_LIMIT}",
                self._image,
                "sleep",
                "infinity",
            ]
        ).stdout.strip()
        self._cid = cid
        # Copy the repo *into* the container (no host bind-mount → isolation).
        _docker(["cp", f"{self._repo_root}/.", f"{cid}:{_WORKDIR}"])
        return self

    def __exit__(self, *exc: object) -> None:
        if self._cid:
            _docker(["rm", "-f", self._cid], check=False)
            self._cid = None

    def sync_to_host(self, dest: Path | None = None) -> None:
        """Copy the container workspace back to the host, EXCLUDING ``.git``.

        The agent has shell access inside the container (root, in fact), so a
        plain ``docker cp`` of the whole workspace would let it corrupt
        refs/config/hooks that the caller then runs host-side git against —
        defeating the isolation. The container-side ``--exclude`` below is
        only a courtesy: it runs as root *inside* the untrusted container, so
        an attacker who controls that container can simply not honor it. The
        exclude that actually matters is the host-side one, applied while
        extracting — that's the real trust boundary. ``--no-same-owner`` on
        the extract also stops the container's root-owned files from landing
        on the host owned by root.
        """
        target = Path(dest) if dest is not None else self._repo_root
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(
            [
                "docker",
                "exec",
                self._require_cid(),
                "tar",
                "cf",
                "-",
                "--exclude=./.git",
                "-C",
                _WORKDIR,
                ".",
            ],
            capture_output=True,
            timeout=_DEFAULT_TIMEOUT,
        )
        if archive.returncode != 0:
            raise RuntimeError(
                f"container tar failed: {archive.stderr.decode(errors='replace')[:300]}"
            )
        extract = subprocess.run(
            [
                "tar",
                "xf",
                "-",
                "-C",
                str(target),
                "--exclude=./.git",
                "--no-same-owner",
            ],
            input=archive.stdout,
            capture_output=True,
            timeout=_DEFAULT_TIMEOUT,
        )
        if extract.returncode != 0:
            raise RuntimeError(
                f"host tar extract failed: {extract.stderr.decode(errors='replace')[:300]}"
            )

    # -- helpers -------------------------------------------------------------

    def _require_cid(self) -> str:
        if self._cid is None:
            raise RuntimeError("ContainerBuilderSandbox used outside its context manager")
        return self._cid

    def _safe(self, path: str) -> str:
        p = PurePosixPath(path.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts:
            raise SandboxEscapeError(f"Path {path!r} escapes sandbox root")
        return f"{_WORKDIR}/{p.as_posix()}"

    def _exec(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> tuple[int, str]:
        proc = subprocess.run(
            ["docker", "exec", self._require_cid(), *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    # -- BuilderSandbox protocol --------------------------------------------

    def read_file(self, path: str) -> str:
        rc, out = self._exec(["cat", self._safe(path)])
        if rc != 0:
            raise FileNotFoundError(path)
        return out

    def write_file(self, path: str, content: str) -> None:
        target = self._safe(path)
        parent = str(PurePosixPath(target).parent)
        _docker(["exec", self._require_cid(), "mkdir", "-p", parent])
        _docker(
            ["exec", "-i", self._require_cid(), "sh", "-c", f"cat > {_sh_quote(target)}"],
            stdin=content,
        )

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        text = self.read_file(path)
        count = text.count(old_string)
        if count == 0:
            raise ValueError(
                f"old_string not found in {path!r} — it must match the file exactly, "
                "including whitespace. Re-read the file and copy the exact text."
            )
        if count > 1:
            raise ValueError(
                f"old_string appears {count} times in {path!r} — include more surrounding "
                "context so it matches exactly one location."
            )
        self.write_file(path, text.replace(old_string, new_string, 1))
        return f"edited {path} (1 replacement)"

    def run_command(self, cmd: str, *, timeout: int = _DEFAULT_TIMEOUT) -> str:
        # Shell runs *inside* the container — the container is the trust boundary.
        _, out = self._exec(["sh", "-c", cmd], timeout=timeout)
        return out

    def run_argv(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> str:
        _, out = self._exec(argv, timeout=timeout)
        return out

    def diff(self) -> str:
        _, out = self._exec(["git", "-C", _WORKDIR, "diff"])
        return out

    def search(self, pattern: str, *, glob: str = "**/*.py") -> list[str]:
        include = glob.rsplit("/", 1)[-1] or "*"
        _rc, out = self._exec(["grep", "-rl", "--include", include, "-e", pattern, _WORKDIR])
        prefix = f"{_WORKDIR}/"
        return [
            line[len(prefix) :] if line.startswith(prefix) else line
            for line in out.splitlines()
            if line.strip()
        ]


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
