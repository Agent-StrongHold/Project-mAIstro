"""Tests for the Repertoire Pattern's reuse-first cascade core (SPEC-258 / ADR-070)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.repertoire.protocol import Repertoire
from maistro.repertoire.run import repertoire_run
from maistro.repertoire.types import PerformGate, RehearsalFailed, Verdict


@dataclass
class FakeEntry:
    input_class: str
    value: str


@dataclass
class FakeRepertoire:
    entries: dict[str, FakeEntry] = field(default_factory=dict)
    rehearsal_ok: bool = True
    improvise_calls: int = 0
    compose_calls: list[tuple[str, str]] = field(default_factory=list)

    def recall(self, input_class: str) -> FakeEntry | None:
        return self.entries.get(input_class)

    def nearest(self, input_class: str) -> tuple[FakeEntry, ...]:
        return tuple(self.entries.values())

    def improvise(self, inp: str, priors: tuple[FakeEntry, ...]) -> str:
        self.improvise_calls += 1
        return f"improvised:{inp}"

    def rehearse(self, candidate: str) -> Verdict:
        return Verdict(ok=self.rehearsal_ok, reason="" if self.rehearsal_ok else "failed")

    def compose(self, verified: str, input_class: str) -> FakeEntry:
        self.compose_calls.append((verified, input_class))
        entry = FakeEntry(input_class=input_class, value=verified)
        self.entries[input_class] = entry
        return entry

    def class_of(self, inp: str) -> str:
        return inp


class ThresholdGate:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def should_perform(self, entry: object, *, stakes: float) -> bool:
        return stakes < self.threshold


class AlwaysGate:
    def should_perform(self, entry: object, *, stakes: float) -> bool:
        return True


class NeverGate:
    def should_perform(self, entry: object, *, stakes: float) -> bool:
        return False


def _check_protocol_conformance() -> None:
    rep: Repertoire[str, str, FakeEntry] = FakeRepertoire()
    assert rep is not None


class TestReuseFirst:
    @pytest.mark.asyncio
    async def test_recall_hit_with_approving_gate_skips_improvise(self) -> None:
        rep = FakeRepertoire(entries={"cls1": FakeEntry(input_class="cls1", value="cached")})
        gate: PerformGate = AlwaysGate()

        result = await repertoire_run(rep, "cls1", stakes=0.1, gate=gate)

        assert result == FakeEntry(input_class="cls1", value="cached")
        assert rep.improvise_calls == 0

    @pytest.mark.asyncio
    async def test_recall_miss_falls_to_improvise(self) -> None:
        rep = FakeRepertoire()
        gate: PerformGate = AlwaysGate()

        result = await repertoire_run(rep, "cls1", stakes=0.1, gate=gate)

        assert result == "improvised:cls1"
        assert rep.improvise_calls == 1
        assert rep.compose_calls == [("improvised:cls1", "cls1")]

    @pytest.mark.asyncio
    async def test_high_stakes_gate_rejection_falls_to_improvise(self) -> None:
        rep = FakeRepertoire(entries={"cls1": FakeEntry(input_class="cls1", value="cached")})
        gate: PerformGate = NeverGate()

        result = await repertoire_run(rep, "cls1", stakes=0.9, gate=gate)

        assert result == "improvised:cls1"
        assert rep.improvise_calls == 1


class TestVerifyAlways:
    @pytest.mark.asyncio
    async def test_failing_rehearsal_raises_and_never_composes(self) -> None:
        rep = FakeRepertoire(rehearsal_ok=False)
        gate: PerformGate = AlwaysGate()

        with pytest.raises(RehearsalFailed) as exc_info:
            await repertoire_run(rep, "cls1", stakes=0.1, gate=gate)

        assert exc_info.value.verdict.ok is False
        assert rep.compose_calls == []

    @pytest.mark.asyncio
    async def test_passing_rehearsal_composes_once_and_returns_candidate(self) -> None:
        rep = FakeRepertoire(rehearsal_ok=True)
        gate: PerformGate = AlwaysGate()

        result = await repertoire_run(rep, "cls1", stakes=0.1, gate=gate)

        assert result == "improvised:cls1"
        assert rep.compose_calls == [("improvised:cls1", "cls1")]


@given(stakes=st.floats(min_value=0.0, max_value=1.0))
def test_improvise_called_iff_recall_miss_or_gate_rejects(stakes: float) -> None:
    threshold = 0.5
    rep = FakeRepertoire(entries={"cls1": FakeEntry(input_class="cls1", value="cached")})
    gate = ThresholdGate(threshold)

    asyncio.run(repertoire_run(rep, "cls1", stakes=stakes, gate=gate))

    expected_improvise = stakes >= threshold
    assert (rep.improvise_calls == 1) == expected_improvise
