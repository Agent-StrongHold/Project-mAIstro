"""Injectable async HTTP seam for capability providers (testable; httpx-backed default)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AsyncHttp(Protocol):
    async def get_json(self, path: str) -> dict[str, Any]: ...
    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]: ...
