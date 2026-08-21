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
def test_absent_entry_still_permits() -> None:
    """A core-package mirror of formal invariant I6: an absent table entry
    permits by default, so a future fail-closed change breaks a core test
    too, not only a formal one."""
    table = build_permission_table(preset="dangerous_tools_admin")
    assert AuthContext(roles=frozenset()).can_use_tool("some_unlisted_tool", table) is True
