"""Git operations MCP server — clone, branch, commit, push, PR, diff.

Exposes git and GitHub operations as MCP tools for agents to use.
All tools return structured dicts with {success, exit_code, stdout, ...};
failures additionally carry {error_code, recoverable, suggested_action}.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from maistro.tools.git.github import create_pr, get_pr, list_issues
from maistro.tools.result import fail, ok
from maistro.tools.sandbox.workspace import validate_workspace_path

mcp = FastMCP("git", instructions="Git and GitHub operations")

GIT_CLONE_TIMEOUT = 300

# Schemes legitimate callers actually use (github_create_pr/selfbranch clone
# over https; ssh/git are kept for parity with normal git usage). Anything
# else — notably a bare `-`-prefixed string, which `argv` would otherwise
# hand straight to git as a flag — is rejected before the subprocess runs.
_ALLOWED_CLONE_SCHEMES = ("https://", "git://", "ssh://")
_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

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
    url: str, dest: str, timeout: Annotated[int, Field(ge=1, le=900)] = GIT_CLONE_TIMEOUT
) -> dict[str, Any]:
    """Clone a git repository (shallow, depth=1)."""
    if not url.startswith(_ALLOWED_CLONE_SCHEMES):
        return fail(
            stdout=f"Blocked: url scheme is not allowed: {url}",
            error_code="blocked_url_scheme",
            suggested_action=f"Use a URL starting with one of {_ALLOWED_CLONE_SCHEMES}.",
        )
    try:
        dest = _validate_git_workspace(dest)
    except ValueError:
        return _blocked_workspace_result(dest)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
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
        if code == 0:
            return ok(stdout=output, exit_code=code)
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
