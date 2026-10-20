"""ADR-093/#76 builders sandbox: the canonical selector plus a host-side
credential boundary.

The authority is `maistro.sandbox`: `__enter__` asks the canonical selector for
a backend satisfying `BUILDER_AGENT` (a builders session runs model-generated
edits and commands unattended, so the policy's floor is the hardware-VM tier),
and every command, read, write and diff executes through that backend. There is
no private Docker/microVM path left here — a host whose selector cannot
evidence a strong enough backend refuses (`NoSuitableBackendError`) instead of
silently choosing weaker isolation.

What this adapter *does* own is the host-side credential boundary, which the
protocol deliberately leaves to callers that have one:

* **Seed.** The sandbox's workspace is a fresh host-side *copy* of the repo,
  minus a credential denylist (`_SEED_EXCLUDES`), built by host-side tar — the
  trust boundary — never by anything running inside the sandbox. The copy lives
  under the canonical allowlisted workspace root, so backends that bind
  `workspace_host` (Kata does) accept it.
* **Sync-back.** `sync_to_host()` copies the sandbox's work back to the host
  with `.git` excluded host-side: the agent had a shell inside the sandbox, so
  repo refs/config/hooks are untrusted, and the filter that matters is the one
  the candidate cannot reach.

The `BuilderSandbox` protocol is synchronous while `SandboxProtocol` is async,
so the adapter owns a dedicated loop thread (`_AsyncBridge`) for the sandbox's
lifetime — safe to call from sync code *and* from inside a host event loop
(the RSI loop's `apply` is async), because the coroutines run on the bridge's
own loop, never the caller's.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Coroutine
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from maistro.sandbox import (
    BUILDER_AGENT,
    NoSuitableBackendError,
    SandboxInstance,
    SandboxProtocol,
    SandboxSelector,
    WorkloadPolicy,
    build_selector,
)
from maistro_bootstrap.builders.errors import SandboxEscapeError

DEFAULT_IMAGE = "maistro-builders:latest"
_WORKDIR = "/workspace"
_DEFAULT_TIMEOUT = 120

# The seed denylist (#77/#78: the sandbox used to be handed the whole repo,
# ambient credentials included). Applied HOST-side when the seed copy is built
# — the trust boundary — never sandbox-side. Pattern semantics verified
# identical on GNU tar 1.35 and bsdtar 3.5.3 (so macOS hosts and Linux CI
# behave the same): patterns prefixed `./` are exact root-relative paths; bare
# names (`.env`, `id_rsa`, `.ssh`) and bare `*.ext` patterns match at ANY
# depth. Secret-shaped material is excluded wherever it sits — the failure
# mode of over-excluding is a visible test failure, while under-excluding
# leaks silently. Committed placeholder content (e.g. `.env.example`) is
# already public; only the secret-shaped names below are dropped.
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
_SEED_TIMEOUT = 300  # tar create+extract through one pipe, host to host

T = TypeVar("T")


class _AsyncBridge:
    """A dedicated event loop, on its own thread, for one sandbox's lifetime.

    `BuilderSandbox` is sync; `SandboxProtocol` is async. `asyncio.run` per
    call would explode the moment a caller is itself inside a loop (the RSI
    loop is), and a backend instance must not hop between short-lived loops.
    One loop for the sandbox's whole lifetime solves both: `run` submits the
    coroutine from any thread and blocks on the concurrent future.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="builders-sandbox-bridge", daemon=True
        )
        self._thread.start()

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=30)
        self._loop.close()


