"""Tests for types.py: EpisodicMemory construction invariants."""

from __future__ import annotations

from uuid import uuid4

import pytest

from maistro_turing.types import DURABLE_TIERS, EpisodicMemory, MemoryTier, SourceKind


def _make_regret(self_id: str, *, supersedes: str | None = None) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="something I wish I hadn't done",
        weight=0.7,
        affect=-0.5,
        confidence_at_creation=0.8,
        surprise_delta=0.5,
        intent_at_time="route-a-request",
        supersedes=supersedes,
        immutable=True,
    )


def test_ac_3_3_durable_requires_i_did_source() -> None:
    for bad_source in (SourceKind.I_WAS_TOLD, SourceKind.I_IMAGINED):
        with pytest.raises(ValueError, match="requires source=i_did"):
            EpisodicMemory(
                memory_id="x",
                self_id="self-A",
                tier=MemoryTier.REGRET,
                source=bad_source,
                content="c",
                weight=0.7,
                intent_at_time="i",
            )


def test_ac_3_4_self_binding_required() -> None:
    with pytest.raises(ValueError, match="self_id is required"):
        EpisodicMemory(
            memory_id="x",
            self_id="",
            tier=MemoryTier.REGRET,
            source=SourceKind.I_DID,
            content="c",
            weight=0.7,
            intent_at_time="i",
        )


def test_ac_3_6_frozen_fields_cannot_be_mutated_in_python() -> None:
    m = EpisodicMemory(
        memory_id="x",
        self_id="self-A",
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="c",
        weight=0.7,
        intent_at_time="i",
        immutable=True,
    )
    with pytest.raises(AttributeError):
        m.content = "changed"
    with pytest.raises(AttributeError):
        m.tier = MemoryTier.ACCOMPLISHMENT


def test_superseded_by_settable_once() -> None:
    m = EpisodicMemory(
        memory_id="x",
        self_id="self-A",
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content="c",
        weight=0.3,
    )
    m.superseded_by = "y"
    with pytest.raises(AttributeError, match="settable only once"):
        m.superseded_by = "z"


def test_mutable_fields_are_settable() -> None:
    m = EpisodicMemory(
        memory_id="x",
        self_id="self-A",
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content="c",
        weight=0.3,
    )
    m.reinforcement_count = 5
    m.contradiction_count = 1
    m.deleted = True
    assert m.reinforcement_count == 5
    assert m.contradiction_count == 1
    assert m.deleted is True


def test_affect_range_validated() -> None:
    with pytest.raises(ValueError, match="affect out of range"):
        EpisodicMemory(
            memory_id="x",
            self_id="self-A",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="c",
            weight=0.3,
            affect=2.0,
        )


def test_confidence_range_validated() -> None:
    with pytest.raises(ValueError, match="confidence_at_creation out of range"):
        EpisodicMemory(
            memory_id="x",
            self_id="self-A",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="c",
            weight=0.3,
            confidence_at_creation=1.5,
        )


def test_surprise_delta_range_validated() -> None:
    with pytest.raises(ValueError, match="surprise_delta out of range"):
        EpisodicMemory(
            memory_id="x",
            self_id="self-A",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="c",
            weight=0.3,
            surprise_delta=-0.5,
        )


def test_memory_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        EpisodicMemory(
            memory_id="x",
            self_id="self-A",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="c",
            weight=0.3,
            supersedes="x",
        )


def test_accomplishment_requires_intent() -> None:
    with pytest.raises(ValueError, match="ACCOMPLISHMENT requires non-empty intent"):
        EpisodicMemory(
            memory_id="x",
            self_id="self-A",
            tier=MemoryTier.ACCOMPLISHMENT,
            source=SourceKind.I_DID,
            content="c",
            weight=0.7,
            intent_at_time="",
        )


def test_durable_tiers_set() -> None:
    assert MemoryTier.REGRET in DURABLE_TIERS
    assert MemoryTier.ACCOMPLISHMENT in DURABLE_TIERS
    assert MemoryTier.AFFIRMATION in DURABLE_TIERS
    assert MemoryTier.WISDOM in DURABLE_TIERS
    assert MemoryTier.OBSERVATION not in DURABLE_TIERS
