"""Tests for the authorization tier ladder + authorize() (SPEC-245 / ADR-068 §B,F)."""

from __future__ import annotations

import pytest

from maistro.security.sentinel.authz_types import (
    Principal,
    Tier,
)
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden


@pytest.fixture
def sentinel() -> Sentinel:
    return Sentinel(warden=Warden(), permission_table={})


def _human(principal_id: str = "u1", roles: tuple[str, ...] = ("user",)) -> Principal:
    return Principal(id=principal_id, kind="human", roles=roles, scopes=("user:u1",))


def _agent(owner: str = "u1") -> Principal:
    return Principal(id="agent-1", kind="agent", roles=(), scopes=("agent:agent-1",), owner=owner)


class TestResolveTier:
    def test_no_policy_internal_action_defaults_open(self, sentinel: Sentinel) -> None:
        tier = sentinel.resolve_tier("read_file", _human(), reversibility="internal")
        assert tier == Tier.OPEN

    def test_no_policy_reversible_action_defaults_open(self, sentinel: Sentinel) -> None:
        tier = sentinel.resolve_tier("write_file", _human(), reversibility="reversible")
        assert tier == Tier.OPEN

    def test_no_policy_irreversible_action_defaults_self_elevation(
        self, sentinel: Sentinel
    ) -> None:
        tier = sentinel.resolve_tier("delete_directory", _human(), reversibility="irreversible")
        assert tier == Tier.SELF_ELEVATION

    def test_explicit_policy_entry_overrides_default(self) -> None:
        s = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("deploy", "team:2"): Tier.DELEGATED},
        )
        tier = s.resolve_tier("deploy", _human(roles=()), reversibility="irreversible")
        # No scope match for team:2 on this principal -> falls back to default.
        assert tier == Tier.SELF_ELEVATION


class TestAuthorize:
    async def test_open_action_never_prompts(self, sentinel: Sentinel) -> None:
        decision = await sentinel.authorize(
            "read_file", _human(), reversibility="internal", within_budget=True
        )
        assert decision.needs == "none"
        assert decision.authorized is True

    async def test_irreversible_human_needs_self_elevation(self, sentinel: Sentinel) -> None:
        decision = await sentinel.authorize(
            "delete_directory", _human(), reversibility="irreversible", within_budget=True
        )
        assert decision.tier == Tier.SELF_ELEVATION
        assert decision.needs == "self_elevation"

    async def test_irreversible_agent_needs_scoped_2fa_not_self_elevation(
        self, sentinel: Sentinel
    ) -> None:
        decision = await sentinel.authorize(
            "delete_directory", _agent(), reversibility="irreversible", within_budget=True
        )
        assert decision.tier == Tier.SELF_ELEVATION
        assert decision.needs == "scoped_2fa"

    async def test_over_budget_denies_regardless_of_tier(self, sentinel: Sentinel) -> None:
        decision = await sentinel.authorize(
            "read_file", _human(), reversibility="internal", within_budget=False
        )
        assert decision.within_budget is False
        assert decision.authorized is False
        assert decision.needs == "none"

    async def test_admin_tier_via_explicit_policy(self) -> None:
        s = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("nuke", "user:u1"): Tier.ADMIN},
        )
        decision = await s.authorize(
            "nuke", _human(), reversibility="irreversible", within_budget=True
        )
        assert decision.tier == Tier.ADMIN
        assert decision.needs == "admin"

    async def test_blocked_tier_denies(self) -> None:
        s = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("forbidden", "user:u1"): Tier.BLOCKED},
        )
        decision = await s.authorize(
            "forbidden", _human(), reversibility="irreversible", within_budget=True
        )
        assert decision.tier == Tier.BLOCKED
        assert decision.authorized is False
        assert decision.needs == "none"

    async def test_unauthorized_principal_short_circuits(self) -> None:
        s = Sentinel(
            warden=Warden(),
            permission_table={"deploy": frozenset({"admin"})},
        )
        decision = await s.authorize(
            "deploy", _human(roles=("user",)), reversibility="irreversible", within_budget=True
        )
        assert decision.authorized is False
        assert decision.approver_scope is None
        assert decision.rlphd is None
