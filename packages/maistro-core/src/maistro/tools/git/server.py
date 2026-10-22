"""Git operations MCP server — clone, branch, commit, push, PR, diff.

Exposes git and GitHub operations as MCP tools for agents to use.
All tools return structured dicts with {success, exit_code, stdout, ...};
failures additionally carry {error_code, recoverable, suggested_action}.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import SplitResult, urlsplit
from urllib.request import url2pathname

from fastmcp import FastMCP
from pydantic import Field

from maistro.tools.git.github import create_pr, get_pr, list_issues
from maistro.tools.result import fail, ok
from maistro.tools.sandbox.workspace import validate_workspace_path

mcp = FastMCP("git", instructions="Git and GitHub operations")

GIT_CLONE_TIMEOUT = 300

# Transport policy for `git_clone`. Only authenticated transports may carry a
# candidate source: `https://` and `ssh://` verify the remote. `git://` is the
# unauthenticated, unencrypted git daemon protocol — an on-path attacker can
# substitute repository content that downstream builds/tests execute — so it
# is hard-rejected first, even if the allowlist below is ever widened. The
# same whitelist travels with every git command this server runs (_TRANSPORT_PIN
# below): command-line `-c` config is invocation-scoped — the clone neither
# writes it into the destination repo nor is it inherited by a later command —
# so it is re-applied per invocation, and GIT_CONFIG_PARAMETERS carries it into
# child git processes, which is how a server-issued `git submodule update`
# pins the submodule's internal clone. The clone additionally persists the
# whitelist into the destination's local config (_pin_destination_transport),
# where later in-repo fetch/pull/push read it. Anything else — bare local
# paths, `scp`-like `host:path`, a `-`-prefixed string argv would hand to git
# as a flag — is rejected by parsing the URL, not prefix-matching it, so case
# (`GIT://`) and encoded spellings resolve to the same decision.
#
# Signature policy (#404 AC3's "identity/signature policy" clause): digest
# identity over authenticated transport is the default. A deployment that
# wants signed provenance names its trust anchor in
# MAISTRO_GIT_CLONE_TRUSTED_SIGNERS (comma-separated full OpenPGP key
# fingerprints; the corresponding public keys must be in the runner's
# keyring, which is what `git log %G?` consults) — then EVERY successful
# clone must additionally land on a commit whose signature is
# cryptographically good (`%G?` G — or U: good with unknown *local* keyring
# trust, a keyring setting rather than a cryptographic verdict) and made by
# a trusted key (`%GP`/`%GF` fingerprint match); anything else fails with
# its own error code. On top of the anchor, an individual call can demand a
# verifiable signature via `require_signed` (`git verify-commit` on the
# pinned digest). The anchor is deliberately deployment-wide (env), not
# per-call: a candidate source's provenance is a property of what the
# deployment executes, not of who remembered to ask.
_FORBIDDEN_CLONE_SCHEMES = ("git://",)
_ALLOWED_CLONE_SCHEMES = ("https://", "ssh://")

# Host policy (always on): an https/ssh source must name one of these hosts.
# Merged from the two #404 implementations — the deployments-wide override is
# MAISTRO_GIT_CLONE_HOSTS (comma-separated); without it the well-known code
# forges are the only candidate sources, so an arbitrary https host is not
# silently clonable.
_DEFAULT_ALLOWED_CLONE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "ssh.github.com")

# "Verified local sources": `file://` is clonable only when the scheme tuple
# above is explicitly widened AND the resolved source path sits under one of
# these roots. Empty by default — production refuses local sources outright;
# hermetic tests opt in exactly the way they relax ALLOWED_HOST_ROOTS.
_ALLOWED_LOCAL_SOURCE_ROOTS: tuple[str, ...] = ()


def _clone_host_allowlist() -> frozenset[str]:
    """Host policy for remote sources, read per call so tests and deploys can
    set it via MAISTRO_GIT_CLONE_HOSTS (comma-separated hostnames). Without
    the override the default forges above are the allowlist — remote sources
    are always host-restricted, never "any https host goes"."""
    raw = os.environ.get("MAISTRO_GIT_CLONE_HOSTS", "")
    override = frozenset(host.strip().lower() for host in raw.split(",") if host.strip())
    return override or frozenset(_DEFAULT_ALLOWED_CLONE_HOSTS)


# (key, value) transport whitelist applied at three layers:
# - as `-c` flags ahead of the clone subprocess (_CLONE_CONFIG_HARDENING) and
#   ahead of every other git command this server issues in a workspace —
#   always before the subcommand, so a URL can never override them;
# - persisted into the clone destination's local config post-clone
#   (_pin_destination_transport), where in-repo fetch/pull/push read it. git's
#   `clone` command ignores the enclosing repo's local config, which is why
#   the flags are re-applied per invocation instead of relying on this row;
# - protocol.file.allow=user keeps file:// usable only by a direct
#   user-invoked fetch/clone/push, so an indirect transport — a submodule
#   fetch, or a redirect target — cannot use it.
# - http.followRedirects=false: an http(s) source cannot be silently
#   redirected to another host or downgraded off HTTPS — the command fails
#   instead, and the same URL policy applies to whatever the caller asked for.
# - http.sslVerify=true: a stray system/global git config cannot disable
#   certificate verification.
# Declared submodule URLs are additionally validated against the same source
# policy right after the clone (_validate_submodule_urls).
_TRANSPORT_PIN: tuple[tuple[str, str], ...] = (
    ("protocol.allow", "never"),
    ("protocol.https.allow", "always"),
    ("protocol.ssh.allow", "always"),
    ("protocol.file.allow", "user"),
    ("http.followRedirects", "false"),
    ("http.sslVerify", "true"),
)
_CLONE_CONFIG_HARDENING = tuple(
    flag for key, value in _TRANSPORT_PIN for flag in ("-c", f"{key}={value}")
)

# Commit pins must be full SHA-1 or SHA-256 digests — branch names and
# abbreviated SHAs can be re-pointed and are not an identity.
_COMMIT_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")
_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

# Remediation hint carried by every URL-policy rejection that does not name a
# more specific one (develop-side #404 API: the message and this hint travel
# with the exception, so non-MCP surfaces — the RSI harvest gate, the builders
# TUI — render the same verdict the MCP tool returns).
_CLONE_POLICY_ACTION = (
    "Use an https:// or ssh:// URL for a host allowed by the configured "
    "clone policy (MAISTRO_GIT_CLONE_HOSTS); git:// and local paths are "
    "not accepted as candidate sources."
)


class ClonePolicyError(ValueError):
    """A clone source violated URL policy; carries its machine-readable code
    and the remediation hint surfaced to callers."""

    def __init__(
        self, message: str, error_code: str, suggested_action: str = _CLONE_POLICY_ACTION
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.suggested_action = suggested_action


def _check_clone_scheme_allowed(scheme: str, url: str) -> None:
    """Hard-deny unauthenticated transports, then allowlist the rest.

    The forbidden check runs before the allowlist check so a hostile config
    that widens _ALLOWED_CLONE_SCHEMES can never smuggle git:// back in.
    """
    if f"{scheme}://" in _FORBIDDEN_CLONE_SCHEMES:
        raise ClonePolicyError(
            f"Blocked: unauthenticated clone transport is not allowed: {url}",
            "blocked_url_scheme",
        )
    if f"{scheme}://" not in tuple(s.lower() for s in _ALLOWED_CLONE_SCHEMES):
        raise ClonePolicyError(f"Blocked: url scheme is not allowed: {url}", "blocked_url_scheme")


def _validate_remote_clone_host(parts: SplitResult, url: str) -> tuple[str, str]:
    """Gate remote (non-file) sources behind the explicit host policy."""
    host = (parts.hostname or "").lower()
    if not host:
        raise ClonePolicyError(f"Blocked: url has no host: {url}", "blocked_url_scheme")
    allowlist = _clone_host_allowlist()
    if host not in allowlist:
        raise ClonePolicyError(
            f"Blocked: clone host is not in policy: {host}", "blocked_clone_host"
        )
    scheme = parts.scheme.lower()
    return scheme, host


def _validate_clone_url(url: str) -> tuple[str, str]:
    """Validate a clone *source* URL against the transport/host policy.

    Returns the normalized (scheme, hostname); raises :class:`ClonePolicyError`
    otherwise. The same function validates submodule URLs, so redirects are
    refused at the transport level and every nested source is held to the
    identical rules.
    """
    if not url:
        raise ClonePolicyError("Blocked: empty clone url", "blocked_url_scheme")
    if url.startswith("-"):
        raise ClonePolicyError(f"Blocked: url must not start with '-': {url}", "blocked_url_scheme")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    _check_clone_scheme_allowed(scheme, url)
    if scheme == "file":
        return _validate_local_clone_source(parts, url)
    return _validate_remote_clone_host(parts, url)


def validate_clone_source(url: str) -> None:
    """Raise :class:`ClonePolicyError` unless `url` is a clonable source.

    The one #404 verdict, shared verbatim by every surface that clones: the
    MCP `git_clone` tool, the RSI harvest cloud path (`maistro_rsi.__main__`)
    and the builders TUI. There is no second policy to drift — a URL refused
    here is refused everywhere, before any subprocess runs.
    """
    _validate_clone_url(url)


def _validate_local_clone_source(parts: SplitResult, url: str) -> tuple[str, str]:
    """Gate `file://` sources: they are only clonable when explicitly opted
    into via _ALLOWED_CLONE_SCHEMES AND the resolved path sits under a verified
    local root (empty by default — production refuses local sources)."""
    if "file://" not in tuple(s.lower() for s in _ALLOWED_CLONE_SCHEMES):
        raise ClonePolicyError(f"Blocked: url scheme is not allowed: {url}", "blocked_url_scheme")
    source = Path(url2pathname(parts.path)).resolve()
    for root in _ALLOWED_LOCAL_SOURCE_ROOTS:
        root_resolved = Path(root).resolve()
        if source == root_resolved or root_resolved in source.parents:
            return "file", "localhost"
    raise ClonePolicyError(
        f"Blocked: local clone source is not under a verified root: {url}",
        "blocked_local_source",
    )


def _blocked_clone_source_result(exc: ClonePolicyError) -> dict[str, Any]:
    return fail(
        stdout=exc.message,
        error_code=exc.error_code,
        suggested_action=exc.suggested_action,
    )


# In-memory dedup for PR creation, keyed by a content hash rather than a
# model-supplied key — retries with identical args return the original
# result instead of opening a duplicate PR. Bounded TTL, not a permanent
# store: a deliberately new PR with identical content after the window
# is rare enough not to matter, and unbounded growth would leak memory.
_PR_CACHE_TTL_S = 300
_pr_cache: dict[str, dict[str, Any]] = {}


def _validate_git_workspace(workspace: str) -> str:
    try:
        return str(validate_workspace_path(workspace))
    except ValueError as exc:
        raise ValueError(f"Git workspace path is not allowed: {workspace}") from exc


def _blocked_workspace_result(workspace: str) -> dict[str, Any]:
    return fail(
        stdout=f"Blocked: git workspace path is not allowed: {workspace}",
        error_code="blocked_workspace",
        suggested_action="Use a workspace under /tmp/maistro-workspace or /repos.",
    )


def _pr_cache_key(repo: str, branch: str, title: str, body: str, base: str) -> str:
    raw = "\n".join((repo, branch, title, body, base))
    return hashlib.sha256(raw.encode()).hexdigest()


async def _git(workspace: str, *args: str, timeout: int = 60) -> dict[str, Any]:
    """Run a git command in the given workspace. Returns structured result."""
    try:
        workspace = _validate_git_workspace(workspace)
    except ValueError:
        return _blocked_workspace_result(workspace)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            workspace,
            *_CLONE_CONFIG_HARDENING,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        code = proc.returncode or 0
        if code == 0:
            return ok(stdout=output, exit_code=code)
        return fail(
            stdout=output,
            exit_code=code,
            error_code="git_command_failed",
            recoverable=True,
            suggested_action="Inspect stdout for git's error message, correct the command or workspace state, and retry.",
        )
    except FileNotFoundError:
        return fail(
            stdout="git binary not found",
            error_code="git_not_found",
            suggested_action="Ensure git is installed in the execution environment.",
        )
    except TimeoutError:
        return fail(
            stdout=f"git command timed out after {timeout}s",
            exit_code=124,
            error_code="git_timeout",
            recoverable=True,
            suggested_action="Retry with a longer timeout or a narrower operation.",
        )


def _parse_log_lines(output: str) -> list[dict[str, str]]:
    """Parse `git log --oneline` output ('<sha> <message>') into structured records."""
    commits: list[dict[str, str]] = []
    for line in output.splitlines():
        sha, _, message = line.partition(" ")
        if sha:
            commits.append({"sha": sha, "message": message})
    return commits


async def _resolve_pinned_head(dest: str, pin: str) -> tuple[str, dict[str, Any] | None]:
    """Land the workspace exactly on ``pin`` after the default branch missed it.

    The default branch did not land on the pin (the ref moved between
    resolution and fetch — TOCTOU — or the pin is historical). Fetch the
    digest itself, detach to it, and re-verify: the fetched object
    identity must equal the pin or the workspace is rejected outright.
    Returns ``(resolved_head, failure)`` — failure is None on success.
    """
    fetched = await _git(dest, "fetch", "--depth=1", "origin", pin)
    if not fetched["success"]:
        return "", fail(
            stdout=fetched["stdout"],
            exit_code=fetched.get("exit_code", 1),
            error_code="commit_pin_mismatch",
            recoverable=False,
            suggested_action=(
                f"The pinned commit {pin} is not reachable from the remote; "
                "verify the digest or the source policy."
            ),
        )
    checkout = await _git(dest, "checkout", "--detach", pin)
    if not checkout["success"]:
        return "", _pin_mismatch(pin, checkout)
    head = await _git(dest, "rev-parse", "HEAD")
    resolved = head["stdout"].strip().lower() if head["success"] else ""
    if not head["success"] or resolved != pin:
        return "", _pin_mismatch(pin, head)
    return resolved, None


async def _verify_commit_signature(dest: str, pin: str) -> dict[str, Any] | None:
    """Enforce the per-call signature policy on the pinned digest (fail
    closed): `require_signed=True` demands `git verify-commit` accept the
    pinned commit — a verifiable OpenPGP signature under the local keyring's
    trust model."""
    signature = await _git(dest, "verify-commit", pin)
    if not signature["success"]:
        return fail(
            stdout=signature["stdout"],
            exit_code=signature.get("exit_code", 1),
            error_code="commit_signature_unverified",
            recoverable=False,
            suggested_action=(
                "The signature policy requires the pinned commit to carry a "
                "verifiable signature; configure trusted keys or pin a "
                "signed commit."
            ),
        )
    return None


# Deployment-wide signature trust anchor (#404 AC3; the develop-side API the
# develop-sync merge had dropped, restored by the repair round): full OpenPGP
# key fingerprints (40/64 hex, spaces allowed) this deployment trusts to sign
# candidate clone sources.
_TRUSTED_SIGNERS_ENV = "MAISTRO_GIT_CLONE_TRUSTED_SIGNERS"
# `git log %G?` verdicts that mean "cryptographically good signature": G is
# good; U is good with unknown *local* keyring trust, which is a keyring
# setting, not a cryptographic verdict, and must not fail a policy whose
# anchor is the fingerprint allowlist anyway.
_GOOD_SIGNATURE_STATUSES = frozenset({"G", "U"})


def _trusted_signature_fprs() -> frozenset[str]:
    """Normalized (space-stripped, lowercased) signer key fingerprints from
    `MAISTRO_GIT_CLONE_TRUSTED_SIGNERS`. Empty frozenset — no signature
    requirement — when the deployment has not configured the anchor."""
    raw = os.environ.get(_TRUSTED_SIGNERS_ENV, "")
    return frozenset(fpr.replace(" ", "").lower() for fpr in raw.split(",") if fpr.strip())


def _signature_policy_failure(
    result: dict[str, Any], error_code: str, detail: str, suggested_action: str
) -> dict[str, Any]:
    """Fail a finished clone whose HEAD violated the signature trust anchor,
    keeping the clone's own stdout (and the verdict) in the audit trail."""
    return fail(
        stdout=(result.get("stdout", "") or "") + f"\ncommit signature policy: {detail}",
        error_code=error_code,
        suggested_action=suggested_action,
    )


