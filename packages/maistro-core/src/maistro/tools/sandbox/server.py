"""Sandbox MCP server — exposes Docker sandbox operations as MCP tools.

This FastMCP server provides tools for:
- exec: Run commands in the sandbox
- read: Read files from the workspace
- write: Write files to the workspace
- glob: Find files by name pattern
- grep: Search file contents by pattern
"""

from __future__ import annotations

import asyncio
import shlex
from typing import Annotated, Any

import structlog
from fastmcp import FastMCP
from pydantic import Field

from maistro.observability.metrics import sandbox_containers_active
from maistro.security.dangerous_tools import is_blocked_path, is_dangerous_command
from maistro.tools.result import fail, ok
from maistro.tools.sandbox.docker import SandboxContainer, create_sandbox

logger = structlog.get_logger()

mcp = FastMCP("sandbox", instructions="Docker sandbox for isolated code execution")

# Active sandbox containers, keyed by workspace path
_containers: dict[str, SandboxContainer] = {}
_container_lock = asyncio.Lock()


async def _get_or_create(workspace: str) -> SandboxContainer:
    """Get an existing container for this workspace or create one."""
    async with _container_lock:
        existing = _containers.get(workspace)
        if existing is not None:
            if existing.expired:
                logger.info("sandbox_ttl_expired", workspace=workspace)
                await existing.destroy()
                del _containers[workspace]
            else:
                return existing

        container = await create_sandbox(workspace)
        _containers[workspace] = container
        sandbox_containers_active.set(len(_containers))
        return container


async def cleanup_all_containers() -> None:
    """Destroy all active sandbox containers. Called during shutdown."""
    async with _container_lock:
        count = len(_containers)
        for workspace, container in list(_containers.items()):
            try:
                await container.destroy()
            except Exception:
                logger.exception("sandbox_cleanup_error", workspace=workspace)
        _containers.clear()
        sandbox_containers_active.set(0)
    logger.info("all_sandboxes_cleaned_up", count=count)


def _blocked_path_result(path: str) -> dict[str, Any]:
    return fail(
        stdout=f"Blocked: access to '{path}' is not allowed",
        error_code="blocked_path",
        suggested_action="Choose a relative workspace path outside blocked locations, traversal, or secrets.",
    )


def _check_path(path: str) -> dict[str, Any] | None:
    """Return a fail result if path is blocked, else None."""
    if is_blocked_path(path):
        return _blocked_path_result(path)
    try:
        SandboxContainer._safe_path("/workspace", path)
    except ValueError:
        return _blocked_path_result(path)
    return None


def _parse_grep_matches(output: str) -> list[dict[str, Any]]:
    """Parse `grep -n` output ('path:line:text') into structured records."""
    matches: list[dict[str, Any]] = []
    for line in output.splitlines():
        path, sep, rest = line.partition(":")
        if not sep:
            continue
        line_no, sep2, text = rest.partition(":")
        if not sep2 or not line_no.isdigit():
            continue
        matches.append({"path": path, "line": int(line_no), "text": text})
    return matches


@mcp.tool()
async def sandbox_exec(
    workspace: str,
    command: str,
    timeout: Annotated[int, Field(ge=1, le=300)] = 60,
) -> dict[str, Any]:
    """Execute a shell command in the sandbox container.

    Use this for running builds, tests, or scripts. To just inspect a file's
    contents use sandbox_read instead — it's cheaper and doesn't risk
    matching a dangerous-command pattern.
    """
    violations = is_dangerous_command(command)
    if violations:
        logger.warning("dangerous_command_blocked", command=command, violations=violations)
        return fail(
            stdout=f"Blocked: command matched dangerous patterns: {', '.join(violations)}",
            error_code="dangerous_command",
            suggested_action="Rewrite the command without the matched dangerous pattern and retry.",
        )

    container = await _get_or_create(workspace)
    exit_code, output = await container.exec(command, timeout=timeout)
    if exit_code == 0:
        return ok(stdout=output, exit_code=exit_code)
    return fail(
        stdout=output,
        exit_code=exit_code,
        error_code="command_failed",
        recoverable=True,
        suggested_action="Inspect stdout for the failure reason, then correct and retry the command.",
    )


@mcp.tool()
async def sandbox_read(workspace: str, path: str) -> dict[str, Any]:
    """Read a file from the sandbox workspace.

    Use sandbox_glob first if you're not sure the path exists.
    """
    if err := _check_path(path):
        return err
    container = await _get_or_create(workspace)
    try:
        content = await container.read_file(path)
        return ok(stdout=content, path=path)
    except FileNotFoundError as e:
        return fail(
            stdout=str(e),
            path=path,
            error_code="file_not_found",
            suggested_action="Check the path with sandbox_glob before reading.",
        )


@mcp.tool()
async def sandbox_write(workspace: str, path: str, content: str) -> dict[str, Any]:
    """Write a file to the sandbox workspace, overwriting it if it exists."""
    if err := _check_path(path):
        return err
    container = await _get_or_create(workspace)
    try:
        await container.write_file(path, content)
        return ok(stdout=f"Written: {path}", path=path)
    except OSError as e:
        return fail(
            stdout=str(e),
            path=path,
            error_code="write_failed",
            recoverable=True,
            suggested_action="Verify the parent directory exists in the workspace and retry.",
        )


@mcp.tool()
async def sandbox_glob(workspace: str, pattern: str) -> dict[str, Any]:
    """Find files by NAME pattern (e.g. '**/*.py') in the workspace.

    Use sandbox_grep instead if you're searching file CONTENTS rather than
    names. Returns at most 100 paths.
    """
    if err := _check_path(pattern):
        return err
    container = await _get_or_create(workspace)
    safe_pattern = shlex.quote(SandboxContainer._safe_path("/workspace", pattern))
    _exit_code, output = await container.exec(
        f"find /workspace -path {safe_pattern} -type f 2>/dev/null | head -100"
    )
    files = [f for f in output.strip().splitlines() if f] if output else []
    return ok(stdout=output or "No files found", files=files, file_count=len(files))


@mcp.tool()
async def sandbox_grep(workspace: str, pattern: str, path: str = ".") -> dict[str, Any]:
    """Search file CONTENTS for a regex pattern in the workspace.

    Use sandbox_glob instead if you're searching file NAMES rather than
    contents. Returns at most 50 matches as structured {path, line, text}
    records.
    """
    if err := _check_path(path):
        return err
    container = await _get_or_create(workspace)
    safe_pattern = shlex.quote(pattern)
    safe_path = shlex.quote(SandboxContainer._safe_path("/workspace", path))
    _exit_code, output = await container.exec(
        f"grep -rn -- {safe_pattern} {safe_path} 2>/dev/null | head -50"
    )
    matches = _parse_grep_matches(output)
    return ok(stdout=output or "No matches found", matches=matches, match_count=len(matches))


@mcp.tool()
async def sandbox_destroy(workspace: str) -> dict[str, Any]:
    """Destroy the sandbox container for a workspace, freeing its resources."""
    async with _container_lock:
        container = _containers.pop(workspace, None)
    if container:
        await container.destroy()
        sandbox_containers_active.set(len(_containers))
        return ok(stdout=f"Sandbox destroyed for {workspace}")
    return fail(
        stdout="No sandbox found for this workspace",
        error_code="sandbox_not_found",
        suggested_action="No action needed — there is no running sandbox for this workspace.",
    )
