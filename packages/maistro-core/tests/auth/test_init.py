"""Tests for maistro.auth's package __init__: lazy attrs + __all__ integrity."""

from __future__ import annotations

import pytest

import maistro.auth as auth_pkg


class TestLazyGetattr:
    def test_lazy_attrs_resolve_from_middleware(self) -> None:
        assert auth_pkg.extract_service_identity is not None
        assert auth_pkg.require_any_scope is not None
        assert auth_pkg.require_scope is not None
        assert auth_pkg.setup_service_auth is not None

    def test_unknown_attr_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError, match="no attribute 'nonexistent'"):
            _ = auth_pkg.nonexistent


class TestAllIntegrity:
    def test_every_name_in_all_is_resolvable(self) -> None:
        for name in auth_pkg.__all__:
            assert hasattr(auth_pkg, name), f"{name} listed in __all__ but not resolvable"
