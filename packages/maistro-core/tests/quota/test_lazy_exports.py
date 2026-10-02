"""`maistro.quota` resolves every name it advertises, and only those (#1196).

The package exports lazily so importing config does not drag the Invocation
accounting modules in behind it. That shape invites one specific bug: a name
listed in `__all__` that `__getattr__` has no branch for, which imports clean
and fails at the first real use. `from maistro.quota import X` is the only
thing that catches it, and nothing did -- the module sat at 18% line coverage
with every export unexercised.
"""

from __future__ import annotations

import importlib

import pytest

import maistro.quota as quota


@pytest.mark.parametrize("name", sorted(quota.__all__))
def test_every_advertised_name_resolves(name: str) -> None:
    """Each `__all__` entry is importable and is the class it claims to be."""
    resolved = getattr(quota, name)
    assert resolved is not None
    assert resolved.__name__ == name


def test_the_sqlite_door_is_the_real_class() -> None:
    """The one branch that loads a different module than the rest."""
    from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota

    assert quota.SqliteInvocationQuota is SqliteInvocationQuota


def test_the_accounting_names_come_from_invocation_quota() -> None:
    """The shared branch: six names out of one module, by identity not by shape."""
    module = importlib.import_module("maistro.quota.invocation_quota")

    for name in sorted(set(quota.__all__) - {"SqliteInvocationQuota"}):
        assert getattr(quota, name) is getattr(module, name)


def test_an_unknown_name_is_an_attribute_error_not_a_key_error() -> None:
    """The failure path callers actually see.

    `__getattr__` resolves through a dict, so a miss raises `KeyError` unless
    it is translated. `KeyError` from an attribute access would break
    `hasattr`, `getattr(..., default)` and `from ... import` alike, each in a
    different and confusing way.
    """
    with pytest.raises(AttributeError, match="NotAQuotaName"):
        quota.NotAQuotaName  # noqa: B018

    assert getattr(quota, "NotAQuotaName", "fallback") == "fallback"
    assert not hasattr(quota, "NotAQuotaName")
