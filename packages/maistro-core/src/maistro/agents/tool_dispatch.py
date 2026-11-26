"""Preserve provider tool-call identity without changing legacy executors."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import getattr_static
from typing import Any, cast

from maistro.types.tool import ToolCall


class ToolCallExecutor:
    """Adapt an identity-aware hook to the existing ``(name, args)`` contract.

    Legacy calls have no provider ID or Agent identity. Consumers requiring
    model-effect identity must refuse that absence rather than invent a key.
    """

    def __init__(self, execute: Callable[[ToolCall, str, int, int], Awaitable[Any]]) -> None:
        self._execute = execute

    async def __call__(self, name: str, args: dict[str, Any]) -> Any:
        return await self.execute_tool_call(ToolCall(id="", name=name, arguments=args))

    async def execute_tool_call(
        self,
        call: ToolCall,
        *,
        agent_name: str = "",
        delegation_depth: int = 0,
        tool_round: int = 0,
    ) -> Any:
        return await self._execute(call, agent_name, delegation_depth, tool_round)


async def dispatch_tool_call(
    executor: Any,
    call: ToolCall,
    *,
    agent_name: str = "",
    delegation_depth: int = 0,
    tool_round: int = 0,
) -> Any:
    """Use an explicitly supplied hook, otherwise the original executor API."""
    # Dynamic proxies (including AsyncMock) may fabricate any attribute. An
    # optional hook must actually exist before it can replace their callable.
    if getattr_static(executor, "execute_tool_call", None) is not None:
        hook = getattr(executor, "execute_tool_call", None)
        if callable(hook):
            return await cast(Callable[..., Awaitable[Any]], hook)(
                call,
                agent_name=agent_name,
                delegation_depth=delegation_depth,
                tool_round=tool_round,
            )
    return await executor(call.name, call.arguments)