def _landed_signer_fprs(fprs: dict[str, Any]) -> set[str]:
    """Normalized (space-stripped, lowercased) signer fingerprints reported
    by `git log %GF%n%GP`; empty when the read itself failed."""
    if not fprs["success"]:
        return set()
    return {
        line.strip().replace(" ", "").lower()
        for line in fprs["stdout"].splitlines()
        if line.strip()
    }


async def _enforce_signature_policy(
    dest: str, result: dict[str, Any], timeout: int
) -> dict[str, Any]:
    """Apply the #404 AC3 signature policy to a finished, identity-verified
    clone.

    No-op unless the deployment configured a trust anchor
    (`MAISTRO_GIT_CLONE_TRUSTED_SIGNERS`): the default policy is digest
    identity over authenticated transport, documented in the module header.
    With the anchor set, HEAD's signature must be cryptographically good
    (`%G?` G or U) and made by a trusted key (`%GP`/`%GF` fingerprint match) —
    the checked-out commit is the object the caller receives, so its
    signature is the provenance being attested.
    """
    trusted = _trusted_signature_fprs()
    if not trusted:
        return result
    status = await _git(dest, "log", "-1", "--pretty=format:%G?", timeout=timeout)
    verdict = status["stdout"].strip() if status["success"] else ""
    if verdict == "N" or not verdict:
        return _signature_policy_failure(
            result,
            "commit_signature_missing",
            f"HEAD is not signed ({verdict or 'unreadable'})",
            f"{_TRUSTED_SIGNERS_ENV} requires signed candidate sources; the "
            "cloned HEAD carries no valid OpenPGP signature. Do not use this "
            "workspace.",
        )
    if verdict not in _GOOD_SIGNATURE_STATUSES:
        return _signature_policy_failure(
            result,
            "commit_signature_invalid",
            f"HEAD signature is not good ({verdict})",
            f"{_TRUSTED_SIGNERS_ENV} is set, so the cloned HEAD must carry a "
            f"good signature; git reports {verdict!r}. The source or the local "
            "keyring is wrong — do not use this workspace.",
        )
    fprs = await _git(dest, "log", "-1", "--pretty=format:%GF%n%GP", timeout=timeout)
    landed = _landed_signer_fprs(fprs)
    if not landed & trusted:
        return _signature_policy_failure(
            result,
            "commit_signature_untrusted",
            f"signer {sorted(landed) or 'unknown'} is not on the trusted-signer allowlist",
            f"The signature is good but the key is not one of the fingerprints "
            f"in {_TRUSTED_SIGNERS_ENV}. Do not use this workspace.",
        )
    augmented = dict(result)
    augmented["signature_verified"] = True
    return augmented


