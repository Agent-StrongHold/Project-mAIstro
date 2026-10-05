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
import urllib.parse
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from maistro.tools.git.github import create_pr, get_pr, list_issues
from maistro.tools.result import fail, ok
from maistro.tools.sandbox.workspace import validate_workspace_path

mcp = FastMCP("git", instructions="Git and GitHub operations")

GIT_CLONE_TIMEOUT = 300

# Clone-source policy (#404). Anything this tool clones is candidate source
# the RSI cycle branches, patches, builds and tests, so the gate is an
# allowlist of authenticated transports — not a blocklist:
#
# * `git://` is unauthenticated and unencrypted — no transport integrity, no
#   server identity — so an on-path attacker can substitute repository
#   content. It gets its own error code so the policy violation is
#   distinguishable from a typo, and the check is case-insensitive because
#   git parses remote schemes per RFC 3986 (`GIT://` names the same
#   transport). The verdict is not overridable by the `_ALLOWED_CLONE_SCHEMES`
#   test knob, which exists only to admit `file://` hermetic origins.
# * The scheme allowlist admits `https://` and `ssh://` only. Any other
#   scheme — including scp-style `git@host:path` remotes and a bare
#   `-`-prefixed string, which `argv` would otherwise hand to git as a flag —
#   is rejected before the subprocess runs.
# * Hosts: an https/ssh URL must also name a host on the explicit source
#   allowlist (`_ALLOWED_CLONE_HOSTS`; deployments override with
#   `MAISTRO_GIT_CLONE_ALLOWED_HOSTS`, comma-separated). The *repository*
#   half of the source policy is the commit digest pin (`git_clone(commit=...)`):
#   whatever is checked out is proven to be the requested object, so a moved
#   ref or a hostile mirror cannot substitute content.
# * Local paths are "verified local sources" only when they pass the same
#   workspace-root validation the destination already undergoes.
#
# The argv carries two `-c` pins that make the redirect/submodule arguments
# executable instead of architectural (verified against real git):
# * `protocol.git.allow=never` — git itself refuses the git:// transport
#   ("fatal: transport 'git' not allowed") even when a URL re-introduces it
#   via a redirect or a `.gitmodules` entry. Proven below: under this pin,
#   `git submodule update` against a `git://` URL fails in transport
#   selection, before any connection.
# * `http.followRedirects=false` — git refuses to follow redirects at all, so
#   no server response can move the fetch to a URL the scheme/host policy
#   never vetted. git's default (`initial`) still follows the initial
#   request's redirect even to a different host, which would let an allowed
#   host's open redirect pick the real source; `false` closes that, at the
#   price of failing loudly on moved-repo redirects (retry with the canonical
#   URL, which passes policy itself). This server never runs `git submodule
#   update`; the pin above means even a hypothetical submodule fetch over
#   git:// dies in transport selection.
#
# Signature policy (#404 AC3's "identity/signature policy" clause): the
# deployment names its trust anchor in `MAISTRO_GIT_CLONE_TRUSTED_SIGNERS`
# (comma-separated full OpenPGP key fingerprints; the corresponding public
# keys must be in the runner's keyring, which is what `git log %G?` consults).
# With the anchor set, every clone must land on a commit whose signature is
# cryptographically good (`%G?` G, or U — good but locally untrusted) and made
# by a trusted key (`%GP`/`%GF` fingerprint match); anything else fails with
# its own error code. Without the anchor the policy stays digest-identity over
# authenticated transport (`commit=` pin + host allowlist) — that default is
# documented here, not silent: a deployment that wants provenance signs its
# candidate sources and configures the anchor.
_ALLOWED_CLONE_SCHEMES = ("https://", "ssh://")
_DEFAULT_ALLOWED_CLONE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "ssh.github.com")
_ALLOWED_CLONE_HOSTS: tuple[str, ...] = _DEFAULT_ALLOWED_CLONE_HOSTS
# A pin is only a pin if it names an object, not a label a remote can repoint:
# full sha1/sha256 hex digests only — no short shas, no ref names.
_COMMIT_DIGEST_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class ClonePolicyError(ValueError):
    """A clone source failed the #404 transport/host policy."""

    def __init__(self, message: str, error_code: str, suggested_action: str) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.suggested_action = suggested_action


def _clone_policy_hosts() -> tuple[str, ...]:
    """Hosts allowed as clone sources: the deployment's env override when
    set, else the module allowlist (which hermetic tests monkeypatch)."""
    override = os.environ.get("MAISTRO_GIT_CLONE_ALLOWED_HOSTS", "")
    hosts = tuple(host.strip().lower() for host in override.split(",") if host.strip())
    return hosts or _ALLOWED_CLONE_HOSTS


# #404 AC3 signature trust anchor: full OpenPGP fingerprints (40/64 hex,
# spaces allowed) this deployment trusts to sign candidate clone sources.
_TRUSTED_SIGNERS_ENV = "MAISTRO_GIT_CLONE_TRUSTED_SIGNERS"
# git log %G? verdicts that mean "cryptographically good signature": G is
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


