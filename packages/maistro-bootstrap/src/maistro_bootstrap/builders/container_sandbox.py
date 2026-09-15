"""ADR-093 sandbox: run the agent's edits and commands inside a container.

`LocalWorktreeSandbox` operates on the host filesystem — fine for trusted use,
but ADR-093 mandates hardware-VM-class isolation for *untrusted agent code*
(the architecture-fit judge flagged the local path as violating it). This is the
transitional Docker-backed Builder backend behind the isolation seam. It provides
Tier-3-style defense in depth for the supervised Builder path; it is not a
hardware-VM or user-space-kernel boundary for hostile autonomous workloads
(ADR-093). The repo's working
tree is seeded into an ephemeral container (minus a credential denylist — see
`_SEED_EXCLUDES`) and every read/write/edit/command the agent issues runs
*there*, so agent-controlled code never executes against the host.

Same `BuilderSandbox` protocol as the local sandbox, so it's a drop-in — the
agent loop and TUI don't change. Sync the container's work back to the host with
`sync_to_host()` when a caller (e.g. the RSI loop) needs to commit the result.

Talks to Docker through the `docker` CLI with argv lists (no shell on the host),
so it stays synchronous like the rest of the builder sandbox interface.

Network posture (#77): the container is created with `--network=none`, so an
unattended candidate has *no* egress by default — external, DNS, link-local
(incl. cloud metadata), and private-network paths all fail, because the only
interface inside the netns is loopback. There is deliberately no constructor
parameter to relax this: any egress grant belongs to the policy/Binding layer
(#18), granted explicitly and audited there — not to a sandbox flag candidate
influence could reach. The policy lives in the container's create-time config,
so it survives restarts and cannot be widened from inside: the candidate runs
as an unprivileged uid with `cap-drop=ALL`, no Docker socket is mounted, and
`no-new-privileges` blocks setuid paths; the one bootstrap exec that needs root
(`chown` of the empty workspace, before any candidate code or repo content
exists) is explicit and auditable below.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
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
_WORKSPACE_TMPFS = "size=2g,rw,nosuid,nodev"
_TMP_TMPFS = "size=512m,rw,nosuid,nodev"
_BASELINE_DIR = "/tmp/.maistro-baseline"

# Every command that can run candidate-influenced code executes as this
# unprivileged identity (#77: the sandbox used to run the agent as container
# root). A numeric uid:gid works in any image — no passwd entry is needed —
# and is deliberately not 0. Container PID 1 is `sleep infinity` (harness
# code, not candidate code) and also runs as this user via `--user`.
_AGENT_UID_GID = "65532:65532"
_AGENT_HOME = "/tmp"  # 1777 in the base images; outside the synced workspace

# The seed is a positive allowlist (#77/#78): only files tracked by the
# worktree's Git index are archived. This prevents an independently-created
# untracked host file with an application-specific name from crossing the
# boundary. The explicit exclusions remain a second layer for credential-shaped
# paths that were accidentally committed. Both are applied HOST-side when the
# seed archive is built — the trust boundary — never container-side.
# Pattern semantics verified identical on GNU tar 1.35 and bsdtar 3.5.3 (so
# macOS hosts and Linux CI behave the same): patterns prefixed `./` are exact
# root-relative paths; bare names (`.env`, `id_rsa`, `.ssh`) and bare
# `*.ext` patterns match at ANY depth.
_SEED_EXCLUDES = (
    # No host VCS metadata crosses the boundary. Besides credentials in config,
    # refs and hooks are host-authored control data. A sanitized baseline used
    # by the builder's git tools is created separately inside /tmp.
    "./.git",
    ".git",  # nested submodule metadata is ambient host control data too.
    # dotenv secrets (including environment-specific variants), at any depth.
    # Do not rely on callers to distinguish `.env.example` from a production
    # variant: a host-side seed is a credential boundary, so all variants stay
    # out of the untrusted workspace.
    ".env",
    ".env.*",
    ".envrc",
    # Ambient credential directories and registry logins, at any depth. A
    # directory named `secrets` is deliberately excluded wholesale: filenames
    # inside it are application-specific and cannot be safely identified by
    # extension (for example, `production-token.txt`).
    ".ssh",
    ".aws",
    ".gnupg",
    ".docker",
    ".npmrc",
    ".netrc",
    "_netrc",
    "secrets",
    # bare key material, at any depth.
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
)
_SEED_TIMEOUT = 300  # Git listing + tar create/extract through one pipe.
_PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
# A candidate can use setsid/double-fork to escape timeout's process group.
# Reap every non-harness process owned by the agent after each exec, including
# successful commands, so background work cannot outlive the command boundary.
_REAP_AGENT_PROCESSES = (
    "self=$$; harness=__MAISTRO_HARNESS_PID__; "
    "for pass in 1 2 3; do "
    "for pid in $(ps -eo pid=,uid= | "
    "awk -v self=$self -v harness=$harness "
    "'$2 == 65532 && $1 != 1 && $1 != self && $1 != harness {print $1}'); do "
    "kill -KILL $pid 2>/dev/null || true; "
    "done; "
    "sleep 0.01; "
    "done"
)


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

    Use as a context manager: entering creates the container and seeds it with
    the tracked, credential-filtered working tree; exiting force-removes the container
    (nothing persists). The host repo is only read once (to seed the container)
    and only written by an explicit `sync_to_host()` — the agent itself never
    touches it. Every command the agent can reach runs as `_AGENT_UID_GID`
    inside a `--network=none` container (#77).
    """

    def __init__(self, repo_root: Path, *, image: str = DEFAULT_IMAGE) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._image = image
        self._cid: str | None = None
        self._harness_pid: str | None = None

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> ContainerBuilderSandbox:
        try:
            cid = _docker(
                [
                    "run",
                    "-d",
                    "--init",
                    "--workdir",
                    _WORKDIR,
                    # Default-deny egress (#77): no interface beyond loopback, so
                    # external, DNS, link-local and private paths all fail.
                    "--network=none",
                    # A read-only image root leaves only the explicit workspace
                    # and scratch tmpfs mounts writable. Candidate code cannot
                    # turn an image path into durable host state.
                    "--read-only",
                    "--tmpfs",
                    f"{_WORKDIR}:{_WORKSPACE_TMPFS}",
                    "--tmpfs",
                    f"/tmp:{_TMP_TMPFS}",
                    # Nobody in this container runs as root -- not PID 1, not any
                    # exec -- and no capability survives the drop (CHOWN returns
                    # solely for the one-shot root bootstrap below; caps granted
                    # to uid 0 cannot be exercised by the agent's uid).
                    "--user",
                    _AGENT_UID_GID,
                    "--cap-drop=ALL",
                    "--cap-add=CHOWN",
                    "--security-opt=no-new-privileges",
                    f"--memory={_MEMORY_LIMIT}",
                    # Prevent the runtime's default swap allowance from turning
                    # the memory budget into a soft hint.
                    f"--memory-swap={_MEMORY_LIMIT}",
                    f"--pids-limit={_PIDS_LIMIT}",
                    "-e",
                    f"HOME={_AGENT_HOME}",
                    # Docker clients can inject proxy configuration from
                    # ~/.docker/config.json. Explicitly blank every spelling
                    # so credentials in that config cannot reach the candidate.
                    *[arg for name in _PROXY_ENV_NAMES for arg in ("-e", f"{name}=")],
                    self._image,
                    "sleep",
                    "infinity",
                ]
            ).stdout.strip()
            self._cid = cid
            self._harness_pid = self._find_harness_pid(cid)
            # One explicit, auditable root exec: make the (empty) workspace
            # writable by the agent uid. Runs before any repo content or candidate
            # code exists; everything after this is unprivileged.
            _docker(
                [
                    "exec",
                    "-u",
                    "0:0",
                    cid,
                    "chown",
                    _AGENT_UID_GID,
                    _WORKDIR,
                ]
            )
            self._seed(cid)
            return self
        except BaseException:
            # A failed bootstrap must not leave a live container behind. This is
            # also important when the seed tar or image fails halfway through.
            self.__exit__(None, None, None)
            raise

    def _find_harness_pid(self, cid: str) -> str:
        """Identify the fixed ``sleep infinity`` child created with the sandbox.

        ``--init`` adds a tiny PID 1, so the harness command is a separate
        process that must survive agent-process reaping. Capture its PID before
        any candidate code or repo content exists; candidates cannot spoof this
        startup identity later.
        """
        proc = _docker(
            [
                *self._exec_prefix(),
                cid,
                "ps",
                "-eo",
                "pid=,ppid=,args=",
            ],
            check=False,
            timeout=10,
        )
        for line in proc.stdout.splitlines():
            fields = line.strip().split(maxsplit=2)
            if (
                len(fields) == 3
                and fields[1] == "1"
                and fields[2] == "sleep infinity"
                and fields[0].isdigit()
            ):
                return fields[0]
        raise RuntimeError("sandbox harness process is missing")

    def _seed(self, cid: str) -> None:
        """Seed only indexed worktree files, excluding credential-shaped paths.

        The file list and archive are built HOST-side (the trust boundary — an
        inside-the-container filter would run as the party being contained) and
        extracted *as the agent uid*, so every seeded file is owned by the
        unprivileged user from the start. Untracked files are intentionally not
        seeded: candidate-created files appear in the container after startup,
        while ambient host files need an explicit, trusted Git-index decision.
        """
        tracked = self._tracked_seed_files()
        archive = subprocess.run(
            [
                "tar",
                "-cf",
                "-",
                *[f"--exclude={pattern}" for pattern in _SEED_EXCLUDES],
                "-C",
                str(self._repo_root),
                "--null",
                "--verbatim-files-from",
                "--files-from=-",
            ],
            input=tracked,
            capture_output=True,
            timeout=_SEED_TIMEOUT,
            env={**os.environ, "COPYFILE_DISABLE": "1"},
        )
        if archive.returncode != 0:
            self.__exit__(None, None, None)
            raise RuntimeError(f"seed tar failed: {archive.stderr.decode(errors='replace')[:300]}")
        extract = self._extract_seed(cid, archive.stdout, _WORKDIR)
        if extract.returncode != 0:
            self.__exit__(None, None, None)
            raise RuntimeError(
                f"container tar extract failed: {extract.stderr.decode(errors='replace')[:300]}"
            )
        # Keep a clean, in-container git index for the builder's status/diff
        # tools without importing the host's .git directory. It lives on the
        # scratch tmpfs and is never synced back to the host.
        baseline = self._extract_seed(cid, archive.stdout, _BASELINE_DIR)
        if baseline.returncode != 0:
            self.__exit__(None, None, None)
            raise RuntimeError(
                f"container baseline extract failed: {baseline.stderr.decode(errors='replace')[:300]}"
            )
        _docker(
            [
                *self._exec_prefix(),
                cid,
                "sh",
                "-c",
                (
                    f"git -C {_sh_quote(_BASELINE_DIR)} init -q && "
                    f"git -C {_sh_quote(_BASELINE_DIR)} add -A && "
                    f"git -C {_sh_quote(_BASELINE_DIR)} -c user.name=maistro "
                    f"-c user.email=maistro@localhost commit -qm seed"
                ),
            ]
        )

    def _git_index_path(self) -> Path:
        """Locate the worktree index without asking Git to parse its config."""
        git_marker = self._repo_root / ".git"
        if git_marker.is_dir():
            index_path = git_marker / "index"
        elif git_marker.is_file():
            marker = git_marker.read_text(encoding="utf-8").strip()
            if not marker.startswith("gitdir:"):
                raise RuntimeError(".git is not a valid worktree gitdir marker")
            gitdir = Path(marker.removeprefix("gitdir:").strip())
            index_path = (
                self._repo_root / gitdir if not gitdir.is_absolute() else gitdir
            ) / "index"
        else:
            raise RuntimeError("sandbox seed requires a Git worktree with an index")
        if not index_path.is_file():
            raise RuntimeError(f"sandbox Git index is missing: {index_path}")
        return index_path

    def _list_indexed_paths(self, index_path: Path) -> bytes:
        """List staged index entries without allowing the host config to run.

        The ``--stage`` metadata is needed to distinguish a tracked submodule
        (mode 160000) from an ordinary directory. Passing a gitlink to tar as a
        path makes tar recurse through the submodule checkout and defeats the
        indexed-file allowlist.

        Use the index in its original Git directory rather than copying it into
        a temporary repository. Split indexes keep their shared index beside the
        primary index, so copying only the primary file makes ``ls-files`` fail
        before the seed archive is created.
        """
        isolated_env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_INDEX_FILE": str(index_path.resolve()),
            # Listing must not create an index lock or otherwise mutate the
            # caller's worktree while the sandbox is being bootstrapped.
            "GIT_OPTIONAL_LOCKS": "0",
        }
        with tempfile.TemporaryDirectory(prefix="maistro-seed-index-") as isolated_git:
            initialized = subprocess.run(
                ["git", "init", "--bare", "--template=/dev/null", "-q", isolated_git],
                capture_output=True,
                timeout=_SEED_TIMEOUT,
                env=isolated_env,
            )
            if initialized.returncode != 0:
                raise RuntimeError(
                    f"temporary Git index setup failed: "
                    f"{initialized.stderr.decode(errors='replace')[:300]}"
                )
            listed = subprocess.run(
                [
                    "git",
                    "--git-dir",
                    isolated_git,
                    "--work-tree",
                    str(self._repo_root),
                    "-c",
                    "core.fsmonitor=false",
                    "ls-files",
                    "--cached",
                    "--stage",
                    "-z",
                ],
                capture_output=True,
                timeout=_SEED_TIMEOUT,
                env=isolated_env,
            )
            if listed.returncode != 0:
                raise RuntimeError(
                    f"git seed listing failed: {listed.stderr.decode(errors='replace')[:300]}"
                )
            return listed.stdout

    def _tracked_seed_files(self) -> bytes:
        """Return a NUL-delimited allowlist of existing indexed paths."""
        listed = self._list_indexed_paths(self._git_index_path())
        existing: list[bytes] = []
        for entry in listed.split(b"\0"):
            if not entry:
                continue
            try:
                metadata, raw_path = entry.split(b"\t", 1)
                mode = metadata.split(b" ", 1)[0]
            except ValueError as exc:
                raise RuntimeError("git returned a malformed staged seed entry") from exc
            # A gitlink names a checked-out directory but does not authorize its
            # contents. Never hand that directory to tar; only seed its parent
            # repository's ordinary indexed files.
            if mode == b"160000":
                continue
            path = PurePosixPath(os.fsdecode(raw_path))
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"git returned an unsafe seed path: {path}")
            candidate = self._repo_root.joinpath(*path.parts)
            if candidate.exists() or candidate.is_symlink():
                existing.append(raw_path)
        return b"".join(path + b"\0" for path in existing)

    def _extract_seed(
        self, cid: str, archive: bytes, destination: str
    ) -> subprocess.CompletedProcess[bytes]:
        """Extract a host-built seed as the agent, never as container root."""
        _docker([*self._exec_prefix(), cid, "mkdir", "-p", destination])
        return subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "-u",
                _AGENT_UID_GID,
                "-e",
                f"HOME={_AGENT_HOME}",
                cid,
                "tar",
                "-xf",
                "-",
                "--no-same-owner",
                "-C",
                destination,
            ],
            input=archive,
            capture_output=True,
            timeout=_SEED_TIMEOUT,
        )

    def __exit__(self, *exc: object) -> None:
        if self._cid:
            _docker(["rm", "-f", self._cid], check=False)
            self._cid = None

    def sync_to_host(self, dest: Path | None = None) -> None:
        """Copy the container workspace back to the host, EXCLUDING ``.git``.

        The agent has shell access inside the container, so a plain archive of
        the whole workspace would let it corrupt refs/config/hooks that the
        caller then runs host-side git against — defeating the isolation. The
        container-side ``--exclude`` below is only a courtesy: it runs *inside*
        the untrusted container, so an attacker who controls that container can
        simply not honor it. The exclude that actually matters is the host-side
        one, applied while extracting — that's the real trust boundary.
        ``--no-same-owner`` on the extract also stops the container's files
        from landing on the host with foreign uids.

        The container-side tar runs as the agent uid, which owns every file in
        the workspace (seeded and written as that uid): `cap-drop=ALL` leaves
        even root without `DAC_OVERRIDE`, so exec-as-root would read no more
        than the owner can — and the owner always can, whatever modes the
        host tree carried (a mode-700 workspace from a 0700 host checkout
        would otherwise break the sync read).
        """
        target = Path(dest) if dest is not None else self._repo_root
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(
            [
                "docker",
                *self._exec_prefix(),
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

    def _reap_agent_processes(self) -> None:
        """Remove agent-owned descendants that can escape a process group.

        ``timeout`` cannot kill a child that calls ``setsid`` (or double-forks)
        into a new session. All candidate processes share the agent uid, while
        PID 1 is the container harness; reaping the rest is the only reliable
        cleanup boundary that does not depend on candidate cooperation.
        """
        _docker(
            [
                *self._exec_prefix(),
                self._require_cid(),
                "sh",
                "-c",
                _REAP_AGENT_PROCESSES.replace("__MAISTRO_HARNESS_PID__", self._harness_pid or "1"),
            ],
            check=False,
            timeout=10,
        )

    def _exec(
        self,
        argv: list[str],
        *,
        timeout: int = _DEFAULT_TIMEOUT,
        git_tools: bool = False,
    ) -> tuple[int, str]:
        # GNU timeout runs inside the container, so killing the docker CLI on a
        # host-side timeout cannot leave candidate processes behind. The reap
        # below additionally handles detached sessions and double-forks.
        command = [
            # Put timeout and the candidate in one process group. This handles
            # ordinary shell children; _reap_agent_processes handles children
            # that deliberately create a separate session.
            "setsid",
            "--wait",
            "timeout",
            "--signal=KILL",
            "--kill-after=1s",
            str(timeout),
            *argv,
        ]
        prefix = self._exec_prefix()
        if git_tools:
            prefix += [
                "-e",
                f"GIT_DIR={_BASELINE_DIR}/.git",
                "-e",
                f"GIT_WORK_TREE={_WORKDIR}",
            ]
        try:
            proc = subprocess.run(
                ["docker", *prefix, self._require_cid(), *command],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        finally:
            # Also reap when the host-side Docker CLI timeout fires; killing the
            # CLI does not stop processes already running in the container.
            self._reap_agent_processes()

    def _exec_prefix(self) -> list[str]:
        """Docker flags every agent-facing exec carries (#77).

        Unprivileged uid + sanitized HOME on *every* exec, explicitly — never
        relying on the container's default user alone, so a future edit that
        drops `--user` from the `docker run` cannot silently re-root the agent.
        """
        return ["exec", "-u", _AGENT_UID_GID, "-e", f"HOME={_AGENT_HOME}"]

    # -- BuilderSandbox protocol --------------------------------------------

    def read_file(self, path: str) -> str:
        rc, out = self._exec(["cat", self._safe(path)])
        if rc != 0:
            raise FileNotFoundError(path)
        return out

    def write_file(self, path: str, content: str) -> None:
        target = self._safe(path)
        parent = str(PurePosixPath(target).parent)
        _docker([*self._exec_prefix(), self._require_cid(), "mkdir", "-p", parent])
        _docker(
            [
                *self._exec_prefix(),
                "-i",
                self._require_cid(),
                "sh",
                "-c",
                f"cat > {_sh_quote(target)}",
            ],
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
        return self.run_argv_status(argv, timeout=timeout)[1]

    def run_argv_status(
        self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT
    ) -> tuple[int, str]:
        """Run ``argv`` in the container, returning its exit status and output.

        `run_argv` discards the status, which is the right shape for an agent
        tool: there the output *is* the answer. For a validation command the
        answer is the status, and a caller that can only see output cannot tell
        a pass from a failure that printed something — so the RSI loop runs its
        candidate test vector through this instead (#305).
        """
        return self._exec(argv, timeout=timeout, git_tools=bool(argv and argv[0] == "git"))

    def diff(self) -> str:
        _, out = self._exec(["git", "-C", _WORKDIR, "diff"], git_tools=True)
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
