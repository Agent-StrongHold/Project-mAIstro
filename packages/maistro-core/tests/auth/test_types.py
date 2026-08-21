"""Tests for maistro.auth._types — scope expansion, category mapping, ServiceIdentity."""

from __future__ import annotations

import pytest

from maistro.auth._types import (
    CATEGORY_SCOPES,
    Scope,
    ScopeCategory,
    ServiceIdentity,
    expand_scopes,
)


class TestExpandScopes:
    def test_single_scope(self) -> None:
        result = expand_scopes(["llm:chat_completions"])
        assert Scope.CHAT_COMPLETIONS in result
        assert len(result) == 1

    def test_category_wildcard(self) -> None:
        result = expand_scopes(["llm:*"])
        assert Scope.CHAT_COMPLETIONS in result
        assert Scope.MODELS_LIST in result
        assert Scope.EMBEDDINGS in result
        assert Scope.IMAGE_GENERATE in result
        assert Scope.RESPONSES_CREATE in result
        assert Scope.RESPONSES_READ in result
        assert len(result) == len(CATEGORY_SCOPES[ScopeCategory.LLM])

    def test_multiple_categories(self) -> None:
        result = expand_scopes(["llm:*", "trading:*"])
        assert Scope.CHAT_COMPLETIONS in result
        assert Scope.TRADING_READ in result
        assert Scope.TRADING_WRITE in result

    def test_mixed_category_and_individual(self) -> None:
        result = expand_scopes(["events:*", "memory:read"])
        assert Scope.EVENTS_EMIT in result
        assert Scope.EVENTS_SUBSCRIBE in result
        assert Scope.EVENTS_HISTORY in result
        assert Scope.MEMORY_READ in result
        assert Scope.MEMORY_WRITE not in result

    def test_supersede_wildcard(self) -> None:
        result = expand_scopes(["*:*"])
        all_individual: set[Scope] = set()
        for s in CATEGORY_SCOPES.values():
            all_individual |= s
        assert result == frozenset(all_individual)

    def test_invalid_scope_ignored(self) -> None:
        result = expand_scopes(["llm:chat_completions", "nonsense:foo"])
        assert Scope.CHAT_COMPLETIONS in result
        assert len(result) == 1

    def test_invalid_category_wildcard_ignored(self) -> None:
        result = expand_scopes(["nonexistent:*"])
        assert len(result) == 0

    def test_empty_list(self) -> None:
        result = expand_scopes([])
        assert len(result) == 0

    def test_duplicate_scopes_deduplicated(self) -> None:
        result = expand_scopes(["llm:chat_completions", "llm:chat_completions"])
        assert len(result) == 1


class TestServiceIdentity:
    def test_has_scope_true(self) -> None:
        identity = ServiceIdentity(
            name="test",
            scopes=frozenset({Scope.CHAT_COMPLETIONS, Scope.EVENTS_EMIT}),
        )
        assert identity.has_scope(Scope.CHAT_COMPLETIONS)

    def test_has_scope_false(self) -> None:
        identity = ServiceIdentity(name="test", scopes=frozenset({Scope.EVENTS_EMIT}))
        assert not identity.has_scope(Scope.CHAT_COMPLETIONS)

    def test_has_any_scope(self) -> None:
        identity = ServiceIdentity(
            name="test",
            scopes=frozenset({Scope.EVENTS_EMIT}),
        )
        assert identity.has_any_scope(Scope.CHAT_COMPLETIONS, Scope.EVENTS_EMIT)

    def test_has_any_scope_false(self) -> None:
        identity = ServiceIdentity(name="test", scopes=frozenset())
        assert not identity.has_any_scope(Scope.CHAT_COMPLETIONS)

    def test_frozen(self) -> None:
        identity = ServiceIdentity(name="test", scopes=frozenset({Scope.EVENTS_EMIT}))
        with pytest.raises(AttributeError):
            identity.name = "other"  # type: ignore[misc]


class TestCategoryScopesCompleteness:
    def test_every_category_has_scopes(self) -> None:
        for cat in ScopeCategory:
            assert len(CATEGORY_SCOPES[cat]) > 0, f"{cat} has no scopes"

    def test_all_scopes_belong_to_a_category(self) -> None:
        all_from_categories: set[Scope] = set()
        for s in CATEGORY_SCOPES.values():
            all_from_categories |= s
        for scope in Scope:
            assert scope in all_from_categories, f"{scope} not in any category"

    def test_scope_category_prefix_matches(self) -> None:
        for cat, scopes in CATEGORY_SCOPES.items():
            for scope in scopes:
                assert scope.value.startswith(f"{cat.value}:"), (
                    f"{scope} doesn't match category prefix {cat.value}"
                )