def _url_host(url: str) -> str | None:
    """Lowercased hostname of a schemed URL, or None if it has none.

    urlsplit puts everything before the last `@` of the authority into
    user-info, so `https://github.com@evil.com/x` is host evil.com (refused)
    and `https://evil@github.com/x` is host github.com (allowed) — matching
    what git/curl will actually connect to.
    """
    try:
        host = urllib.parse.urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def validate_clone_source(url: str) -> None:
    """Raise :class:`ClonePolicyError` unless `url` names a source the #404
    clone policy allows.

    One function, every surface: the MCP tool below and the RSI harvest cloud
    path (`maistro_rsi.__main__`) both gate through this, so a URL rejected
    here is rejected there — there is no second policy to drift.
    """
    lowered = url.lower()
    if lowered.startswith("git://"):
        raise ClonePolicyError(
            f"Blocked: unauthenticated transport: {url}",
            "blocked_unauthenticated_transport",
            "Use https:// or ssh:// — the git:// protocol provides no "
            "transport encryption or server authentication (#404).",
        )
    if url.startswith(_ALLOWED_CLONE_SCHEMES):
        if lowered.startswith(("https://", "ssh://")):
            host = _url_host(url)
            if host is None or host not in _clone_policy_hosts():
                raise ClonePolicyError(
                    f"Blocked: clone host is not on the source allowlist: {url}",
                    "blocked_clone_host",
                    "Clone from a host on MAISTRO_GIT_CLONE_ALLOWED_HOSTS "
                    f"(default: {_DEFAULT_ALLOWED_CLONE_HOSTS}), or set that "
                    "variable for this deployment.",
                )
        return
    _raise_for_unvetted_source_spelling(url)


def _raise_for_unvetted_source_spelling(url: str) -> None:
    """Refuse the source forms the allowlist never named, and vet bare paths
    as the one remaining door (verified local sources)."""
    # A schemed URL that missed the allowlist is refused as a scheme; so is
    # scp-style `git@host:path` syntax, which git would silently treat as
    # ssh:// — a source form the policy above never names.
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url) or (
        "@" in url and ":" in url.split("@", 1)[1] and "://" not in url
    ):
        raise ClonePolicyError(
            f"Blocked: url scheme is not allowed: {url}",
            "blocked_url_scheme",
            f"Use a URL starting with one of {_ALLOWED_CLONE_SCHEMES}.",
        )
    # Last door: a verified local source — same workspace-root validation the
    # destination must pass.
    try:
        validate_workspace_path(url)
    except ValueError as exc:
        raise ClonePolicyError(
            f"Blocked: {exc}",
            "blocked_url_scheme",
            f"Use a URL starting with one of {_ALLOWED_CLONE_SCHEMES}, or a path "
            "inside an allowed workspace root.",
        ) from None


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


@mcp.tool()
async def git_clone(
    url: str,
    dest: str,
    timeout: Annotated[int, Field(ge=1, le=900)] = GIT_CLONE_TIMEOUT,
    commit: str | None = None,
) -> dict[str, Any]:
    """Clone a git repository (shallow, depth=1).

    Only authenticated, policy-vetted sources are accepted (#404): https:// or
    ssh:// to a host on the clone-source allowlist, or a verified local path.
    `git://` has its own rejection — it provides neither encryption nor server
    authentication, and anything it clones is candidate source the RSI
    self-modification cycle may execute.

    Pass `commit` (full 40- or 64-hex digest) to pin the checkout: the digest —
    not a ref name — is fetched directly and `rev-parse HEAD` must equal it
    after every fetch, so a ref that moves mid-clone (TOCTOU) cannot change
    what the caller receives. The checkout is exactly the requested digest or
    the call fails.

    Signature policy (#404): when the deployment sets
    `MAISTRO_GIT_CLONE_TRUSTED_SIGNERS` (comma-separated OpenPGP key
    fingerprints), the landed HEAD commit must additionally carry a
    cryptographically good signature by one of those keys; the result then
    reports `signature_verified: True`. Without the anchor, transport
    authentication plus the digest pin is the policy.
    """
    try:
        validate_clone_source(url)
    except ClonePolicyError as exc:
        return fail(
            stdout=exc.message,
            error_code=exc.error_code,
            suggested_action=exc.suggested_action,
        )
    if commit is not None:
        if not _COMMIT_DIGEST_RE.match(commit):
            return fail(
                stdout=f"Blocked: commit pin must be a full 40- or 64-hex digest: {commit}",
                error_code="blocked_commit_digest",
                suggested_action=(
                    "Pass the full digest (git rev-parse <ref>). A short sha or a "
                    "ref name can be repointed by the remote; a digest cannot."
                ),
            )
        commit = commit.lower()
    try:
        dest = _validate_git_workspace(dest)
    except ValueError:
        return _blocked_workspace_result(dest)
    return await _clone_and_maybe_pin(url, dest, commit, timeout)


