"""Host-owned tool authority used at the Agent invocation boundary.

Agent declarations describe the eligible set; they are not an executor.  This
module turns that declaration into the narrow callback handed to a strategy so
an internally selected call cannot bypass the same allowlist as a model call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any


class ToolAuthorityError(PermissionError):
    """A tool call is outside the effective Agent capability envelope."""

    code = "tool_not_authorized"


class ToolSchemaError(ValueError):
    """A requested tool has no governed argument schema."""

    code = "tool_schema_missing"


_WRITE_TOOLS = frozenset(
    {
        "write_file",
        "file_ops.write",
        "sandbox_write",
        "git_commit",
        "git_push",
    }
)


def _path_from_args(args: dict[str, Any]) -> str | None:
    value = args.get("path")
    return value if isinstance(value, str) else None


def _unsafe_relative_path(path: str) -> bool:
    """Reject paths that can escape the workspace before glob matching."""
    if not path or "\x00" in path or "\\" in path:
        return True
    candidate = PurePosixPath(path)
    return candidate.is_absolute() or ".." in candidate.parts


class ToolAuthority:
    """The effective tool/write envelope for one running Agent.

    ``declared_tools`` comes from the Agent identity.  ``host_tools`` is an
    optional host-policy narrowing; it can never widen the declaration.  A
    non-empty write-scope declaration narrows write-capable tools to matching
    workspace-relative paths.  Empty scopes are left compatible with legacy
    non-path integrations, while path tools still require the executor's own
    workspace/path guard.
    """

    def __init__(
        self,
        declared_tools: Iterable[str],
        *,
        write_scopes: Iterable[str] = (),
        host_tools: Iterable[str] | None = None,
    ) -> None:
        declared = tuple(dict.fromkeys(declared_tools))
        host = None if host_tools is None else frozenset(host_tools)
        self.allowed_tools = (
            declared if host is None else tuple(name for name in declared if name in host)
        )
        self.write_scopes = tuple(write_scopes)

    def narrowed(self, host_tools: Iterable[str] | None) -> ToolAuthority:
        """Return this declaration intersected with a current host policy."""
        return ToolAuthority(
            self.allowed_tools,
            write_scopes=self.write_scopes,
            host_tools=host_tools,
        )

    def check(self, tool_name: str, args: dict[str, Any]) -> None:
        if tool_name not in self.allowed_tools:
            raise ToolAuthorityError(
                f"tool '{tool_name}' is not in the Agent's effective authorized tool set"
            )
        if tool_name in _WRITE_TOOLS and self.write_scopes:
            path = _path_from_args(args)
            if path is None or _unsafe_relative_path(path):
                raise ToolAuthorityError(
                    f"write path for tool '{tool_name}' is outside the Agent write scopes"
                )
            if not any(fnmatchcase(path, scope) for scope in self.write_scopes):
                raise ToolAuthorityError(
                    f"write path for tool '{tool_name}' is outside the Agent write scopes"
                )

    def wrap(
        self,
        executor: Callable[[str, dict[str, Any]], Awaitable[Any]],
    ) -> Callable[[str, dict[str, Any]], Awaitable[Any]]:
        """Return a fail-closed callback safe to pass to arbitrary strategies."""

        async def governed(tool_name: str, args: dict[str, Any]) -> Any:
            try:
                self.check(tool_name, args)
            except ToolAuthorityError as exc:
                return f"Error: {exc}"
            return await executor(tool_name, args)

        return governed


__all__ = ["ToolAuthority", "ToolAuthorityError", "ToolSchemaError"]
