"""Behavioral pins for the Conductor's host-resolved isolation floor (#60, #845).

`services/execution_mode.py` translates the tier Sentinel resolved into the
Conductor's isolation vocabulary. The authorization decision itself stays in
Sentinel; these tests pin the translation, so a caller-supplied label can
never select the mode and a host denial is never softened into a weaker one.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.execution_mode import resolve_authorized_execution_mode  # noqa: E402

#: The grant the shipped Conductor profiles state for graph-node execution
#: (``MAISTRO_PERMISSIONS`` in the compose stacks). The deployment-level pin
#: lives in ``tests/security/test_sentinel_permission_table_armed.py``; this
#: file pins what that grant does to a node.
_SHIPPED_NODE_GRANT = {"graph.node.execute": ["admin", "user"]}


def _shipped_sentinel() -> Sentinel:
    """A Sentinel armed exactly as the shipped Conductor profiles arm it."""
    from maistro.security.permission_policy import build_permission_table

    return Sentinel(
        warden=Warden(),
        permission_table=build_permission_table(
            preset="hive_conductor_tools",
            permissions=_SHIPPED_NODE_GRANT,
        ),
    )


@pytest.mark.asyncio
async def test_execution_mode_is_the_authorized_tier_floor() -> None:
    """A host denial is the only "blocked"; an authorized action gets its floor."""
    principal = Principal(id="owner-1", kind="human", roles=("user",))

    # No permission decision at all (fail-closed table): a host denial.
    strict_sentinel = Sentinel(warden=Warden(), permission_table={})
    assert (
        await resolve_authorized_execution_mode(
            strict_sentinel,
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
        )
        == "blocked"
    )

    # Authorized (compatibility allow-on-miss) with no explicit tier record:
    # the irreversible default tier is SELF_ELEVATION, whose floor is the
    # sandbox -- never inline, and no longer collapsed into a denial.
    default_sentinel = Sentinel(warden=Warden(), permission_table={}, allow_on_miss=True)
    assert (
        await resolve_authorized_execution_mode(
            default_sentinel,
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
        )
        == "sandbox"
    )

    # Only an explicit host tier record promotes an authorized action inline.
    role_sentinel = Sentinel(
        warden=Warden(),
        permission_table={},
        tier_policy={("graph.node.execute", "user"): Tier.ROLE_AUTO},
        allow_on_miss=True,
    )
    assert (
        await resolve_authorized_execution_mode(
            role_sentinel,
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
        )
        == "async"
    )


@pytest.mark.asyncio
async def test_an_explicitly_blocked_tier_denies_even_an_authorized_action() -> None:
    principal = Principal(id="owner-1", kind="human", roles=("user",))
    sentinel = Sentinel(
        warden=Warden(),
        permission_table={},
        tier_policy={("graph.node.execute", "user"): Tier.BLOCKED},
        allow_on_miss=True,
    )

    assert (
        await resolve_authorized_execution_mode(
            sentinel,
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
        )
        == "blocked"
    )


@pytest.mark.asyncio
async def test_a_cleared_elevation_grant_selects_the_sandbox_floor() -> None:
    """The TTL-bound elevation grant is the human decision record that clears
    the SELF_ELEVATION tier; the cleared action still executes at the sandbox
    floor, never inline."""
    from maistro.security.sentinel.elevation import (
        InMemoryElevationStore,
        confirm_self_elevation,
        request_self_elevation,
    )

    principal = Principal(id="owner-1", kind="human", roles=("user",))
    store = InMemoryElevationStore()
    challenge = request_self_elevation(principal.id, "graph.node.execute")
    await store.store(confirm_self_elevation(challenge, "re-auth proof", ttl_seconds=300))
    sentinel = Sentinel(
        warden=Warden(),
        permission_table={},
        elevation_store=store,
        allow_on_miss=True,
    )

    # Cleared by the stored grant: sandbox floor (never inline).
    assert (
        await resolve_authorized_execution_mode(
            sentinel,
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
        )
        == "sandbox"
    )

    # A different action class is not covered by the grant: still authorized,
    # still at the sandbox floor, but the grant decision stays action-bound.
    assert (
        await resolve_authorized_execution_mode(
            sentinel,
            "graph.node.untrusted",
            principal,
            args={"node_id": "n1"},
        )
        == "sandbox"
    )
    grants_for_other_action = await store.find_valid(principal.id, "graph.node.untrusted", None)
    assert grants_for_other_action is None


@pytest.mark.asyncio
async def test_an_uncleared_delegated_tier_stays_off_the_inline_mode() -> None:
    principal = Principal(id="owner-1", kind="human", roles=("user",))
    sentinel = Sentinel(
        warden=Warden(),
        permission_table={},
        tier_policy={("graph.node.execute", "user"): Tier.DELEGATED},
        allow_on_miss=True,
    )

    assert (
        await resolve_authorized_execution_mode(
            sentinel,
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
        )
        == "sandbox"
    )


@pytest.mark.asyncio
async def test_an_untrusted_node_default_tier_is_blocked_not_sandbox() -> None:
    """The untrusted node class carries its own host default: it is blocked
    unless the host policy record says otherwise."""
    principal = Principal(id="owner-1", kind="human", roles=("user",))
    sentinel = Sentinel(warden=Warden(), permission_table={}, allow_on_miss=True)

    assert (
        await resolve_authorized_execution_mode(
            sentinel,
            "graph.node.untrusted",
            principal,
            args={"node_id": "n1"},
            default=Tier.BLOCKED,
        )
        == "blocked"
    )


@pytest.mark.asyncio
async def test_the_shipped_grant_makes_a_normal_node_reachable() -> None:
    """The shipped deployment grant is what makes a DAG node runnable.

    Without it the fail-closed table denies `graph.node.execute` and every
    node in every shipped profile blocks (#60, #845).
    """
    principal = Principal(id="owner-1", kind="human", roles=("user",))

    assert (
        await resolve_authorized_execution_mode(
            _shipped_sentinel(),
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
            default=Tier.SELF_ELEVATION,
        )
        == "sandbox"
    )


@pytest.mark.asyncio
async def test_the_shipped_grant_does_not_reach_the_untrusted_node_class() -> None:
    """`graph.node.untrusted` is a different capability and stays ungranted."""
    principal = Principal(id="owner-1", kind="human", roles=("user",))

    assert (
        await resolve_authorized_execution_mode(
            _shipped_sentinel(),
            "graph.node.untrusted",
            principal,
            args={"node_id": "n1"},
            default=Tier.BLOCKED,
        )
        == "blocked"
    )


@pytest.mark.asyncio
async def test_a_principal_without_a_host_role_is_denied() -> None:
    """The grant names host roles; a principal the host gave none is denied."""
    principal = Principal(id="owner-1", kind="human", roles=())

    assert (
        await resolve_authorized_execution_mode(
            _shipped_sentinel(),
            "graph.node.execute",
            principal,
            args={"node_id": "n1"},
            default=Tier.SELF_ELEVATION,
        )
        == "blocked"
    )
