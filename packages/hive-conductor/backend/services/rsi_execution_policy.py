"""What an RSI run over HTTP is allowed to touch and allowed to execute (#305).

Why this exists
---------------
`POST /v1/rsi/runs` took `repo_path` and `test_command` as free strings and
handed both to `LocalRsiConfig`, whose `_run_tests` executes the command with
`shell=True` on the host. So the `rsi.execute` scope — which reads as "you may
run the self-improvement loop" — actually conferred "you may run any command as
the Conductor process, against any directory on this machine". Those are not
the same grant, and nothing sat between them.

The shape of the fix is that the caller stops *describing* execution and starts
*selecting* it:

- a repository is a path, but only one that resolves beneath a root the
  operator authorized, after symlinks are followed;
- a test command is not a string at all. It is the name of a profile the server
  holds, and the profile is an argument vector, so there is no shell to
  interpret anything;
- isolation is attested before a candidate runs, and an unavailable backend is
  an error rather than a quiet downgrade to the host.

Fail closed, everywhere
-----------------------
Every default here is the refusing one. No configured root means *nothing* is
authorized, not everything; an unreadable profile overlay is an error, not an
empty overlay; unavailable isolation stops the run. That is deliberate: each of
these has an "unset" state that a deployment reaches by forgetting something,
and the cost of forgetting must never be a wider grant than the one intended.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: The only isolation backend an HTTP-initiated run may use. `LocalSandbox`
#: (both copies of it — `maistro_rsi.sandbox.local` and the shadow in
#: `local_loop`) runs the candidate on the host with no isolation beyond a
#: working directory. It is a development convenience for an operator at a
#: terminal; reaching it over HTTP is the escalation this module exists to stop.
REQUIRED_ISOLATION: Final = "container"

#: Named test commands, as argument vectors. A vector rather than a string is
#: the point: `subprocess` runs it without a shell, so a metacharacter in any
#: token is a character in an argument and cannot become an operator.
_BUILTIN_PROFILES: Final[dict[str, tuple[str, ...]]] = {
    "pytest": ("python", "-m", "pytest", "-q"),
    "pytest-core": ("python", "-m", "pytest", "packages/maistro-core/tests", "-q"),
    "pytest-fast": ("python", "-m", "pytest", "-q", "-x", "--timeout=60"),
}

#: Argv[0] basenames that would put a shell back in the path under a policy
#: name. A profile is refused if it names one, so "add a profile" can never
#: become "add free-text execution with extra steps".
_SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "cmd", "cmd.exe", "pwsh"})


class RsiPolicyError(ValueError):
    """A request the RSI execution policy refuses. Surfaces as a 400."""


@dataclass(frozen=True)
class TestProfile:
    """One executable test command, held by the server rather than the caller."""

    name: str
    argv: tuple[str, ...]


def _settings():  # type: ignore[no-untyped-def]
    from config import get_settings

    return get_settings()


def _authorized_roots() -> tuple[Path, ...]:
    """Directories beneath which an RSI run may target a repository.

    Configured as `RSI_REPO_ROOTS`, `os.pathsep`-separated. Resolved here so a
    root that is itself a symlink still compares against a resolved candidate;
    comparing a resolved path to an unresolved root refuses legitimate repos
    and, worse, teaches whoever hits it to widen the root.
    """
    raw = getattr(_settings(), "rsi_repo_roots", "") or ""
    roots: list[Path] = []
    for entry in raw.split(os.pathsep):
        candidate = entry.strip()
        if not candidate:
            continue
        resolved = Path(candidate).expanduser().resolve()
        if resolved.is_dir():
            roots.append(resolved)
    return tuple(roots)


def resolve_repo(raw: str) -> Path:
    """The repository an RSI run may target, or `RsiPolicyError`.

    Containment is decided *after* `resolve()`, which follows symlinks. `..` is
    the escape everyone blocks; a symlink planted inside an authorized root
    points outward while every component of the requested path reads as legal,
    and a check on the literal string would pass it.
    """
    if not raw or not raw.strip():
        raise RsiPolicyError("repo_path is required")

    roots = _authorized_roots()
    if not roots:
        raise RsiPolicyError(
            "no authorized RSI repository roots are configured — set RSI_REPO_ROOTS "
            "to the directories this deployment may run the loop against"
        )

    try:
        resolved = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError) as exc:  # RuntimeError: symlink loop
        raise RsiPolicyError(f"repo_path could not be resolved: {exc}") from exc

    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise RsiPolicyError(
            f"repo_path is not beneath an authorized root ({', '.join(str(r) for r in roots)})"
        )
    if not resolved.is_dir():
        raise RsiPolicyError("repo_path is not a directory")
    if not (resolved / ".git").exists():
        raise RsiPolicyError("repo_path is not a git repository")
    return resolved


def _overlay_profiles() -> dict[str, tuple[str, ...]]:
    """Operator-defined profiles from `RSI_TEST_PROFILES_FILE`, if configured.

    Deployments test different things, so the built-ins cannot be the whole
    story — but the extension point is a file on the server's disk, not a field
    in the request. An unreadable or malformed file is an error rather than an
    empty overlay: silently falling back to the built-ins would present a
    smaller, differently-named policy as if it were the configured one.
    """
    path = (getattr(_settings(), "rsi_test_profiles_file", "") or "").strip()
    if not path:
        return {}

    source = Path(path).expanduser()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RsiPolicyError(f"RSI test profile file {source} could not be read: {exc}") from exc
    if not isinstance(raw, dict):
        raise RsiPolicyError(f"RSI test profile file {source} must hold an object of name -> argv")

    profiles: dict[str, tuple[str, ...]] = {}
    for name, argv in raw.items():
        if not isinstance(argv, list) or not argv or not all(isinstance(t, str) for t in argv):
            raise RsiPolicyError(f"profile {name!r} must be a non-empty list of strings")
        profiles[str(name)] = tuple(argv)
    return profiles


def _reject_shells(profile: TestProfile) -> TestProfile:
    """Refuse a profile that hands its arguments to a shell.

    `["bash", "-c", "..."]` is a well-formed argument vector and restores every
    property this module removed, behind a name that reads like policy.
    """
    if Path(profile.argv[0]).name.lower() in _SHELLS:
        raise RsiPolicyError(
            f"profile {profile.name!r} invokes {profile.argv[0]!r}, which would "
            f"re-introduce a shell — express the command as its own argument vector"
        )
    if "-c" in profile.argv:
        raise RsiPolicyError(
            f"profile {profile.name!r} passes '-c', which asks an interpreter to "
            f"evaluate a string — name the module or script instead"
        )
    return profile


def test_profiles() -> tuple[TestProfile, ...]:
    """Every selectable test command, built-ins first, each already validated."""
    merged = {**_BUILTIN_PROFILES, **_overlay_profiles()}
    return tuple(
        _reject_shells(TestProfile(name=name, argv=argv)) for name, argv in sorted(merged.items())
    )


def resolve_test_profile(name: str) -> TestProfile:
    """The profile called `name`, or `RsiPolicyError` naming what does exist."""
    available = {profile.name: profile for profile in test_profiles()}
    profile = available.get((name or "").strip())
    if profile is None:
        raise RsiPolicyError(
            f"unknown test profile {name!r}; this deployment offers: {', '.join(sorted(available))}"
        )
    return profile


#: Whether this process can run an RSI cleanup loop with candidate code
#: contained. It cannot, and saying so here is the point (#305).
#:
#: `LocalRsiConfig.isolation="container"` sandboxes only the builders agent's
#: edits; `LocalRsiLoop._run_tests` then runs the test command against the
#: edited worktree ON THE HOST. An argument vector is not an isolation
#: boundary: `python -m pytest` over a candidate-edited tree imports that
#: tree's `conftest.py`, its test modules, and any plugin it declares, so
#: candidate-authored code executes as the Conductor process whether or not a
#: shell parsed the command.
#:
#: `tools/run_rsi_isolated.sh` is the supported isolated path precisely because
#: it puts the WHOLE loop — agent, git, tests, coverage — inside an ephemeral
#: container. Its own header says so: "`maistro_rsi --isolation container` only
#: sandboxes the agent's *edits* and then runs the tests back on the host;
#: running the whole loop in-container closes that gap."
#:
#: So the HTTP path fails closed. Dispatching a run into that wrapper is real
#: work with its own design — where the container runs, how reports come back,
#: how it is cancelled — and is tracked in #509; until it exists, an
#: unattested backend must stop the run rather than quietly be the host.
IN_PROCESS_ISOLATION_AVAILABLE: Final = False


def _isolation_available() -> bool:
    """Whether a backend that contains the WHOLE loop is wired in this process.

    Deliberately not "is the builders container sandbox importable and is
    docker on PATH". Both can be true while the test command still runs on the
    host, and an attestation that answers a narrower question than the one
    being asked is worse than none — it reads as containment to every caller.
    """
    return IN_PROCESS_ISOLATION_AVAILABLE


def require_isolation() -> str:
    """The isolation backend an HTTP run must use, or `RsiPolicyError`.

    Unavailable isolation stops the run. The alternative — falling back to the
    host — is precisely the state this issue is about, and it is worse arriving
    silently than it was arriving by design.
    """
    if not _isolation_available():
        raise RsiPolicyError(
            "this deployment cannot run an RSI cleanup loop with candidate code "
            "contained: the in-process loop executes the test command against the "
            "edited worktree on the host, and an argument vector is not an "
            "isolation boundary. Use tools/run_rsi_isolated.sh, which runs the "
            "whole loop inside an ephemeral container"
        )
    return REQUIRED_ISOLATION