class ContainerBuilderSandbox:
    """A `BuilderSandbox` whose operations execute through the canonical selector.

    Use as a context manager: entering selects a backend for `BUILDER_AGENT`,
    builds the denylist-filtered seed copy and spawns the sandbox; exiting
    destroys the sandbox and removes the seed. The host repo is only read once
    (to seed the copy) and only written by an explicit `sync_to_host()` — the
    agent itself never touches it.

    `selector` is injectable so the adapter contract can be tested on hosts
    with no real backend; production leaves it None and gets the host-evidenced
    selector, which refuses when it cannot satisfy the policy (#76).
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        image: str = DEFAULT_IMAGE,
        policy: WorkloadPolicy | None = None,
        selector: SandboxSelector | None = None,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._image = image
        self._policy = policy if policy is not None else BUILDER_AGENT
        self._selector = selector
        self._backend: SandboxProtocol | None = None
        self._instance: SandboxInstance | None = None
        self._seed_dir: Path | None = None
        self._bridge: _AsyncBridge | None = None

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> ContainerBuilderSandbox:
        selector = self._selector if self._selector is not None else build_selector()
        # The policy authority decides first: a host that cannot evidence a
        # strong enough backend refuses here, before anything is seeded.
        _tier, backend = selector.select(self._policy)
        self._seed_dir = self._seed_workspace()
        base = selector.build_config(self._policy)
        config = replace(
            base,
            # Session envelopes, not isolation strength: the tier floor comes
            # from the policy and is untouched.
            cpu_cores=2.0,
            max_file_mb=1024,
            max_processes=512,
            workspace_host=str(self._seed_dir),
            image=self._image,
        )
        self._bridge = _AsyncBridge()
        try:
            self._instance = self._bridge.run(backend.spawn(config=config))
        except BaseException:
            self.__exit__(None, None, None)
            raise
        self._backend = backend
        return self

    def _seed_workspace(self) -> Path:
        """Build the denylist-filtered seed copy under the workspace allowlist.

        The archive is created and extracted HOST-side — the trust boundary —
        so an inside-the-sandbox filter is never the thing keeping credentials
        out. `COPYFILE_DISABLE` keeps macOS bsdtar from smuggling `._*`
        AppleDouble metadata files into the seed.
        """
        root = Path(tempfile.gettempdir()) / "maistro-workspace"
        root.mkdir(parents=True, exist_ok=True)
        seed_dir = Path(tempfile.mkdtemp(prefix="builders-seed-", dir=root))
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
            shutil.rmtree(seed_dir, ignore_errors=True)
            raise RuntimeError(f"seed tar failed: {archive.stderr.decode(errors='replace')[:300]}")
        extract = subprocess.run(
            [
                "tar",
                "-xf",
                "-",
                "--no-same-owner",
                "-C",
                str(seed_dir),
            ],
            input=archive.stdout,
            capture_output=True,
            timeout=_SEED_TIMEOUT,
        )
        if extract.returncode != 0:
            shutil.rmtree(seed_dir, ignore_errors=True)
            raise RuntimeError(
                f"seed extract failed: {extract.stderr.decode(errors='replace')[:300]}"
            )
        return seed_dir

    def __exit__(self, *exc: object) -> None:
        backend, self._backend = self._backend, None
        instance, self._instance = self._instance, None
        seed_dir, self._seed_dir = self._seed_dir, None
        bridge, self._bridge = self._bridge, None
        try:
            if backend is not None and instance is not None and bridge is not None:
                bridge.run(backend.destroy(instance))
        finally:
            if bridge is not None:
                bridge.close()
            if seed_dir is not None:
                shutil.rmtree(seed_dir, ignore_errors=True)

    def sync_to_host(self, dest: Path | None = None) -> None:
        """Copy the sandbox workspace back to the host, EXCLUDING ``.git``.

        The agent has a shell inside the sandbox, so repo refs/config/hooks it
        wrote are untrusted, and the ``--exclude`` that actually matters is the
        HOST-side one applied while extracting — the candidate cannot reach it.
        ``--no-same-owner`` on the extract also stops the sandbox's files from
        landing on the host with foreign uids.
        """
        seed_dir = self._require_seed()
        target = Path(dest) if dest is not None else self._repo_root
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(
            [
                "tar",
                "-cf",
                "-",
                "--exclude=./.git",
                "-C",
                str(seed_dir),
                ".",
            ],
            capture_output=True,
            timeout=_DEFAULT_TIMEOUT,
        )
        if archive.returncode != 0:
            raise RuntimeError(
                f"workspace tar failed: {archive.stderr.decode(errors='replace')[:300]}"
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

    def _require_seed(self) -> Path:
        if self._seed_dir is None:
            raise RuntimeError("ContainerBuilderSandbox used outside its context manager")
        return self._seed_dir

    def _require_live(self) -> tuple[SandboxProtocol, SandboxInstance]:
        if self._backend is None or self._instance is None or self._bridge is None:
            raise RuntimeError("ContainerBuilderSandbox used outside its context manager")
        return self._backend, self._instance

    def _safe(self, path: str) -> str:
        p = PurePosixPath(path.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts:
            raise SandboxEscapeError(f"Path {path!r} escapes sandbox root")
        return f"{_WORKDIR}/{p.as_posix()}"

    def _exec(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> tuple[int, str]:
        backend, instance = self._require_live()
        result = self._bridge.run(  # type: ignore[union-attr]  # _require_live checked it
            backend.exec(instance, list(argv), timeout_s=timeout)
        )
        return result.exit_code, (result.stdout or "") + (result.stderr or "")

    # -- BuilderSandbox protocol --------------------------------------------

    def read_file(self, path: str) -> str:
        backend, instance = self._require_live()
        content = self._bridge.run(  # type: ignore[union-attr]
            backend.read_file(instance, self._safe(path))
        )
        return content.decode(errors="replace")

    def write_file(self, path: str, content: str) -> None:
        target = self._safe(path)
        parent = str(PurePosixPath(target).parent)
        self._exec(["mkdir", "-p", parent])
        backend, instance = self._require_live()
        self._bridge.run(  # type: ignore[union-attr]
            backend.write_file(instance, target, content.encode())
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
        # Shell runs *inside* the sandbox — the sandbox is the trust boundary.
        _, out = self._exec(["sh", "-c", cmd], timeout=timeout)
        return out

    def run_argv(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> str:
        return self.run_argv_status(argv, timeout=timeout)[1]

    def run_argv_status(
        self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT
    ) -> tuple[int, str]:
        """Run ``argv`` in the sandbox, returning its exit status and output.

        `run_argv` discards the status, which is the right shape for an agent
        tool: there the output *is* the answer. For a validation command the
        answer is the status, and a caller that can only see output cannot tell
        a pass from a failure that printed something — so the RSI loop runs its
        candidate test vector through this instead (#305).
        """
        return self._exec(argv, timeout=timeout)

    def diff(self) -> str:
        _, out = self._exec(
            [
                "git",
                "-C",
                _WORKDIR,
                # The seed copy is host-owned; without this, git's dubious-
                # ownership check refuses to diff a repo it does not own.
                "-c",
                f"safe.directory={_WORKDIR}",
                "diff",
            ]
        )
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


__all__ = ["ContainerBuilderSandbox", "NoSuitableBackendError"]
