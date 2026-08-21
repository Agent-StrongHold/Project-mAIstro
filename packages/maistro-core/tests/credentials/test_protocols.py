"""Tests for maistro.credentials.protocols — CredentialProvider Protocol."""

from __future__ import annotations

from maistro.credentials.protocols import CredentialProvider
from maistro.credentials.types import CredentialRecord, PoolStats


class _FakeProvider:
    async def acquire(self, provider: str) -> CredentialRecord:
        raise NotImplementedError

    async def release(
        self,
        provider: str,
        key_id: str,
        status: int,
        error: Exception | None = None,
    ) -> None:
        pass

    async def get_stats(self, provider: str) -> PoolStats:
        raise NotImplementedError


class _NotAProvider:
    pass


class TestCredentialProviderProtocol:
    def test_conforming_class_is_instance(self) -> None:
        assert isinstance(_FakeProvider(), CredentialProvider)

    def test_non_conforming_class_is_not_instance(self) -> None:
        assert not isinstance(_NotAProvider(), CredentialProvider)
