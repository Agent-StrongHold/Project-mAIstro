"""ADR-093 sandbox: run the agent's edits and commands inside a container.

`LocalWorktreeSandbox` operates on the host filesystem — fine for trusted use,
but ADR-093 mandates hardware-VM-class isolation for *untrusted agent code*
(the architecture-fit judge flagged the local path as violating it). This is the
Docker-backed implementation ADR-093 names as satisfying the isolation contract
today (Firecracker/E2B/gVisor remain an open backend choice): the repo's working
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

# Every command that can run candidate-influenced code executes as this
# unprivileged identity (#77: the sandbox used to run the agent as container
# root). A numeric uid:gid works in any image — no passwd entry is needed —
# and is deliberately not 0. Container PID 1 is `sleep infinity` (harness
# code, not candidate code) and also runs as this user via `--user`.
_AGENT_UID_GID = "65532:65532"
_AGENT_HOME = "/tmp"  # 1777 in the base images; outside the synced workspace

# The seed denylist (#77/#78: the sandbox used to hand the container the whole
# repo via `docker cp`, ambient credentials included). Applied HOST-side when
# the seed archive is built — the trust boundary — never container-side.
# Pattern semantics verified identical on GNU tar 1.35 and bsdtar 3.5.3 (so
# macOS hosts and Linux CI behave the same): patterns prefixed `./` are exact
# root-relative paths; bare names (`.env`, `id_rsa`, `.ssh`) and bare
# `*.ext` patterns match at ANY depth. Secret-shaped material is excluded
# wherever it sits — the failure mode of over-excluding is a visible test
# failure, while under-excluding leaks silently. Committed placeholder
# content (e.g. `.env.example`) is already public; only the secret-shaped
# names below are dropped.
_SEED_EXCLUDES = (
    # git metadata that carries host-side code or credentials. HEAD/index/
    # objects stay so `git diff`/`git status` keep working inside; config
    # (credential helpers, fsmonitor/pager command hooks, remote URLs with
    # embedded tokens) and hooks (host-authored scripts) do not.
    "./.git/config",
    "./.git/hooks",
    # dotenv secrets (the gitignored kind), at any depth.
    ".env",
    ".env.local",
    ".env.*.local",
    # ambient credential directories and registry logins, at any depth.
    ".ssh",
    ".aws",
    ".gnupg",
    ".docker",
    ".npmrc",
    ".netrc",
    "_netrc",
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
_SEED_TIMEOUT = 300  # tar create+extract through one pipe ≈ 2x the old `docker cp`


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
    the (denylist-filtered) working tree; exiting force-removes the container
    (nothing persists). The host repo is only read once (to seed the container)
    and only written by an explicit `sync_to_host()` — the agent itself never
    touches it. Every command the agent can reach runs as `_AGENT_UID_GID`
    inside a `--network=none` container (#77).
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
                # Default-deny egress (#77): no interface beyond loopback, so
                # external, DNS, link-local and private paths all fail.
                "--network=none",
                # Nobody in this container runs as root — not PID 1, not any
                # exec — and no capability survives the drop (CHOWN returns
                # solely for the one-shot root bootstrap below; caps granted
                # to uid 0 cannot be exercised by the agent's uid).
                "--user",
                _AGENT_UID_GID,
                "--cap-drop=ALL",
                "--cap-add=CHOWN",
                "--security-opt=no-new-privileges",
                f"--memory={_MEMORY_LIMIT}",
                f"--pids-limit={_PIDS_LIMIT}",
                "-e",
                f"HOME={_AGENT_HOME}",
                self._image,
                "sleep",
                "infinity",
            ]
        ).stdout.strip()
        self._cid = cid
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

    def _seed(self, cid: str) -> None:
        """Seed the workspace with the repo, minus the `_SEED_EXCLUDES` denylist.

        The archive is built HOST-side (the trust boundary — an inside-the-
        container filter would run as the party being contained) and extracted
        *as the agent uid*, so every seeded file is owned by the unprivileged
        user from the start — no root-owned files, no later `chown -R` pass,
        and `git` sees consistent ownership. `COPYFILE_DISABLE` keeps macOS
        bsdtar from smuggling `._*` AppleDouble metadata files into the seed.
        """
        archive = subprocess.run(
            [
                "tar",
                "-cf",
                "-",
                *[f"--exclude={pattern}" for pattern in _SEED_EXCLUDES],
                "-C",
                str(self._repo_root),
                ".",
            ],
            capture_output=True,
            timeout=_SEED_TIMEOUT,
            env={**os.environ, "COPYFILE_DISABLE": "1"},
        )
        if archive.returncode != 0:
            self.__exit__(None, None, None)
            raise RuntimeError(f"seed tar failed: {archive.stderr.decode(errors='replace')[:300]}")
        extract = subprocess.run(
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
                _WORKDIR,
            ],
            input=archive.stdout,
            capture_output=True,
            timeout=_SEED_TIMEOUT,
        )
        if extract.returncode != 0:
            self.__exit__(None, None, None)
            raise RuntimeError(
                f"container tar extract failed: {extract.stderr.decode(errors='replace')[:300]}"
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

    def _exec(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> tuple[int, str]:
        proc = subprocess.run(
            ["docker", *self._exec_prefix(), self._require_cid(), *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

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
        return self._exec(argv, timeout=timeout)

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
