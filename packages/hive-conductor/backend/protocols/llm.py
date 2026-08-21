from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from models.schemas import ChatCompletionRequest


class LLMPort(Protocol):
    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]: ...

    def stream(self, req: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        """Yield OpenAI-style streaming chunks (``choices[].delta`` with ``content``
        and/or ``tool_calls`` fragments). Implemented as an async generator."""
        ...