async def _pin_destination_transport(dest: str) -> dict[str, Any] | None:
    """Persist the transport whitelist into the cloned repo's local config.

    git's `clone` command ignores the enclosing repo's local config, so the
    `-c` flags on the clone subprocess cannot protect commands run later in
    the workspace; writing _TRANSPORT_PIN into dest/.git/config puts it where
    in-repo fetch/pull/push read it. Fail-closed: a destination whose config
    cannot be pinned is rejected outright.
    """
    for key, value in _TRANSPORT_PIN:
        result = await _git(dest, "config", key, value)
        if not result["success"]:
            return fail(
                stdout=result["stdout"],
                exit_code=result.get("exit_code", 1),
                error_code="transport_pin_failed",
                recoverable=False,
                suggested_action=(
                    "The cloned workspace could not be pinned to the "
                    "source-policy transport whitelist; do not use it as a "
                    "candidate source."
                ),
            )
    return None


async def _verify_cloned_source(dest: str, *, pin: str | None) -> dict[str, Any]:
    """Post-clone identity checks on the fetched tree.

    Persists the transport whitelist into the destination config, resolves
    HEAD, enforces the commit-digest pin (fetching the digest
    itself and detaching when the default branch moved — the TOCTOU guard),
    and validates every .gitmodules submodule
    URL against the same source policy as the top-level clone. Returns
    ``{"ok": True, "head_commit": <digest>}`` or a structured failure.
    """
    transport_failure = await _pin_destination_transport(dest)
    if transport_failure is not None:
        return transport_failure
    head = await _git(dest, "rev-parse", "HEAD")
    if not head["success"]:
        return fail(
            stdout=head["stdout"],
            exit_code=head.get("exit_code", 1),
            error_code="git_clone_failed",
            recoverable=False,
            suggested_action=(
                "The clone succeeded but HEAD could not be resolved; inspect "
                "the destination repository before using it."
            ),
        )
    resolved = head["stdout"].strip().lower()

    if pin is not None and resolved != pin:
        resolved, pin_failure = await _resolve_pinned_head(dest, pin)
        if pin_failure is not None:
            return pin_failure

    submodule_failure = await _validate_submodule_urls(dest)
    if submodule_failure is not None:
        return submodule_failure
    return {"ok": True, "head_commit": resolved}


