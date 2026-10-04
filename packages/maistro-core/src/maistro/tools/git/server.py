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
# is hard-rejected first, even if the allowlist below is ever widened, and the
# `-c protocol.*` flags pin the same whitelist inside git itself (submodules
# and nested git invocations inherit it). Anything else — bare local paths,
# `scp`-like `host:path`, a `-`-prefixed string argv would hand to git as a
# flag — is rejected by parsing the URL, not prefix-matching it, so case
# (`GIT://`) and encoded spellings resolve to the same decision.
_FORBIDDEN_CLONE_SCHEMES = ("git://",)
_ALLOWED_CLONE_SCHEMES = ("https://", "ssh://")

# "Verified local sources": `file://` is clonable only when the scheme tuple
# above is explicitly widened AND the resolved source path sits under one of
# these roots. Empty by default — production refuses local sources outright;
# hermetic tests opt in exactly the way they relax ALLOWED_HOST_ROOTS.
_ALLOWED_LOCAL_SOURCE_ROOTS: tuple[str, ...] = ()


def _clone_host_allowlist() -> frozenset[str]:
    """Explicit host/repository policy, read per call so tests and deploys can
    set it via MAISTRO_GIT_CLONE_HOSTS (comma-separated hostnames). Empty = no
    host restriction beyond the transport policy; strict deployments pin the
    hosts a candidate source may come from."""
    raw = os.environ.get("MAISTRO_GIT_CLONE_HOSTS", "")
    return frozenset(host.strip().lower() for host in raw.split(",") if host.strip())


# Config hardening passed ahead of every clone — before the subcommand, so a
# URL can never override them:
# - protocol.allow=never plus explicit https/ssh allows and file=user pins the
#   git transport whitelist for this clone AND everything it triggers
#   (submodule fetches do not run as user-initiated transports, so a hostile
#   .gitmodules cannot reintroduce git:// or file:// from inside the tree).
# - http.followRedirects=false: an http(s) source cannot be silently
#   redirected to another host or downgraded off HTTPS — the clone fails
#   instead, and the same URL policy applies to whatever the caller asked for.
# - http.sslVerify=true: a stray system/global git config cannot disable
#   certificate verification.
_CLONE_CONFIG_HARDENING = (
    "-c",
    "protocol.allow=never",
    "-c",
    "protocol.https.allow=always",
    "-c",
    "protocol.ssh.allow=always",
    "-c",
    "protocol.file.allow=user",
    "-c",
    "http.followRedirects=false",
    "-c",
    "http.sslVerify=true",
)

