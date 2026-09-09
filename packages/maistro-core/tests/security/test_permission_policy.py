"""Coverage for maistro.security.permission_policy.build_permission_table."""

from __future__ import annotations

import pytest

from maistro.security._types import AuthContext
from maistro.security.patterns import DANGEROUS_TOOL_NAMES
from maistro.security.permission_policy import build_permission_table


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_default_build_returns_empty_table() -> None:
    assert build_permission_table() == {}


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_preset_maps_every_dangerous_tool_to_admin() -> None:
    table = build_permission_table(preset="dangerous_tools_admin")
    assert set(table.keys()) == set(DANGEROUS_TOOL_NAMES)
    assert all(roles == frozenset({"admin"}) for roles in table.values())


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_explicit_permissions_override_preset() -> None:
    table = build_permission_table(
        preset="dangerous_tools_admin",
        permissions={"exec": ["operator"]},
    )
    assert table["exec"] == frozenset({"operator"})
    assert table["shell"] == frozenset({"admin"})


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_empty_role_list_is_a_hard_deny() -> None:
    table = build_permission_table(permissions={"nuke": []})
    assert table["nuke"] == frozenset()
    assert AuthContext(roles=frozenset({"admin"})).can_use_tool("nuke", table) is False


@pytest.mark.contract("boundary")
@pytest.mark.scope("unit")
def test_unknown_preset_raises() -> None:
    with pytest.raises(ValueError, match="typo"):
        build_permission_table(preset="typo")


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_absent_entry_denies_by_default() -> None:
    """Core-package mirror of formal invariant I6 as amended (ADR-072726-0d6b,
    implemented for #1165): an absent table entry DENIES by default, so a
    future permissive regression breaks a core test too, not only a formal
    one. The inverse property pinned here is exactly the allow-all hole #1165
    closes: a deployment that configures nothing authorizes nothing."""
    table = build_permission_table(preset="dangerous_tools_admin")
    assert AuthContext(roles=frozenset()).can_use_tool("some_unlisted_tool", table) is False
    assert (
        AuthContext(roles=frozenset({"admin"})).can_use_tool("some_unlisted_tool", table) is False
    )


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
def test_governed_table_still_grants_explicit_entries() -> None:
    """Fail-closed is a default, not a blanket deny: entries built by this
    module grant exactly the roles they name (and the empty-role hard deny
    still denies admins)."""
    table = build_permission_table(preset="dangerous_tools_admin")
    tool = sorted(table)[0]
    assert AuthContext(roles=frozenset({"admin"})).can_use_tool(tool, table) is True
    assert AuthContext(roles=frozenset({"user"})).can_use_tool(tool, table) is False
    hard_denied = build_permission_table(permissions={"nuke": []})
    assert AuthContext(roles=frozenset({"admin"})).can_use_tool("nuke", hard_denied) is False