def _pin_mismatch(pin: str, git_result: dict[str, Any]) -> dict[str, Any]:
    return fail(
        stdout=git_result["stdout"],
        exit_code=git_result.get("exit_code", 1),
        error_code="commit_pin_mismatch",
        recoverable=False,
        suggested_action=(
            f"The cloned HEAD does not match the pinned digest {pin}; the ref "
            "moved or the pin is wrong — refusing to hand over the workspace."
        ),
    )


async def _validate_submodule_urls(dest: str) -> dict[str, Any] | None:
    """Every submodule URL declared by the fetched tree must pass the same
    source policy as the top-level clone — a hostile .gitmodules cannot
    reintroduce git:// (or any non-policy transport) via a later `git
    submodule update`. Returns a structured failure, or None when the tree
    declares no violating submodule."""
    if not (Path(dest) / ".gitmodules").is_file():
        return None
    config = await _git(
        dest, "config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.url$"
    )
    if config.get("exit_code") == 1:
        # Well-formed file with no submodule url entries.
        return None
    if not config["success"]:
        return fail(
            stdout=config["stdout"],
            exit_code=config.get("exit_code", 1),
            error_code="submodule_policy_error",
            recoverable=False,
            suggested_action=(
                "The fetched .gitmodules is malformed and cannot be validated; "
                "do not initialize submodules from this workspace."
            ),
        )
    for line in config["stdout"].splitlines():
        _, _, raw_url = line.partition(" ")
        url = raw_url.strip()
        if not url:
            continue
        try:
            _validate_clone_url(url)
        except ClonePolicyError as exc:
            return fail(
                stdout=exc.message,
                error_code="blocked_submodule_url",
                recoverable=False,
                suggested_action=(
                    "The fetched tree declares a submodule outside source "
                    "policy; do not run `git submodule init/update` in this "
                    "workspace."
                ),
            )
    return None


