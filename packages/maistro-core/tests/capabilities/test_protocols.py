from __future__ import annotations

from maistro.capabilities.protocols import CapabilityProvider
from maistro.capabilities.types import ProviderHealth


class _FakeProvider:
    name = "fake"
    slot = "web_search"
    trust_tier = "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)


def test_fake_provider_satisfies_protocol():
    assert isinstance(_FakeProvider(), CapabilityProvider)
