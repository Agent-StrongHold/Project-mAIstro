from __future__ import annotations

from typing import Protocol, runtime_checkable

from maistro.credentials.types import CredentialRecord, PoolStats


@runtime_checkable
class CredentialProvider(Protocol):
    async def acquire(self, provider: str) -> CredentialRecord: ...

    async def release(
        self,
        provider: str,
        key_id: str,
        status: int,
        error: Exception | None = None,
    ) -> None: ...

    async def get_stats(self, provider: str) -> PoolStats: ...