@mcp.tool()
async def git_remote_tip(
    url: str, timeout: Annotated[int, Field(ge=1, le=900)] = 60
) -> dict[str, Any]:
    """Resolve a policy-vetted remote's HEAD to a full commit digest (#404).

    The one network read a caller needs to turn "clone whatever the tip is
    right now" into a verified digest pin: the returned digest feeds
    `git_clone(commit=...)`, whose fetch-by-digest and post-fetch `rev-parse`
    verdict then prove the checkout IS that object. `ls-remote` is itself a
    network transport, so it gates through the same source policy first — a
    refused URL spawns no subprocess — and carries the same transport pins as
    every other subprocess this module spawns. A resolution that is not a
    full digest is refused: the point of the resolution is an immutable pin,
    not a repointable name.
    """
    try:
        _validate_clone_url(url)
    except ClonePolicyError as exc:
        return _blocked_clone_source_result(exc)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *_CLONE_CONFIG_HARDENING,
            "ls-remote",
            "--",
            url,
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
    except FileNotFoundError:
        return fail(
            stdout="git binary not found",
            error_code="git_not_found",
            suggested_action="Ensure git is installed in the execution environment.",
        )
    except TimeoutError:
        return fail(
            stdout=f"git ls-remote timed out after {timeout}s",
            exit_code=124,
            error_code="git_timeout",
            recoverable=True,
            suggested_action="Retry with a longer timeout, or check network conditions.",
        )
    if proc.returncode != 0:
        return fail(
            stdout=output,
            exit_code=proc.returncode or 1,
            error_code="remote_tip_unresolved",
            recoverable=True,
            suggested_action=(
                "Could not read the remote's HEAD digest; verify the source is "
                "reachable and pass the digest to clone explicitly instead."
            ),
        )
    digest = output.split()[0] if output.split() else ""
    if not _COMMIT_DIGEST_RE.match(digest):
        return fail(
            stdout=output,
            error_code="remote_tip_unresolved",
            suggested_action=(
                "The remote's HEAD did not resolve to a full 40/64-hex digest; "
                "resolve it manually (git ls-remote) and pass the digest to "
                "clone explicitly instead."
            ),
        )
    return ok(stdout=output, commit=digest.lower())


