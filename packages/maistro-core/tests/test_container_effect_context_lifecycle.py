"""Container publication, explicit reset, and teardown share one lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    configure_default_effect_context,
    default_effect_context,
    new_effect_context,
    release_default_effect_context,
)
from maistro.container import create_container
from maistro.types.config import AgentConfig


@pytest.fixture(autouse=True)
def _isolated_default_context() -> Iterator[None]:
    default_effect_context.cache_clear()
    yield
    default_effect_context.cache_clear()


@pytest.mark.parametrize("close_inner_first", [True, False], ids=["nested", "out-of-order"])
async def test_container_lifetimes_preserve_the_other_live_context(close_inner_first: bool) -> None:
    config = AgentConfig(router_api_key="test-key", database_url="memory://")
    outer = await create_container(config)
    try:
        inner = await create_container(config)
        try:
            assert default_effect_context() is inner.capability_effects
            first, remaining = (inner, outer) if close_inner_first else (outer, inner)
            await first.aclose()
            assert default_effect_context() is remaining.capability_effects
            await first.aclose()
            assert default_effect_context() is remaining.capability_effects
        finally:
            await inner.aclose()
    finally:
        await outer.aclose()
    fallback = default_effect_context()
    assert fallback is not outer.capability_effects
    assert fallback is not inner.capability_effects
    assert default_effect_context() is fallback


def test_explicit_bind_reset_clears_published_contexts_and_fallback() -> None:
    previous_fallback = default_effect_context()
    outer, inner = new_effect_context(), new_effect_context()
    configure_default_effect_context(outer)
    configure_default_effect_context(inner)
    assert default_effect_context() is inner

    default_effect_context.cache_clear()

    fallback = default_effect_context()
    assert all(fallback is not context for context in (outer, inner, previous_fallback))
    release_default_effect_context(inner)
    release_default_effect_context(outer)
    assert default_effect_context() is fallback


def test_republishing_does_not_leave_a_stale_duplicate() -> None:
    outer, inner = new_effect_context(), new_effect_context()
    configure_default_effect_context(outer)
    configure_default_effect_context(inner)
    configure_default_effect_context(outer)
    assert default_effect_context() is outer
    release_default_effect_context(outer)
    assert default_effect_context() is inner


async def test_cache_clear_drops_a_published_sqlite_context_after_connection_close(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        router_api_key="test-key", database_url=f"sqlite:///{tmp_path / 'effects.db'}"
    )
    container = await create_container(config)
    try:
        assert default_effect_context() is container.capability_effects
        # Match legacy restart cleanup: callers may close the underlying
        # database directly before explicitly resetting the process default.
        await container.db_pool.close()
        default_effect_context.cache_clear()
        replacement = default_effect_context()
        assert replacement is not container.capability_effects
        binding = Binding(
            binding_id="after-reset",
            workspace_id="workspace",
            project_id="project",
            capability="jira.search",
        )
        await replacement.bindings.put(binding)
        assert await replacement.bindings.get(binding.binding_id) == binding
    finally:
        await container.aclose()
