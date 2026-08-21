"""Tests for the memory exposure mode gating primitive (SPEC-249 / ADR-057)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.memory.exposure import (
    Actor,
    BlockExposure,
    MemoryExposureMode,
    MemoryWriteDenied,
    enforce_promote,
    enforce_write,
)


class TestEnforceWrite:
    def test_system_managed_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_write(MemoryExposureMode.SYSTEM_MANAGED, Actor.AGENT)

    def test_system_managed_allows_system(self) -> None:
        assert enforce_write(MemoryExposureMode.SYSTEM_MANAGED, Actor.SYSTEM) is None

    def test_agent_managed_allows_agent(self) -> None:
        assert enforce_write(MemoryExposureMode.AGENT_MANAGED, Actor.AGENT) is None

    def test_agent_managed_allows_system(self) -> None:
        assert enforce_write(MemoryExposureMode.AGENT_MANAGED, Actor.SYSTEM) is None

    def test_hybrid_system_managed_tag_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_write(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.SYSTEM_MANAGED,
            )

    def test_hybrid_agent_managed_tag_allows_agent(self) -> None:
        assert (
            enforce_write(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.AGENT_MANAGED,
            )
            is None
        )

    def test_hybrid_without_block_exposure_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            enforce_write(MemoryExposureMode.HYBRID, Actor.AGENT)

    def test_denial_carries_scope_actor_mode_reason(self) -> None:
        with pytest.raises(MemoryWriteDenied) as exc_info:
            enforce_write(MemoryExposureMode.SYSTEM_MANAGED, Actor.AGENT, scope="agent")
        denied = exc_info.value
        assert denied.scope == "agent"
        assert denied.actor == Actor.AGENT
        assert denied.mode == MemoryExposureMode.SYSTEM_MANAGED
        assert denied.reason


class TestEnforcePromote:
    def test_system_managed_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_promote(MemoryExposureMode.SYSTEM_MANAGED, Actor.AGENT)

    def test_system_managed_allows_system(self) -> None:
        assert enforce_promote(MemoryExposureMode.SYSTEM_MANAGED, Actor.SYSTEM) is None

    def test_agent_managed_allows_agent(self) -> None:
        assert enforce_promote(MemoryExposureMode.AGENT_MANAGED, Actor.AGENT) is None

    def test_hybrid_system_managed_tag_denies_agent(self) -> None:
        with pytest.raises(MemoryWriteDenied):
            enforce_promote(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.SYSTEM_MANAGED,
            )

    def test_hybrid_agent_managed_tag_allows_agent(self) -> None:
        assert (
            enforce_promote(
                MemoryExposureMode.HYBRID,
                Actor.AGENT,
                block_exposure=BlockExposure.AGENT_MANAGED,
            )
            is None
        )

    def test_hybrid_without_block_exposure_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            enforce_promote(MemoryExposureMode.HYBRID, Actor.AGENT)


@given(
    mode=st.sampled_from(MemoryExposureMode),
    block_exposure=st.one_of(st.none(), st.sampled_from(BlockExposure)),
)
def test_system_actor_never_denied(
    mode: MemoryExposureMode, block_exposure: BlockExposure | None
) -> None:
    if mode == MemoryExposureMode.HYBRID and block_exposure is None:
        block_exposure = BlockExposure.SYSTEM_MANAGED
    assert enforce_write(mode, Actor.SYSTEM, block_exposure=block_exposure) is None
    assert enforce_promote(mode, Actor.SYSTEM, block_exposure=block_exposure) is None