@mcp.tool()
async def git_clone(
    url: str,
    dest: str,
    timeout: Annotated[int, Field(ge=1, le=900)] = GIT_CLONE_TIMEOUT,
    commit: str | None = None,
    require_signed: bool = False,
) -> dict[str, Any]:
    """Clone a git repository (shallow, depth=1) under the source policy.

    Candidate sources must arrive over an authenticated transport (https:// or
    ssh://) for a host allowed by MAISTRO_GIT_CLONE_HOSTS (default: the
    well-known forges); `git://` — unauthenticated and unencrypted — is
    always rejected, as are local paths unless a verified local root is
    configured. Redirects are refused and the git protocol whitelist is
    pinned, so neither a redirect, a protocol downgrade, nor a declared
    submodule can escape the same policy.

    Every successful clone is digest-pinned (#404): pass `commit` (a full 40-
    or 64-hex digest) to name the object yourself, or omit it and the tool
    resolves the vetted remote's HEAD via `git_remote_tip` first. The pinned
    digest is fetched by itself, checked out, and re-verified against HEAD,
    so a branch ref moving between resolution and fetch (TOCTOU) cannot
    change what gets built; the result reports the proven digest as
    `head_commit` and `pinned_commit` for the audit trail. `require_signed`
    additionally demands `git verify-commit` accept the pinned commit.

    Signature provenance can also be a deployment-wide policy: when
    MAISTRO_GIT_CLONE_TRUSTED_SIGNERS names full OpenPGP key fingerprints,
    every successful clone must land on a commit carrying a
    cryptographically good signature by one of those keys, and the result
    then reports `signature_verified: True`. Without the anchor, transport
    authentication plus the digest pin is the policy.

    The transport whitelist is not scoped to this call: it is persisted into
    the clone's local config, and every git command this server later runs in
    the workspace re-applies it, so a ref checkout cannot drop the workspace
    back onto an unauthenticated transport (a hostile .gitmodules is rejected
    at clone time; a server-issued `git submodule update` still runs pinned).
    """
    try:
        _validate_clone_url(url)
    except ClonePolicyError as exc:
        return _blocked_clone_source_result(exc)
    try:
        dest = _validate_git_workspace(dest)
    except ValueError:
        return _blocked_workspace_result(dest)

    pin, pin_failure = _parse_commit_pin(commit)
    if pin_failure is not None:
        return pin_failure
    if pin is None:
        # No caller-supplied identity: resolve the vetted remote's HEAD to a
        # digest first, so the checkout is always proven to be a named object
        # — no successful clone is unpinned.
        resolved = await git_remote_tip(url, timeout=timeout)
        if not resolved["success"]:
            return resolved
        pin = str(resolved["commit"])

    result = await _clone_and_maybe_pin(url, dest, pin, timeout)
    if not result.get("success"):
        return result
    if require_signed:
        signature_failure = await _verify_commit_signature(dest, pin)
        if signature_failure is not None:
            return signature_failure
    # Deployment-wide trust anchor (MAISTRO_GIT_CLONE_TRUSTED_SIGNERS): the
    # signature policy on top of digest identity — a no-op when unset.
    return await _enforce_signature_policy(dest, result, timeout)


