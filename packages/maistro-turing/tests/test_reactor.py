"""Tests for cognition/reactor.py: FakeReactor tick and spawn."""

from __future__ import annotations

from datetime import timedelta

from maistro_turing.cognition.reactor import FakeReactor, IntervalTrigger, Reactor


def test_fake_reactor_satisfies_protocol() -> None:
    assert isinstance(FakeReactor(), Reactor)


def test_tick_increments_count() -> None:
    r = FakeReactor()
    assert r.tick_count == 0
    r.tick()
    assert r.tick_count == 1
    r.tick(3)
    assert r.tick_count == 4


def test_register_handler_called_on_tick() -> None:
    r = FakeReactor()
    calls: list[int] = []
    r.register(lambda tick: calls.append(tick))
    r.tick(2)
    assert calls == [1, 2]


def test_spawn_runs_sync_and_returns_future() -> None:
    r = FakeReactor()
    f = r.spawn(lambda x: x + 1, 41)
    assert f.result() == 42


def test_spawn_exception_propagates() -> None:
    r = FakeReactor()
    f = r.spawn(lambda: 1 / 0)
    assert f.exception() is not None


def test_interval_trigger_register_and_fire() -> None:
    r = FakeReactor()
    fires: list[str] = []
    trigger = r.register_interval_trigger(
        "test", timedelta(seconds=10), lambda: fires.append("fired")
    )
    assert isinstance(trigger, IntervalTrigger)
    r.fire_trigger("test")
    assert fires == ["fired"]
    assert trigger.fire_count == 1


def test_interval_trigger_idempotent() -> None:
    r = FakeReactor()
    t1 = r.register_interval_trigger("x", timedelta(seconds=1), lambda: None)
    t2 = r.register_interval_trigger("x", timedelta(seconds=1), lambda: None, idempotent=True)
    assert t1 is t2


def test_unregister_trigger() -> None:
    r = FakeReactor()
    r.register_interval_trigger("x", timedelta(seconds=1), lambda: None)
    r.unregister_trigger("x")
    assert "x" not in r.triggers
