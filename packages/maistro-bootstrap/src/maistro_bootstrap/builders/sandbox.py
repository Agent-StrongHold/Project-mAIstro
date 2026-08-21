"""Ephemeral git-worktree sandbox for the builders DAG (SPEC-200).

The sandbox creates a throwaway git worktree at /tmp/maistro-ws-{id}/,
gives the agent a SandboxedShell locked to that directory, and tears it
down on exit.  Nothing runs on the root filesystem.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import uuid4

from maistro_bootstrap.builders.errors import (
    BlockedCommandError,
    CommandTimeoutError,
    OutputTruncatedWarning,
    SandboxEscapeError,
    WorkspaceTeardownError,
)

logger = logging.getLogger(__name__)

_OUTPUT_CAP = 1 * 1024 * 1024  # 1 MB
_DEFAULT_TIMEOUT = 30  # seconds

# Characters that enable shell injection regardless of the blocklist.
# Reject before any other check so the blocklist can't be bypassed via
# $(), backticks, semicolons, pipes, redirects, or newline smuggling.
_INJECTION_CHARS = re.compile(r"[;|&<>`$\\\n\r]|\$\(|\}\{")

# Approved network URLs (an okayed ``curl https://host/p`` / ``pip --index-url
# https://…``) are blanked out before the absolute-path scan so their scheme
# ``//`` isn't mistaken for a filesystem escape. Only network schemes are
# stripped — ``file://`` is deliberately left in, so ``file:///run/reports`` is
# still caught below.
_URL_SCHEME = re.compile(r"\b(?:https?|ftp|ftps|wss?)://\S*", re.IGNORECASE)

# An absolute POSIX path embedded anywhere in a token, where the leading "/"
# is NOT preceded by a path-word char or dot. This distinguishes an absolute
# path (``--file=/etc/passwd``, ``open('/run/reports/x')``, the bare root
# ``/``, ``file:///etc/x``) from an innocuous relative one (``src/f.py``,
# ``tests/``), whose "/" always follows a word char. The trailing ``*`` (not
# ``+``) matches the bare root ``/`` too — e.g. ``os.chdir('/')``. Catches
# flag-glued long forms and interpreter string arguments; short-flag clusters
# (``-f/etc/x``, ``-RFf/etc/x``) follow the flag letters so they're handled
# separately below.
_EMBEDDED_ABS = re.compile(r"(?<![\w.])(/[^\s'\";,)]*)")

_BLOCKED_PATTERNS = (
    "sudo",
    "su ",
    "su\t",
    "git push",
    "git force",
    "chmod 777",
    "chmod -R 777",
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){",  # fork bomb prefix
)

# Minimal environment for every agent-controlled subprocess.
# No os.environ spread — never leak API keys, tokens, or cloud credentials.
# No HOME — setting HOME to the sandbox root creates a $HOME/.. escape primitive.
_SAFE_ENV = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TERM": "dumb",
    "PYTHONDONTWRITEBYTECODE": "1",
}
if os.name == "nt":
    # Windows children are unusable without the system basics — python.exe
    # cannot even start without SystemRoot (_Py_HashRandomization_init fails),
    # and executable lookup by the child needs the real PATH (a POSIX PATH
    # string is meaningless here). Each is forwarded by NAME from an
    # allowlist — still no os.environ spread, and none of these carry
    # credentials, so the no-secret-leak property holds unchanged.
    # NOTE: TEMP/TMP are deliberately NOT forwarded here — see
    # SandboxedShell._env(). The host's real values would let an
    # agent-authored script escape the sandbox via tempfile at runtime,
    # invisibly to _check_paths's command-string scanning.
    _SAFE_ENV.update(
        {
            name: value
            for name in ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT")
            if (value := os.environ.get(name))
        }
    )
else:
    _SAFE_ENV["PATH"] = "/usr/local/bin:/usr/bin:/bin"


@runtime_checkable
class BuilderSandbox(Protocol):
    """Interface shared by all sandbox implementations."""

    def read_file(self, path: str) -> str: ...
    def write_file(self, path: str, content: str) -> None: ...
    def edit_file(self, path: str, old_string: str, new_string: str) -> str: ...
    def run_command(self, cmd: str, *, timeout: int = _DEFAULT_TIMEOUT) -> str: ...
    def run_argv(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> str: ...
    def diff(self) -> str: ...
    def search(self, pattern: str, *, glob: str = "**/*.py") -> list[str]: ...


class SandboxedShell:
    """Subprocess executor locked to a root directory.

    Blocks dangerous commands and detects path-escape attempts before
    any command reaches the OS.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _env(self) -> dict[str, str]:
        """The subprocess environment for this instance's root.

        Codex review (#256): forwarding the HOST's real TEMP/TMP on Windows let
        an agent-authored script escape the sandbox without ever putting an
        absolute path in the command line — `_check_paths` scans the command
        string, but `tempfile.mktemp()` reads TEMP/TMP from the process
        environment at runtime, so `python script.py` calling it landed files
        in the real user Temp directory, outside `self._root` entirely.
        TEMP/TMP now point at a directory INSIDE the sandbox root instead of
        being inherited — python.exe/git only need `TEMP` to exist and be
        writable, not to be any particular directory.
        """
        env = dict(_SAFE_ENV)
        if os.name == "nt":
            sandbox_tmp = self._root / ".sandbox-tmp"
            sandbox_tmp.mkdir(parents=True, exist_ok=True)
            env["TEMP"] = str(sandbox_tmp)
            env["TMP"] = str(sandbox_tmp)
        return env

    def _assert_inside(self, path_str: str, *, token: str) -> None:
        """Raise unless ``path_str`` resolves inside the sandbox root."""
        try:
            Path(path_str).resolve().relative_to(self._root)
        except ValueError:
            raise SandboxEscapeError(
                f"Path escape detected: {path_str!r} in {token!r} escapes sandbox root {self._root}"
            ) from None

    def _check_paths(self, tokens: list[str]) -> None:
        """Raise SandboxEscapeError if any token references a path outside root.

        Token inspection catches every *literal* absolute path — bare
        (``/etc/passwd``), flag-glued (``--file=/etc/x``, ``-f/etc/x``), and
        embedded in an interpreter string (``python -c "open('/run/x')"``). It
        cannot see a path an interpreter *builds* at runtime
        (``open('/ru'+'n/x')``); the report dir's real guarantee is the OS
        filesystem boundary (non-root agent user + a 0700 report dir). This is
        the defense-in-depth layer that stops the realistic cases.
        """
        for token in tokens:
            # Blank out approved network URLs first so an okayed
            # `curl https://host/p` isn't read as a filesystem escape.
            scannable = _URL_SCHEME.sub(" ", token)
            # (1) The whole token as a path relative to root — catches a bare
            #     absolute token and ../ traversal (absolute RHS replaces root,
            #     then relative_to raises).
            try:
                (self._root / token).resolve().relative_to(self._root)
            except ValueError:
                raise SandboxEscapeError(
                    f"Path escape detected: {token!r} escapes sandbox root {self._root}"
                ) from None
            # (2) Any absolute path embedded in the token: a long-flag value
            #     (--out=/etc/x), an interpreter string (open('/run/x')), the
            #     bare root '/', or a file:// path.
            for match in _EMBEDDED_ABS.finditer(scannable):
                self._assert_inside(match.group(1), token=token)
            # (3) A short-flag cluster with a glued path: -f/abs, -I/abs, and
            #     clustered -RFf/abs — the "/" follows the flag letters, so
            #     (2)'s lookbehind misses it. Any SINGLE-dash token carrying a
            #     "/" has its tail (from the first "/") validated. Long options
            #     (--x=rel/path) are double-dash and handled by (2), so their
            #     relative values stay allowed. A single-dash flag glued to a
            #     RELATIVE subpath (-Isrc/foo) is conservatively blocked too —
            #     it's structurally identical to the -f/abs exfil form and can't
            #     be told apart by token shape; use a space (-I src/foo).
            if scannable.startswith("-") and not scannable.startswith("--") and "/" in scannable:
                self._assert_inside(scannable[scannable.index("/") :], token=token)

    def run(self, cmd: str, *, timeout: int = _DEFAULT_TIMEOUT) -> str:
        # 1. Reject shell-injection metacharacters before anything else.
        if _INJECTION_CHARS.search(cmd):
            raise BlockedCommandError(
                f"Shell metacharacters not allowed in sandbox commands: {cmd!r}"
            )

        # 2. Blocklist check on the lowercased raw string.
        cmd_lower = cmd.lower()
        for pattern in _BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                raise BlockedCommandError(f"Blocked command: {pattern!r} in {cmd!r}")

        # 3. Parse with shlex for correct quoted-token handling, then check paths.
        try:
            tokens = shlex.split(cmd)
        except ValueError as exc:
            raise BlockedCommandError(f"Unparseable command: {exc}") from exc
        self._check_paths(tokens)

        try:
            # shell=False + argv list: the safest possible subprocess invocation.
            # Metachar rejection + shlex parse above ensure `tokens` is clean.
            result = subprocess.run(  # nosec B603
                tokens,
                shell=False,
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise CommandTimeoutError(f"Command timed out after {timeout}s: {cmd!r}") from exc

        out = (result.stdout or "") + (result.stderr or "")
        if len(out) > _OUTPUT_CAP:
            warnings.warn(
                f"Output truncated to {_OUTPUT_CAP // 1024}KB",
                OutputTruncatedWarning,
                stacklevel=2,
            )
            out = out[:_OUTPUT_CAP]
        return out

    def run_argv(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> str:
        """Run a fixed argv list with shell=False — no parsing, no metachar check.

        Use this for structured tools (run_tests, run_lint, git_status) where
        the caller constructs the argv directly and no user-controlled string
        ever reaches the shell.
        """
        if not argv:
            raise BlockedCommandError("Empty argv is not allowed")
        for arg in argv:
            if _INJECTION_CHARS.search(arg):
                raise BlockedCommandError(
                    f"Shell metacharacters not allowed in sandbox argv: {arg!r}"
                )
        cmd_lower = " ".join(argv).lower()
        for pattern in _BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                raise BlockedCommandError(f"Blocked command: {pattern!r} in {argv!r}")
        self._check_paths(argv[1:])
        try:
            result = subprocess.run(  # nosec B603 — shell=False, argv from trusted caller
                argv,
                shell=False,
                cwd=self._root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise CommandTimeoutError(f"Command timed out after {timeout}s: {argv!r}") from exc
        out = (result.stdout or "") + (result.stderr or "")
        if len(out) > _OUTPUT_CAP:
            warnings.warn(
                f"Output truncated to {_OUTPUT_CAP // 1024}KB",
                OutputTruncatedWarning,
                stacklevel=2,
            )
            out = out[:_OUTPUT_CAP]
        return out


class GitWorktreeWorkspace:
    """Context manager that creates an ephemeral git worktree.

    Usage::

        with GitWorktreeWorkspace(repo_root=Path("/my/repo")) as ws:
            out = ws.shell.run("pytest -q")
            patch = ws.diff()
    """

    def __init__(self, repo_root: Path, *, base_ref: str = "HEAD") -> None:
        self._repo_root = repo_root.resolve()
        self._base_ref = base_ref
        self._branch: str | None = None
        self._path: Path | None = None
        self._shell: SandboxedShell | None = None

    @property
    def path(self) -> Path:
        if self._path is None:
            raise RuntimeError("Workspace not entered")
        return self._path

    @property
    def shell(self) -> SandboxedShell:
        if self._shell is None:
            raise RuntimeError("Workspace not entered")
        return self._shell

    def __enter__(self) -> GitWorktreeWorkspace:
        uid = uuid4().hex[:12]
        self._branch = f"builders/{uid}"
        self._path = Path(tempfile.mkdtemp(prefix=f"maistro-ws-{uid}-"))
        subprocess.run(  # nosec B603
            [
                "git",
                "worktree",
                "add",
                str(self._path),
                "-b",
                self._branch,
                self._base_ref,
            ],
            cwd=self._repo_root,
            check=True,
            capture_output=True,
        )
        self._shell = SandboxedShell(self._path)
        logger.info("worktree created path=%s branch=%s", self._path, self._branch)
        return self

    def __exit__(self, *_: object) -> None:
        if self._path is None:
            return
        try:
            subprocess.run(  # nosec B603
                ["git", "worktree", "remove", "--force", str(self._path)],
                cwd=self._repo_root,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            raise WorkspaceTeardownError(f"Worktree removal failed: {exc}") from exc
        finally:
            with contextlib.suppress(Exception):
                import shutil

                shutil.rmtree(self._path, ignore_errors=True)
        logger.info("worktree removed path=%s", self._path)

    def diff(self) -> str:
        result = subprocess.run(  # nosec B603
            ["git", "diff"],
            cwd=self._path,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def commit(self, message: str) -> str:
        subprocess.run(["git", "add", "-A"], cwd=self._path, check=True, capture_output=True)  # nosec B603
        result = subprocess.run(  # nosec B603
            ["git", "commit", "-m", message],
            cwd=self._path,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


class LocalWorktreeSandbox:
    """Sandbox implementation backed by a GitWorktreeWorkspace.

    Implements the BuilderSandbox protocol — the TUI and agent loop use
    this interface; they never touch the host filesystem directly.
    """

    def __init__(self, repo_root: Path, *, base_ref: str = "HEAD") -> None:
        self._repo_root = repo_root.resolve()
        self._base_ref = base_ref
        self._ws: GitWorktreeWorkspace | None = None
        self._shell: SandboxedShell | None = None

    def __enter__(self) -> LocalWorktreeSandbox:
        self._ws = GitWorktreeWorkspace(self._repo_root, base_ref=self._base_ref)
        self._ws.__enter__()
        self._shell = self._ws.shell
        return self

    def __exit__(self, *args: object) -> None:
        if self._ws is not None:
            with contextlib.suppress(WorkspaceTeardownError):
                self._ws.__exit__(*args)

    def _require_shell(self) -> SandboxedShell:
        if self._shell is None:
            # Lazy: create a shell on the repo root if not used as context manager
            self._shell = SandboxedShell(self._repo_root)
        return self._shell

    def _resolve(self, path: str) -> Path:
        root = self._ws.path if self._ws else self._repo_root
        resolved = (root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise SandboxEscapeError(f"Path {path!r} escapes sandbox root") from None
        return resolved

    def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        """Replace an exact, unique occurrence of ``old_string`` with ``new_string``.

        A targeted alternative to rewriting the whole file: the model supplies
        only the snippet it wants changed, so it can't mangle untouched lines and
        doesn't burn its token budget re-emitting the entire file. ``old_string``
        must match byte-for-byte and appear exactly once — otherwise raise with
        guidance the agent can act on.
        """
        target = self._resolve(path)
        text = target.read_text(encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            raise ValueError(
                f"old_string not found in {path!r} — it must match the file exactly, "
                "including whitespace and indentation. Re-read the file and copy the "
                "exact text you want to replace."
            )
        if count > 1:
            raise ValueError(
                f"old_string appears {count} times in {path!r} — include more "
                "surrounding context so it matches exactly one location."
            )
        target.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
        return f"edited {path} (1 replacement)"

    def run_command(self, cmd: str, *, timeout: int = _DEFAULT_TIMEOUT) -> str:
        return self._require_shell().run(cmd, timeout=timeout)

    def run_argv(self, argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> str:
        return self._require_shell().run_argv(argv, timeout=timeout)

    def diff(self) -> str:
        if self._ws:
            return self._ws.diff()
        result = subprocess.run(  # nosec B603
            ["git", "diff"],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def search(self, pattern: str, *, glob: str = "**/*.py") -> list[str]:
        root = self._ws.path if self._ws else self._repo_root
        root = root.resolve()
        glob_path = Path(glob)
        if glob_path.is_absolute() or glob.startswith(("/", "\\")) or ".." in glob_path.parts:
            raise SandboxEscapeError(f"Glob escape detected: {glob!r} escapes sandbox root")
        matches = []
        for p in root.glob(glob):
            try:
                resolved = p.resolve()
                resolved.relative_to(root)
                if not resolved.is_file():
                    continue
                text = resolved.read_text(encoding="utf-8", errors="ignore")
                if pattern in text:
                    matches.append(str(resolved.relative_to(root)))
            except (OSError, ValueError):
                pass
        return matches