async def _clone_and_maybe_pin(
    url: str, dest: str, commit: str | None, timeout: int
) -> dict[str, Any]:
    """Run the hardened clone subprocess and prove the landed identity.

    `commit` is a full digest by the time this runs — the caller's pin or
    `git_remote_tip`'s resolution — and the clone is rejected unless the
    checked out HEAD is exactly that object. On success the result carries
    the proven digest as both `head_commit` and `pinned_commit`.
    """
    try:
        output, code = await _run_git_clone(url, dest, timeout)
    except FileNotFoundError:
        return fail(
            stdout="git binary not found",
            error_code="git_not_found",
            suggested_action="Ensure git is installed in the execution environment.",
        )
    except TimeoutError:
        return fail(
            stdout=f"git clone timed out after {timeout}s",
            exit_code=124,
            error_code="git_clone_timeout",
            recoverable=True,
            suggested_action="Retry with a longer timeout, or check repo size/network conditions.",
        )
    if code != 0:
        return fail(
            stdout=output,
            exit_code=code,
            error_code="git_clone_failed",
            recoverable=True,
            suggested_action="Verify the URL is reachable and dest doesn't already exist, then retry.",
        )
    verified = await _verify_cloned_source(dest, pin=commit)
    if not verified.get("ok"):
        return verified
    return ok(
        stdout=output,
        exit_code=code,
        head_commit=verified["head_commit"],
        pinned_commit=commit,
    )


def _parse_commit_pin(commit: str | None) -> tuple[str | None, dict[str, Any] | None]:
    """Normalize an optional commit pin; only full digests are identities."""
    if commit is None:
        return None, None
    if not _COMMIT_DIGEST_RE.match(commit):
        return None, fail(
            stdout=f"Blocked: commit pin must be a full 40- or 64-hex digest: {commit}",
            error_code="invalid_commit_pin",
            suggested_action=(
                "Resolve the branch to its full commit digest (git rev-parse) "
                "and pass that — branch names and short SHAs are not identities."
            ),
        )
    return commit.lower(), None


async def _run_git_clone(url: str, dest: str, timeout: int) -> tuple[str, int]:
    """Run the hardened shallow clone subprocess; returns (output, exit_code).

    Raises FileNotFoundError / TimeoutError for the caller to map onto its
    structured failures.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *_CLONE_CONFIG_HARDENING,
        "clone",
        "--depth=1",
        "--",
        url,
        dest,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    output = stdout.decode() if stdout else "Cloned"
    return output, proc.returncode or 0


@mcp.tool()
async def git_branch(workspace: str, name: str, checkout: bool = True) -> dict[str, Any]:
    """Create a new branch, checking it out by default."""
    if checkout:
        return await _git(workspace, "checkout", "-b", name)
    return await _git(workspace, "branch", name)


@mcp.tool()
async def git_add(workspace: str) -> dict[str, Any]:
    """Stage all changes (git add -A) without committing. Lets callers inspect
    the staged diff (git_diff staged=True) before git_commit decides what ships;
    git_commit's sensitive-file unstaging still runs at commit time."""
    return await _git(workspace, "add", "-A")


