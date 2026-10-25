"""Tests for the maistro-automaton actor machinery.

Covers the six public contracts: drives, producers/gates, the motivation
arbiter (including refractory), cage verdicts, the tick reactor, and the
episode sink port. All tests are deterministic — injected clocks, explicit
ticks — because that is the entire selling point.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from maistro_automaton import (
    CageCheckpoint,
    CageVerdict,
    Candidate,
    DriveSpec,
    DriveTerm,
    DriveTermKind,
    Episode,
    EpisodeSink,
    MotivationArbiter,
    Producer,
    ThresholdGate,
    TickReactor,
    candidate,
    compute_drive,
    compute_drives,
    first_block,
)


class _Mood:
    valence = 0.8
    arousal = 0.4


# ---------------------------------------------------------------- drives -----


def test_drive_sums_facet_and_mood_terms() -> None:
    spec = DriveSpec(
        name="curiosity",
        terms=(
            DriveTerm("inquisitiveness", 0.7, DriveTermKind.FACET),
            DriveTerm("arousal", 0.3, DriveTermKind.MOOD),
        ),
    )
    # 4/5 * 0.7 + 0.4 * 0.3 = 0.56 + 0.12
    assert compute_drive(spec, {"inquisitiveness": 4.0}, _Mood()) == pytest.approx(0.68)


def test_missing_facet_contributes_zero() -> None:
    spec = DriveSpec(name="d", terms=(DriveTerm("absent_facet", 1.0, DriveTermKind.FACET),))
    assert compute_drive(spec, {}, _Mood()) == 0.0


def test_missing_mood_attribute_raises_typed_error() -> None:
    spec = DriveSpec(name="d", terms=(DriveTerm("missing_mood", 1.0, DriveTermKind.MOOD),))
    with pytest.raises(AttributeError, match="missing_mood"):
        compute_drive(spec, {}, _Mood())


def test_drive_clamps_to_ceiling() -> None:
    spec = DriveSpec(
        name="d",
        terms=(DriveTerm("arousal", 5.0, DriveTermKind.MOOD),),
        ceiling=0.9,
    )
    assert compute_drive(spec, {}, _Mood()) == 0.9


def test_compute_drives_covers_all_specs() -> None:
    specs = (
        DriveSpec("a", (DriveTerm("arousal", 1.0, DriveTermKind.MOOD),)),
        DriveSpec("b", (DriveTerm("valence", 0.5, DriveTermKind.MOOD),)),
    )
    levels = compute_drives(specs, {}, _Mood())
    assert levels == {"a": pytest.approx(0.4), "b": pytest.approx(0.4)}


# ------------------------------------------------------- producers/gates -----


def test_threshold_gate_requires_full_levels() -> None:
    gate = ThresholdGate(drive="starvation", threshold=0.5)
    assert gate.passes({"starvation": 0.5}) is True
    assert gate.passes({"starvation": 0.49}) is False
    assert gate.passes({}) is False


def test_producer_protocol_is_structural() -> None:
    class _P:
        name = "p"

        def should_fire(self, drive_levels: Any) -> bool:
            return True

        def submit(self, drive_levels: Any) -> Candidate | None:
            return None

    assert isinstance(_P(), Producer)


# ------------------------------------------------------------- arbiter -------


def _mk_clock(start: datetime):
    state = {"now": start}

    def clock() -> datetime:
        return state["now"]

    def advance(minutes: float) -> None:
        state["now"] = state["now"] + timedelta(minutes=minutes)

    return clock, advance


def test_arbiter_fires_highest_drive_first() -> None:
    clock, _ = _mk_clock(datetime(2026, 9, 21, tzinfo=UTC))
    arb = MotivationArbiter(clock=clock)
    arb.submit(candidate("low", "p", "d", 0.2))
    arb.submit(candidate("high", "p", "d", 0.9))
    fired = arb.tick()
    assert fired is not None and fired.key == "high"
    assert arb.park_count() == 1


def test_arbiter_silence_is_legal() -> None:
    clock, _ = _mk_clock(datetime(2026, 9, 21, tzinfo=UTC))
    assert MotivationArbiter(clock=clock).tick() is None


def test_refractory_blocks_recently_fired_key() -> None:
    clock, advance = _mk_clock(datetime(2026, 9, 21, tzinfo=UTC))
    arb = MotivationArbiter(clock=clock, refractory={"churn": timedelta(minutes=30)})
    arb.submit(candidate("churn", "p", "d", 1.0))

    first = arb.tick()
    assert first is not None and first.key == "churn"
    assert arb.in_refractory("churn") is True

    arb.submit(candidate("churn", "p", "d", 1.0))
    assert arb.tick() is None, "refractory must suppress immediate re-fire"

    advance(minutes=31)
    arb.submit(candidate("churn", "p", "d", 1.0))
    again = arb.tick()
    assert again is not None and again.key == "churn"


def test_refractory_respects_per_key_cooldowns() -> None:
    clock, advance = _mk_clock(datetime(2026, 9, 21, tzinfo=UTC))
    arb = MotivationArbiter(clock=clock, refractory={"a": timedelta(minutes=10)})
    arb.submit(candidate("a", "p", "d", 1.0))
    arb.submit(candidate("b", "p", "d", 0.5))
    assert arb.tick() is not None
    # a is in refractory; b must still fire on the next tick
    second = arb.tick()
    assert second is not None and second.key == "b"
    advance(minutes=11)
    arb.submit(candidate("a", "p", "d", 1.0))
    assert arb.tick() is not None


# ---------------------------------------------------------------- cage -------


def _gate(code: str, blocks: bool) -> CageCheckpoint:
    class _C:
        checkpoint = code

        def check(self, candidate: Candidate) -> CageVerdict:
            return CageVerdict.block(code, code) if blocks else CageVerdict.allow(code)

    return _C()


def test_first_block_returns_first_blocking_verdict() -> None:
    c = candidate("k", "p", "d", 0.9)
    verdict = first_block([_gate("OK1", False), _gate("WEDGE", True)], c)
    assert verdict.blocked is True
    assert verdict.reason_code == "WEDGE"
    assert verdict.checkpoint == "WEDGE"


def test_all_allow_yields_allowed_verdict() -> None:
    c = candidate("k", "p", "d", 0.1)
    verdict = first_block([_gate("OK1", False), _gate("OK2", False)], c)
    assert verdict.blocked is False
    assert verdict.reason_code == "ALLOWED"


def test_verdict_is_frozen() -> None:
    v = CageVerdict.block("cp", "R", detail=1)
    with pytest.raises(Exception, match="assign"):
        v.blocked = False  # type: ignore[misc]


# -------------------------------------------------------------- reactor ------


def test_tick_reactor_counts_and_dispatches() -> None:
    seen: list[int] = []
    r = TickReactor()
    r.register(seen.append)
    r.tick(3)
    assert seen == [1, 2, 3]
    assert r.tick_count == 3


def test_interval_trigger_fire_and_idempotent_register() -> None:
    r = TickReactor()
    hits: list[str] = []
    t1 = r.register_interval_trigger("t", timedelta(minutes=1), lambda: hits.append("x"))
    t2 = r.register_interval_trigger(
        "t", timedelta(minutes=5), lambda: hits.append("y"), idempotent=True
    )
    assert t1 is t2
    r.fire_trigger("t")
    assert hits == ["x"]
    r.unregister_trigger("t")
    r.fire_trigger("t")
    assert hits == ["x"]


# --------------------------------------------------------------- memory ------


def test_episode_sink_protocol_is_structural() -> None:
    class _Sink:
        def store_episode(self, episode: Episode) -> str:
            return episode.ref or "ok"

    assert isinstance(_Sink(), EpisodeSink)
    ep = Episode(
        content="did a thing", tier="accomplishment", source="i_did", weight=0.7, intent="test"
    )
    assert _Sink().store_episode(ep) == "ok"
