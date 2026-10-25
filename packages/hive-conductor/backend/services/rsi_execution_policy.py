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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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


def _settings() -> Any:
    """The Conductor's settings, imported at call time.

    Annotated rather than suppressed. The blanket per-line waiver that used to
    stand here was flagged by the autonomous-merge integrity check, and it was
    the wrong instrument regardless: the import is deferred because
    `backend/` is a flat layout resolved by `sys.path` and importing `config`
    at module scope makes this module unimportable from anywhere else, which
    is a fact about the layout rather than about the type. Every read of the
    result already goes through `getattr(..., default)`, so `Any` is what the
    callers actually rely on.
    """
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


def _beneath_an_authorized_root(resolved: Path, roots: tuple[Path, ...]) -> bool:
    """Whether an already-resolved path sits in one of the authorized roots.

    Two spellings of one question. The string-prefix form is the containment a
    scanner can follow; `is_relative_to` is the one that states it. Both read
    the *resolved* path, so neither can be satisfied by a spelling the other
    rejects — and the separator in the prefix form is what keeps `/srv/rsi-evil`
    from passing as a child of `/srv/rsi`.
    """
    resolved_str = str(resolved)
    lexical = any(
        resolved_str == str(root) or resolved_str.startswith(str(root) + os.sep) for root in roots
    )
    semantic = any(resolved == root or resolved.is_relative_to(root) for root in roots)
    return lexical and semantic


def resolve_repo(raw: str) -> Path:
    """The repository an RSI run may target, or `RsiPolicyError`.

    Containment is decided *after* `resolve()`, which follows symlinks. `..` is
    the escape everyone blocks; a symlink planted inside an authorized root
    points outward while every component of the requested path reads as legal,
    and a check on the literal string would pass it.

    Resolution therefore comes first, and *both* checks below run against the
    resolved path. Comparing the requested string to an already-resolved root
    is not a cheap extra guard, it is a wrong one: where the configured root is
    itself a symlink (`RSI_REPO_ROOTS=/srv/rsi` with `/srv/rsi -> /data/rsi`),
    every legitimate request under the spelling the operator configured fails
    the string check, and the deployment's way out of that is to widen the
    root — a refusal that teaches the wrong lesson is worse than no refusal.
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
        resolved = Path(os.path.expanduser(raw)).resolve()
    except (OSError, RuntimeError) as exc:  # RuntimeError: symlink loop
        raise RsiPolicyError(f"repo_path could not be resolved: {exc}") from exc

    if not _beneath_an_authorized_root(resolved, roots):
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
#: contained.
#:
#: This used to be the literal `False` that made `POST /v1/rsi/runs` fail
#: closed (#305): `LocalRsiConfig.isolation="container"` sandboxes only the
#: builders agent's *edits*, and `LocalRsiLoop._run_tests` then runs the test
#: command against the edited worktree ON THE HOST — an argument vector is not
#: an isolation boundary when `python -m pytest` imports the candidate tree's
#: conftest, test modules and plugins as the Conductor process.
#:
#: #509 restores the capability with a different execution model, so this is
#: no longer a constant refusal — and deliberately not a constant `True`
#: either. `None` — the default — means "attest the container dispatch
#: backend": the loop is contained only when an ephemeral runner container can
#: actually be launched from this process (`rsi_container_dispatch`
#: checks the CLI, the daemon, and the runner image). `False` is the operator
#: kill-switch. Nothing in source may set `True`: attesting containment no
#: probe has verified is exactly the silenced check this flag exists to
#: prevent, so the module-level value staying `None` is itself the auditable
#: fact — the answer comes from the backend, or there is no answer.
IN_PROCESS_ISOLATION_AVAILABLE: bool | None = None


def _isolation_available() -> bool:
    """Whether a backend that contains the WHOLE loop is usable right now.

    Deliberately not "is the builders container sandbox importable and is
    docker on PATH". Both can be true while the test command still runs on the
    host, and an attestation that answers a narrower question than the one
    being asked is worse than none — it reads as containment to every caller.
    The dispatch backend's probe answers the whole question instead: CLI,
    reachable daemon, and the runner image that will contain the loop.
    """
    if IN_PROCESS_ISOLATION_AVAILABLE is not None:
        return IN_PROCESS_ISOLATION_AVAILABLE
    from services.rsi_container_dispatch import backend_available

    return backend_available()


def require_isolation() -> str:
    """The isolation backend an HTTP run must use, or `RsiPolicyError`.

    Unavailable isolation stops the run. The alternative — falling back to the
    host — is precisely the state #305 is about, and it is worse arriving
    silently than it was arriving by design. When the backend IS available the
    return value is the contract the service dispatches on: the whole loop
    runs inside an ephemeral container, never as this process.

    The probe is a subprocess conversation with the docker CLI, so it has the
    CLI's failure modes: a hung daemon can eat the probe's whole timeout and
    raise `TimeoutExpired`, and the CLI can vanish between `which` and `run`
    (`OSError`). Either must land in the SAME operator-facing refusal as an
    ordinary "no" — an unhandled exception here would turn the route's intended
    400 into a 500 that says nothing about what to fix.
    """
    try:
        available = _isolation_available()
        reason = None if available else _unavailability_reason_safe()
    except (OSError, subprocess.SubprocessError):
        available = False
        reason = "the container backend probe itself failed"
    if not available:
        raise RsiPolicyError(
            "no contained RSI backend is available in this deployment — candidate "
            f"code must run in an ephemeral runner container, and: {reason}. Until "
            "then, tools/run_rsi_isolated.sh drives the same contained loop "
            "outside the Conductor"
        )
    return REQUIRED_ISOLATION


def _unavailability_reason_safe() -> str:
    """`unavailability_reason()` with its subprocess failures folded into text."""
    from services.rsi_container_dispatch import unavailability_reason

    try:
        return unavailability_reason() or "the container backend could not be attested"
    except (OSError, subprocess.SubprocessError):
        return "the container backend probe itself failed"
