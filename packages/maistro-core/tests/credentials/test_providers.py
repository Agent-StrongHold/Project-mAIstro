"""Tests for maistro.credentials.providers — credential provider catalog."""

from __future__ import annotations

from maistro.credentials.providers import PM_CREDENTIAL_PROVIDERS, get_provider


class TestGetProvider:
    def test_returns_matching_provider(self) -> None:
        existing_id = PM_CREDENTIAL_PROVIDERS[0].id
        provider = get_provider(existing_id)
        assert provider is not None
        assert provider.id == existing_id

    def test_returns_none_for_unknown_id(self) -> None:
        assert get_provider("nonexistent-provider") is None


class TestCatalog:
    def test_catalog_is_non_empty(self) -> None:
        assert len(PM_CREDENTIAL_PROVIDERS) > 0

    def test_provider_ids_are_unique(self) -> None:
        ids = [p.id for p in PM_CREDENTIAL_PROVIDERS]
        assert len(ids) == len(set(ids))
