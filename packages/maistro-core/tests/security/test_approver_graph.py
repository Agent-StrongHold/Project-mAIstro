"""Tests for the approver graph (SPEC-246 / ADR-068 §C)."""

from __future__ import annotations

from maistro.security.sentinel.approver_graph import ApproverBinding, ApproverGraph
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden


def _human(
    principal_id: str, roles: tuple[str, ...] = (), scopes: tuple[str, ...] = ()
) -> Principal:
    return Principal(id=principal_id, kind="human", roles=roles, scopes=scopes)


class TestResolve:
    def test_exact_binding_match_wins(self) -> None:
        graph = ApproverGraph(
            [ApproverBinding(action="deploy", for_scope="team:2", approved_by="team:1")]
        )

        assert graph.resolve("deploy", "team:2") == "team:1"

    def test_no_match_falls_back_to_admin(self) -> None:
        graph = ApproverGraph([])

        assert graph.resolve("deploy", "team:9") == "role:admin"

    def test_wildcard_scope_binding_matches_same_prefix(self) -> None:
        graph = ApproverGraph(
            [ApproverBinding(action="deploy", for_scope="user:*", approved_by="role:manager")]
        )

        assert graph.resolve("deploy", "user:42") == "role:manager"

    def test_exact_match_preferred_over_wildcard(self) -> None:
        graph = ApproverGraph(
            [
                ApproverBinding(action="deploy", for_scope="user:*", approved_by="role:manager"),
                ApproverBinding(action="deploy", for_scope="user:42", approved_by="user:99"),
            ]
        )

        assert graph.resolve("deploy", "user:42") == "user:99"

    def test_admin_always_resolvable_with_zero_bindings(self) -> None:
        graph = ApproverGraph([])

        assert graph.resolve("anything", "anything:1") == "role:admin"


class TestMembers:
    def test_role_prefix_resolves_principals_with_role(self) -> None:
        graph = ApproverGraph(
            [],
            principals=[
                _human("u1", roles=("manager",)),
                _human("u2", roles=("employee",)),
            ],
        )

        assert graph.members("role:manager") == {"u1"}

    def test_scope_prefix_resolves_principals_with_scope(self) -> None:
        graph = ApproverGraph(
            [],
            principals=[
                _human("u1", scopes=("team:1",)),
                _human("u2", scopes=("team:2",)),
            ],
        )

        assert graph.members("team:1") == {"u1"}

    def test_unknown_scope_returns_empty_set_not_error(self) -> None:
        graph = ApproverGraph([], principals=[_human("u1")])

        assert graph.members("") == set()


class TestSentinelIntegration:
    async def test_delegated_tier_populates_approver_scope_from_graph(self) -> None:
        graph = ApproverGraph(
            [ApproverBinding(action="deploy", for_scope="team:2", approved_by="team:1")]
        )
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("deploy", "team:2"): Tier.DELEGATED},
            approver_graph=graph,
        )
        principal = _human("u1", scopes=("team:2",))

        decision = await sentinel.authorize("deploy", principal, within_budget=True)

        assert decision.tier == Tier.DELEGATED
        assert decision.approver_scope == "team:1"

    async def test_non_delegated_tier_leaves_approver_scope_none(self) -> None:
        graph = ApproverGraph(
            [ApproverBinding(action="deploy", for_scope="team:2", approved_by="team:1")]
        )
        sentinel = Sentinel(warden=Warden(), permission_table={}, approver_graph=graph)
        principal = _human("u1", scopes=("team:2",))

        decision = await sentinel.authorize(
            "read_file", principal, reversibility="internal", within_budget=True
        )

        assert decision.approver_scope is None
