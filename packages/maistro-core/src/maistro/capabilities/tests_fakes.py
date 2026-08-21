"""Reusable in-memory provider for capability tests."""

from __future__ import annotations

from maistro.capabilities.types import ProviderHealth


class FakeProvider:
    def __init__(self, name: str, slot: str, *, healthy: bool = True, tier: str = "t0") -> None:
        self._name, self._slot, self._healthy, self._tier = name, slot, healthy, tier

    @property
    def name(self) -> str:
        return self._name

    @property
    def slot(self) -> str:
        return self._slot

    @property
    def trust_tier(self) -> str:
        return self._tier

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=self._healthy)