async def _clone_and_maybe_pin(
    url: str, dest: str, commit: str | None, timeout: int
) -> dict[str, Any]:
    """Run the policy-pinned clone subprocess; verify the digest pin if set."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            # Executable #404 enforcement (see the constant block above): git
            # itself refuses the git:// transport and refuses to follow
            # redirects, whatever a URL or .gitmodules entry asks for.
            "-c",
            "protocol.git.allow=never",
            "-c",
            "http.followRedirects=false",
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
        code = proc.returncode or 0
        if code == 0 and commit is not None:
            pinned = await _verify_pinned_checkout(dest, commit, timeout, output)
            if not pinned["success"]:
                return pinned
            return await _enforce_signature_policy(dest, pinned, timeout)
        if code == 0:
            return await _enforce_signature_policy(dest, ok(stdout=output, exit_code=code), timeout)
        return fail(
            stdout=output,
            exit_code=code,
            error_code="git_clone_failed",
            recoverable=True,
            suggested_action="Verify the URL is reachable and dest doesn't already exist, then retry.",
        )
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
        return fail(
            stdout=(result.get("stdout", "") or "")
            + f"\ncommit signature policy: HEAD is not signed ({verdict or 'unreadable'})",
            error_code="commit_signature_missing",
            suggested_action=(
                f"{_TRUSTED_SIGNERS_ENV} requires signed candidate sources; the "
                "cloned HEAD carries no valid OpenPGP signature. Do not use this "
                "workspace."
            ),
        )
    if verdict not in _GOOD_SIGNATURE_STATUSES:
        return fail(
            stdout=(result.get("stdout", "") or "")
            + f"\ncommit signature policy: HEAD signature is not good ({verdict})",
            error_code="commit_signature_invalid",
            suggested_action=(
                f"{_TRUSTED_SIGNERS_ENV} is set, so the cloned HEAD must carry a "
                f"good signature; git reports {verdict!r}. The source or the local "
                "keyring is wrong — do not use this workspace."
            ),
        )
    fprs = await _git(dest, "log", "-1", "--pretty=format:%GF%n%GP", timeout=timeout)
    landed = (
        {
            line.strip().replace(" ", "").lower()
            for line in fprs["stdout"].splitlines()
            if line.strip()
        }
        if fprs["success"]
        else set()
    )
    if not landed & trusted:
        return fail(
            stdout=(result.get("stdout", "") or "")
            + f"\ncommit signature policy: signer {sorted(landed) or 'unknown'} "
            "is not on the trusted-signer allowlist",
            error_code="commit_signature_untrusted",
            suggested_action=(
                f"The signature is good but the key is not one of the fingerprints "
                f"in {_TRUSTED_SIGNERS_ENV}. Do not use this workspace."
            ),
        )
    augmented = dict(result)
    augmented["signature_verified"] = True
    return augmented


async def _verify_pinned_checkout(
    dest: str, commit: str, timeout: int, clone_output: str
) -> dict[str, Any]:
    """Pin a finished clone to `commit` and prove the checkout IS that object.

    The digest is fetched directly (no ref name is ever trusted), and the
    final `rev-parse HEAD` verdict runs after all fetching — if a ref moved at
    any point (TOCTOU), the mismatch fails the call instead of silently
    handing the caller different content than the digest they audited.
    """
    head = await _git(dest, "rev-parse", "HEAD", timeout=timeout)
    if head["success"] and head["stdout"].strip() == commit:
        # Fast path: the pinned digest is the default branch's tip, which the
        # clone already fetched — the checkout already IS the object.
        return ok(
            stdout=f"{clone_output}Pinned to commit {commit} (verified)\n",
            exit_code=0,
            pinned_commit=commit,
        )
    fetch = await _git(dest, "fetch", "--depth=1", "origin", commit, timeout=timeout)
    if not fetch["success"]:
        return fail(
            stdout=fetch["stdout"],
            exit_code=fetch.get("exit_code", 1),
            error_code="commit_fetch_failed",
            recoverable=True,
            suggested_action=(
                f"Could not fetch the pinned digest {commit}: verify it exists on "
                "the remote and that the remote permits fetch-by-sha. The clone "
                "was not verified — do not use the workspace."
            ),
        )
    checkout = await _git(dest, "checkout", "--detach", "FETCH_HEAD", timeout=timeout)
    if not checkout["success"]:
        return fail(
            stdout=checkout["stdout"],
            exit_code=checkout.get("exit_code", 1),
            error_code="git_command_failed",
            recoverable=True,
            suggested_action="Inspect stdout; the pinned checkout could not be made.",
        )
    verify = await _git(dest, "rev-parse", "HEAD", timeout=timeout)
    verified = verify["stdout"].strip() if verify["success"] else ""
    if verified != commit:
        return fail(
            stdout=f"pinned {commit} but checkout is {verified or 'unknown'}",
            error_code="commit_identity_mismatch",
            suggested_action=(
                "The fetched content does not match the pinned digest; the source "
                "moved or lied mid-fetch. Do not use this workspace."
            ),
        )
    return ok(
        stdout=f"{clone_output}Pinned to commit {commit} (verified)\n",
        exit_code=0,
        pinned_commit=commit,
    )


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
