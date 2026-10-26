"""Tests for memory protocol conformance (ADR-014)."""

from __future__ import annotations

import pytest

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.protocols.memory import EpisodicStore, LearningStore, OutcomeStore

pytestmark = [pytest.mark.contract("boundary")]


class TestProtocolConformance:
    @pytest.mark.ac("ADR-014/AC-1")
    def test_learning_store_conforms(self) -> None:
        assert isinstance(
            InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED), LearningStore
        )

    @pytest.mark.ac("ADR-014/AC-2")
    def test_episodic_store_conforms(self) -> None:
        assert isinstance(
            InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED), EpisodicStore
        )

    @pytest.mark.ac("ADR-014/AC-3")
    def test_outcome_store_conforms(self) -> None:
        assert isinstance(
            InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED), OutcomeStore
        )

    @pytest.mark.ac("ADR-014/AC-4")
    def test_non_conforming_class_returns_false(self) -> None:
        class Stub:
            pass

        assert not isinstance(Stub(), LearningStore)
        assert not isinstance(Stub(), EpisodicStore)
        assert not isinstance(Stub(), OutcomeStore)