# File patterns that should never be staged
_SENSITIVE_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "credentials.json",
    "service-account.json",
    "secrets.yaml",
    "id_rsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
)


@mcp.tool()
async def git_commit(workspace: str, message: str, add_all: bool = True) -> dict[str, Any]:
    """Stage and commit changes. Sensitive files (.env, *.pem, id_rsa, etc.) are
    automatically unstaged even if add_all matched them."""
    if add_all:
        await _git(workspace, "add", "-A")
        # Unstage sensitive files if accidentally staged
        for pattern in _SENSITIVE_PATTERNS:
            await _git(workspace, "reset", "HEAD", "--", pattern)
    return await _git(workspace, "commit", "-m", message)


@mcp.tool()
async def git_push(
    workspace: str, branch: str | None = None, set_upstream: bool = True
) -> dict[str, Any]:
    """Push commits to remote."""
    if branch is not None and (branch.startswith("-") or not _BRANCH_NAME_RE.match(branch)):
        return fail(
            stdout=f"Blocked: invalid branch name: {branch}",
            error_code="invalid_branch_name",
            suggested_action="Use a branch name matching [A-Za-z0-9._/-]+ that doesn't start with '-'.",
        )
    args = ["push"]
    if set_upstream:
        args.extend(["-u", "origin"])
    if branch:
        args.append(branch)
    return await _git(workspace, *args)


@mcp.tool()
async def git_diff(workspace: str, staged: bool = False) -> dict[str, Any]:
    """Show the line-level diff of changes. Use git_status instead if you
    only need the list of changed files, not their content."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    return await _git(workspace, *args)


@mcp.tool()
async def git_status(workspace: str) -> dict[str, Any]:
    """Show the short list of changed files. Use git_diff instead if you
    need the actual line changes, not just which files changed."""
    return await _git(workspace, "status", "--short")


@mcp.tool()
async def git_log(
    workspace: str, limit: Annotated[int, Field(ge=1, le=200)] = 10
) -> dict[str, Any]:
    """Show recent commits as structured {sha, message} records."""
    result = await _git(workspace, "log", "--oneline", f"-{limit}")
    if result["success"]:
        result["commits"] = _parse_log_lines(result["stdout"])
    return result


@mcp.tool()
async def github_create_pr(
    repo: str,
    branch: str,
    title: str,
    body: str,
    base: str = "main",
) -> dict[str, Any]:
    """Create a GitHub pull request via the gh CLI.

    Idempotent: retrying with identical repo/branch/title/body/base within
    5 minutes returns the original result (marked deduplicated=True)
    instead of opening a duplicate PR. Use github_get_pr afterward to check
    review/merge status.
    """
    key = _pr_cache_key(repo, branch, title, body, base)
    cached = _pr_cache.get(key)
    if cached is not None and time.monotonic() - cached["cached_at"] < _PR_CACHE_TTL_S:
        return {**cached["result"], "deduplicated": True}

    result = await create_pr(repo, branch, title, body, base)
    if not result["success"]:
        return fail(
            stdout=result["output"],
            exit_code=result["exit_code"],
            error_code="gh_pr_create_failed",
            recoverable=True,
            suggested_action="Check stdout for the gh CLI error — common causes are an unpushed branch or an existing PR for this branch.",
        )
    response = ok(stdout=result["output"], url=result["url"])
    _pr_cache[key] = {"result": response, "cached_at": time.monotonic()}
    return response


@mcp.tool()
async def github_get_pr(repo: str, number: int) -> dict[str, Any]:
    """Get a pull request's title, state, body, changed files, and reviews.

    Use github_list_issues instead for issues — issues and PRs are
    different objects even when a repo shares their numbering.
    """
    result = await get_pr(repo, number)
    if "error" in result:
        return fail(
            stdout=str(result["error"]),
            error_code="gh_pr_fetch_failed",
            recoverable=True,
            suggested_action="Verify the PR number and repo (owner/name), then retry.",
        )
    return ok(stdout=result.get("title", ""), **result)


@mcp.tool()
async def github_list_issues(
    repo: str, limit: Annotated[int, Field(ge=1, le=100)] = 10
) -> dict[str, Any]:
    """List open GitHub issues, with bodies truncated to keep the response small.

    Use github_get_pr instead for pull requests.
    """
    issues = await list_issues(repo, limit)
    summary = f"{len(issues)} open issue(s)" if issues else "No open issues"
    return ok(stdout=summary, issues=issues, issue_count=len(issues))
