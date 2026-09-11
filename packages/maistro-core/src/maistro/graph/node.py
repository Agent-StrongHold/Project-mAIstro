"""Algorithm-level graph node protocols and bounded iteration helpers.

Physical Graph execution is owned by ``maistro.graph.durable_runs``. This
module intentionally contains no node lifecycle object or LLM execution loop;
those would create a second execution authority beside Run/NodeRun/Attempt.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from maistro.graph.types import AgentRole, GraphBlackboard


@runtime_checkable
class NodeExecutor(Protocol):
    """Provider seam for a durable node's capability implementation.

    Implementations produce a typed value for a caller that already owns the
    canonical Attempt. This protocol does not create or advance Graph
    lifecycle records and is not an execution entry point by itself.
    """

    async def run(
        self,
        *,
        role: AgentRole,
        system_prompt: str,
        user_prompt: str,
        blackboard: GraphBlackboard | None,
        output_type: type[BaseModel],
    ) -> BaseModel: ...


class IterationBudget:
    """Bound algorithmic work without owning Run or Attempt lifecycle."""

    def __init__(self, max_iterations: int) -> None:
        self._max = max_iterations
        self._consumed = 0

    def consume(self, count: int = 1) -> bool:
        if self._consumed + count > self._max:
            return False
        self._consumed += count
        return True

    @property
    def remaining(self) -> int:
        return max(0, self._max - self._consumed)

    @property
    def exhausted(self) -> bool:
        return self._consumed >= self._max

    @property
    def max_iterations(self) -> int:
        return self._max

    @property
    def consumed(self) -> int:
        return self._consumed


__all__ = ["IterationBudget", "NodeExecutor"]
