"""Tests for maistro.agents.catalog — AgentCard and AgentCatalog cascade resolution."""

from __future__ import annotations

from maistro.agents.catalog import AgentCard, AgentCatalog
from maistro.types.agent import AgentIdentity


class TestAgentCardFromIdentity:
    def test_from_identity_maps_all_fields(self) -> None:
        identity = AgentIdentity(
            name="mason",
            description="builds things",
            version="2.0.0",
            reasoning_strategy="react",
            tools=("git",),
            skills=("python",),
            trust_tier="t1",
            priority_tier="P0",
            max_tool_rounds=5,
            delegation_mode="auto",
            sub_agents=("artificer",),
            model="claude",
            model_fallbacks=("gpt",),
            active=False,
        )

        card = AgentCard.from_identity(identity, scope="user", user_id="u1")

        assert card.id == "mason"
        assert card.name == "mason"
        assert card.description == "builds things"
        assert card.version == "2.0.0"
        assert card.reasoning_strategy == "react"
        assert card.tools == ("git",)
        assert card.skills == ("python",)
        assert card.trust_tier == "t1"
        assert card.priority_tier == "P0"
        assert card.max_tool_rounds == 5
        assert card.delegation_mode == "auto"
        assert card.sub_agents == ("artificer",)
        assert card.model == "claude"
        assert card.model_fallbacks == ("gpt",)
        assert card.active is False
        assert card.scope == "user"
        assert card.user_id == "u1"

    def test_from_identity_defaults_scope_to_builtin(self) -> None:
        card = AgentCard.from_identity(AgentIdentity(name="ranger"))
        assert card.scope == "builtin"
        assert card.user_id == ""

    def test_from_identity_missing_priority_tier_attr_defaults_to_p2(self) -> None:
        class _BareIdentity:
            name = "x"
            description = ""
            version = "1.0.0"
            reasoning_strategy = "direct"
            tools: tuple[str, ...] = ()
            skills: tuple[str, ...] = ()
            trust_tier = "t4"
            max_tool_rounds = 3
            delegation_mode = "none"
            sub_agents: tuple[str, ...] = ()
            model = "auto"
            model_fallbacks: tuple[str, ...] = ()
            active = True

        card = AgentCard.from_identity(_BareIdentity())  # type: ignore[arg-type]
        assert card.priority_tier == "P2"


class TestAgentCardToDict:
    def test_to_dict_shape(self) -> None:
        card = AgentCard(
            id="mason",
            name="mason",
            description="desc",
            tools=("git", "bash"),
            skills=("python",),
            sub_agents=("artificer",),
        )

        result = card.to_dict()

        assert result["id"] == "mason"
        assert result["name"] == "mason"
        assert result["description"] == "desc"
        assert result["version"] == "1.0.0"
        assert result["capabilities"]["reasoning_strategy"] == "direct"
        assert result["capabilities"]["tools"] == ["git", "bash"]
        assert result["capabilities"]["skills"] == ["python"]
        assert result["capabilities"]["sub_agents"] == ["artificer"]
        assert result["trust_tier"] == "t2"
        assert result["priority_tier"] == "P2"
        assert result["model"] == "auto"
        assert result["active"] is True


def _card(
    *,
    id: str = "mason",
    name: str = "mason",
    scope: str = "builtin",
    user_id: str = "",
    trust_tier: str = "t2",
    priority_tier: str = "P2",
) -> AgentCard:
    return AgentCard(
        id=id,
        name=name,
        scope=scope,
        user_id=user_id,
        trust_tier=trust_tier,
        priority_tier=priority_tier,
    )


class TestAgentCatalogResolve:
    def test_resolve_missing_agent_returns_none(self) -> None:
        catalog = AgentCatalog()
        assert catalog.resolve("missing") is None

    def test_resolve_builtin_visible_to_anyone(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(scope="builtin"))
        assert catalog.resolve("mason") is not None

    def test_resolve_user_card_invisible_to_other_user(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(scope="user", user_id="u1"))
        assert catalog.resolve("mason", user_id="u2") is None

    def test_resolve_user_card_invisible_without_user_id(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(scope="user", user_id="u1"))
        assert catalog.resolve("mason") is None

    def test_resolve_user_card_visible_to_matching_user(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(scope="user", user_id="u1"))
        result = catalog.resolve("mason", user_id="u1")
        assert result is not None
        assert result.scope == "user"

    def test_resolve_skips_cards_with_non_matching_id(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(id="other", name="other"))
        catalog.register(_card(id="mason"))

        result = catalog.resolve("mason")

        assert result is not None
        assert result.id == "mason"

    def test_resolve_user_cascades_over_builtin(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(scope="builtin"))
        catalog.register(_card(scope="user", user_id="u1"))

        result = catalog.resolve("mason", user_id="u1")

        assert result is not None
        assert result.scope == "user"


class TestAgentCatalogListAgents:
    def test_list_agents_empty_catalog(self) -> None:
        assert AgentCatalog().list_agents() == []

    def test_list_agents_excludes_invisible_cards(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(scope="user", user_id="u1"))
        assert catalog.list_agents(user_id="u2") == []

    def test_list_agents_dedupes_by_cascade_priority(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(id="mason", scope="builtin"))
        catalog.register(_card(id="mason", scope="user", user_id="u1"))

        result = catalog.list_agents(user_id="u1")

        assert len(result) == 1
        assert result[0].scope == "user"

    def test_list_agents_keeps_existing_when_new_card_lower_priority(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(id="mason", scope="user", user_id="u1"))
        catalog.register(_card(id="mason", scope="builtin"))

        result = catalog.list_agents(user_id="u1")

        assert len(result) == 1
        assert result[0].scope == "user"

    def test_list_agents_sorted_by_name(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(id="zeta", name="zeta"))
        catalog.register(_card(id="alpha", name="alpha"))

        result = catalog.list_agents()

        assert [c.name for c in result] == ["alpha", "zeta"]


class TestAgentCatalogFilters:
    def test_list_by_trust_tier(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(id="a", name="a", trust_tier="t1"))
        catalog.register(_card(id="b", name="b", trust_tier="t2"))

        result = catalog.list_by_trust_tier("t1")

        assert [c.id for c in result] == ["a"]

    def test_list_by_priority_tier(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(id="a", name="a", priority_tier="P0"))
        catalog.register(_card(id="b", name="b", priority_tier="P2"))

        result = catalog.list_by_priority_tier("P0")

        assert [c.id for c in result] == ["a"]

    def test_list_by_trust_tier_passes_through_user_id_kwarg(self) -> None:
        catalog = AgentCatalog()
        catalog.register(_card(id="a", name="a", scope="user", user_id="u1", trust_tier="t1"))

        result = catalog.list_by_trust_tier("t1", user_id="u2")

        assert result == []