# Commit pins must be full SHA-1 or SHA-256 digests — branch names and
# abbreviated SHAs can be re-pointed and are not an identity.
_COMMIT_PIN_RE = re.compile(r"^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")
_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class _ClonePolicyError(ValueError):
    """A clone source violated URL policy; carries its machine-readable code."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _check_clone_scheme_allowed(scheme: str, url: str) -> None:
    """Hard-deny unauthenticated transports, then allowlist the rest.

    The forbidden check runs before the allowlist check so a hostile config
    that widens _ALLOWED_CLONE_SCHEMES can never smuggle git:// back in.
    """
    if f"{scheme}://" in _FORBIDDEN_CLONE_SCHEMES:
        raise _ClonePolicyError(
            f"Blocked: unauthenticated clone transport is not allowed: {url}",
            "blocked_url_scheme",
        )
    if f"{scheme}://" not in tuple(s.lower() for s in _ALLOWED_CLONE_SCHEMES):
        raise _ClonePolicyError(f"Blocked: url scheme is not allowed: {url}", "blocked_url_scheme")


def _validate_remote_clone_host(parts: SplitResult, url: str) -> tuple[str, str]:
    """Gate remote (non-file) sources behind the explicit host policy."""
    host = (parts.hostname or "").lower()
    if not host:
        raise _ClonePolicyError(f"Blocked: url has no host: {url}", "blocked_url_scheme")
    allowlist = _clone_host_allowlist()
    if allowlist and host not in allowlist:
        raise _ClonePolicyError(
            f"Blocked: clone host is not in policy: {host}", "blocked_clone_host"
        )
    scheme = parts.scheme.lower()
    return scheme, host


def _validate_clone_url(url: str) -> tuple[str, str]:
    """Validate a clone *source* URL against the transport/host policy.

    Returns the normalized (scheme, hostname); raises :class:`_ClonePolicyError`
    otherwise. The same function validates submodule URLs, so redirects are
    refused at the transport level and every nested source is held to the
    identical rules.
    """
    if not url:
        raise _ClonePolicyError("Blocked: empty clone url", "blocked_url_scheme")
    if url.startswith("-"):
        raise _ClonePolicyError(
            f"Blocked: url must not start with '-': {url}", "blocked_url_scheme"
        )
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    _check_clone_scheme_allowed(scheme, url)
    if scheme == "file":
        return _validate_local_clone_source(parts, url)
    return _validate_remote_clone_host(parts, url)


def _validate_local_clone_source(parts: SplitResult, url: str) -> tuple[str, str]:
    """Gate `file://` sources: they are only clonable when explicitly opted
    into via _ALLOWED_CLONE_SCHEMES AND the resolved path sits under a verified
    local root (empty by default — production refuses local sources)."""
    if "file://" not in tuple(s.lower() for s in _ALLOWED_CLONE_SCHEMES):
        raise _ClonePolicyError(f"Blocked: url scheme is not allowed: {url}", "blocked_url_scheme")
    source = Path(url2pathname(parts.path)).resolve()
    for root in _ALLOWED_LOCAL_SOURCE_ROOTS:
        root_resolved = Path(root).resolve()
        if source == root_resolved or root_resolved in source.parents:
            return "file", "localhost"
    raise _ClonePolicyError(
        f"Blocked: local clone source is not under a verified root: {url}",
        "blocked_local_source",
    )


def _blocked_clone_source_result(exc: _ClonePolicyError) -> dict[str, Any]:
    return fail(
        stdout=str(exc),
        error_code=exc.error_code,
        suggested_action=(
            "Use an https:// or ssh:// URL for a host allowed by the configured "
            "clone policy (MAISTRO_GIT_CLONE_HOSTS); git:// and local paths are "
            "not accepted as candidate sources."
        ),
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
    """Enforce the signature policy on the pinned digest (fail closed)."""
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


async def _verify_cloned_source(
    dest: str, *, pin: str | None, require_signed: bool
) -> dict[str, Any]:
    """Post-clone identity checks on the fetched tree.

    Resolves HEAD, enforces an optional commit-digest pin (fetching the digest
    itself and detaching when the default branch moved — the TOCTOU guard), an
    optional signature policy, and validates every .gitmodules submodule URL
    against the same source policy as the top-level clone. Returns
    ``{"ok": True, "head_commit": <digest>}`` or a structured failure.
    """
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

    if require_signed and pin is not None:
        signature_failure = await _verify_commit_signature(dest, pin)
        if signature_failure is not None:
            return signature_failure

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
        except _ClonePolicyError as exc:
            return fail(
                stdout=str(exc),
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
async def git_clone(
    url: str,
    dest: str,
    timeout: Annotated[int, Field(ge=1, le=900)] = GIT_CLONE_TIMEOUT,
    commit: str | None = None,
    require_signed: bool = False,
) -> dict[str, Any]:
    """Clone a git repository (shallow, depth=1) under the source policy.

    Candidate sources must arrive over an authenticated transport (https:// or
    ssh://) for a host allowed by MAISTRO_GIT_CLONE_HOSTS; `git://` —
    unauthenticated and unencrypted — is always rejected, as are local paths
    unless a verified local root is configured. Redirects are refused and the
    git protocol whitelist is pinned, so neither a redirect, a protocol
    downgrade, nor a declared submodule can escape the same policy.

    Pass `commit` (a full 40- or 64-hex digest) to pin the checkout: the tool
    fetches that digest itself, detaches to it, and re-verifies HEAD, so a
    branch ref moving between resolution and fetch (TOCTOU) cannot change what
    gets built. `require_signed` additionally demands `git verify-commit`
    accept the pinned commit (ignored without `commit`). On success the
    resolved HEAD digest is returned as `head_commit` for the audit trail.
    """
    try:
        _validate_clone_url(url)
    except _ClonePolicyError as exc:
        return _blocked_clone_source_result(exc)
    try:
        dest = _validate_git_workspace(dest)
    except ValueError:
        return _blocked_workspace_result(dest)

    pin, pin_failure = _parse_commit_pin(commit)
    if pin_failure is not None:
        return pin_failure

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
    verified = await _verify_cloned_source(dest, pin=pin, require_signed=require_signed)
    if not verified.get("ok"):
        return verified
    return ok(stdout=output, exit_code=code, head_commit=verified["head_commit"])


def _parse_commit_pin(commit: str | None) -> tuple[str | None, dict[str, Any] | None]:
    """Normalize an optional commit pin; only full digests are identities."""
    if commit is None:
        return None, None
    if not _COMMIT_PIN_RE.match(commit):
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
