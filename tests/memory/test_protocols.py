"""Tests for memory protocol conformance (ADR-014)."""

from __future__ import annotations

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.protocols.memory import EpisodicStore, LearningStore, OutcomeStore


class TestProtocolConformance:
    def test_learning_store_conforms(self) -> None:
        assert isinstance(InMemoryLearningStore(), LearningStore)

    def test_episodic_store_conforms(self) -> None:
        assert isinstance(InMemoryEpisodicStore(), EpisodicStore)

    def test_outcome_store_conforms(self) -> None:
        assert isinstance(InMemoryOutcomeStore(), OutcomeStore)

    def test_non_conforming_class_returns_false(self) -> None:
        class Stub:
            pass

        assert not isinstance(Stub(), LearningStore)
        assert not isinstance(Stub(), EpisodicStore)
        assert not isinstance(Stub(), OutcomeStore)
