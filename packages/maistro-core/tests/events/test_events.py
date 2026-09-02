"""Tests for event bus, triggers, and cross-service integrations."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.events.bus import (
    Event,
    EventBus,
    EventCategory,
    Trigger,
    TriggerActionFailure,
    TriggerCondition,
)
from maistro.events.recipes import (
    coinswarm_drawdown_alert,
    coinswarm_evolution_complete,
    coinswarm_fitness_alert,
    security_event_escalation,
)


class TestTriggerCondition:
    def test_eq(self):
        c = TriggerCondition(field="x", op="eq", value=5)
        assert c.matches({"x": 5})
        assert not c.matches({"x": 3})

    def test_gt(self):
        c = TriggerCondition(field="val", op="gt", value=0.5)
        assert c.matches({"val": 0.7})
        assert not c.matches({"val": 0.3})

    def test_lt(self):
        c = TriggerCondition(field="fitness", op="lt", value=0.3)
        assert c.matches({"fitness": 0.1})
        assert not c.matches({"fitness": 0.5})

    def test_contains(self):
        c = TriggerCondition(field="name", op="contains", value="agent")
        assert c.matches({"name": "my-agent-1"})
        assert not c.matches({"name": "swarm"})

    def test_missing_field(self):
        c = TriggerCondition(field="missing", op="eq", value="x")
        assert not c.matches({"other": "y"})


class TestTrigger:
    def test_matches_event_type(self):
        t = Trigger(event_types=["agent_fitness"])
        e = Event(event_type="agent_fitness")
        assert t.matches(e)

    def test_rejects_wrong_type(self):
        t = Trigger(event_types=["agent_fitness"])
        e = Event(event_type="drawdown")
        assert not t.matches(e)

    def test_matches_conditions(self):
        t = Trigger(
            event_types=["agent_fitness"],
            conditions=[TriggerCondition(field="fitness", op="lt", value=0.3)],
        )
        e = Event(event_type="agent_fitness", payload={"fitness": 0.1})
        assert t.matches(e)

    def test_rejects_conditions(self):
        t = Trigger(
            event_types=["agent_fitness"],
            conditions=[TriggerCondition(field="fitness", op="lt", value=0.3)],
        )
        e = Event(event_type="agent_fitness", payload={"fitness": 0.5})
        assert not t.matches(e)

    def test_disabled(self):
        t = Trigger(enabled=False)
        e = Event()
        assert not t.matches(e)

    def test_cooldown(self):
        import time

        t = Trigger(cooldown_seconds=100.0)
        t.last_fired = time.time()
        e = Event()
        assert not t.matches(e)


class TestEventBus:
    async def test_emit_no_triggers(self):
        bus = EventBus()
        fired = await bus.emit(Event(event_type="test"))
        assert fired == []

    async def test_emit_rejects_a_fact_that_cannot_project_itself(self):
        """The bus is a compatibility consumer, not a universal Event sink."""
        bus = EventBus()

        with pytest.raises(TypeError) as exc:
            await bus.emit(object())

        assert "explicit to_legacy_event() projection" in str(exc.value)
        assert bus.get_history() == []

    async def test_emit_rejects_a_projection_that_is_not_a_legacy_event(self):
        class _LyingProjector:
            def to_legacy_event(self) -> Any:
                return {"event_type": "not an Event"}

        bus = EventBus()

        with pytest.raises(TypeError) as exc:
            await bus.emit(_LyingProjector())

        assert "maistro.events.bus.Event" in str(exc.value)
        assert bus.get_history() == []

    @pytest.mark.ac("SPEC-228/AC-4")
    async def test_emit_fires_trigger(self):
        bus = EventBus()
        results = []
        trigger = Trigger(
            name="test",
            event_types=["test"],
            action_type="log",
        )
        bus.add_trigger(trigger)

        async def log(_trigger, event):
            results.append(event.event_type)

        bus.register_handler("log", log)
        fired = await bus.emit(Event(event_type="test"))
        assert results == ["test"]
        assert len(fired) == 1
        assert fired[0] is trigger
        assert fired[0].fire_count == 1
        assert fired[0].last_fired is not None

    async def test_cooldown_prevents_refire(self):
        bus = EventBus()
        bus.add_trigger(
            Trigger(
                name="cd",
                event_types=["test"],
                action_type="log",
                cooldown_seconds=999,
            )
        )

        async def noop(_trigger, _event):
            return None

        bus.register_handler("log", noop)
        await bus.emit(Event(event_type="test"))
        fired = await bus.emit(Event(event_type="test"))
        assert len(fired) == 0

    async def test_history(self):
        bus = EventBus()
        await bus.emit(Event(event_type="a", source="x"))
        await bus.emit(Event(event_type="b", source="y"))
        history = bus.get_history()
        assert len(history) == 2
        assert bus.get_history(source="x") == [history[0]]

    async def test_list_triggers(self):
        bus = EventBus()
        bus.add_trigger(Trigger(name="t1"))
        bus.add_trigger(Trigger(name="t2"))
        triggers = bus.list_triggers()
        assert len(triggers) == 2

    async def test_remove_trigger(self):
        bus = EventBus()
        t = Trigger(trigger_id="abc", name="t1")
        bus.add_trigger(t)
        bus.remove_trigger("abc")
        assert bus.list_triggers() == []

    @pytest.mark.ac("SPEC-228/AC-4")
    async def test_subscriber(self):
        bus = EventBus()
        received = []

        async def subscribe_handler(event):
            received.append(event.event_type)

        bus.subscribe(subscribe_handler)
        await bus.emit(Event(event_type="hello"))
        assert received == ["hello"]


class TestEmitFiringAuthority:
    """A trigger is counted as fired only when its handler actually completed (#836).

    Guards the defect where ``emit`` incremented ``fire_count`` / ``last_fired``
    and reported the trigger as fired even when no handler was registered for
    the action type or the handler raised and the exception was swallowed.
    """

    async def test_no_handler_matched_trigger_is_not_counted_as_fired(self, caplog):
        bus = EventBus()
        trigger = Trigger(name="typo", event_types=["test"], action_type="no_such_action")
        bus.add_trigger(trigger)

        with caplog.at_level("WARNING", logger="maistro.events"):
            fired = await bus.emit(Event(event_type="test"))

        assert fired == []
        assert trigger.fire_count == 0
        assert trigger.last_fired is None
        # The unmatched action_type must be visible, not silent.
        assert "no handler is registered" in caplog.text
        assert "no_such_action" in caplog.text

    async def test_no_handler_does_not_start_cooldown(self):
        bus = EventBus()
        trigger = Trigger(
            name="late-handler",
            event_types=["test"],
            action_type="log",
            cooldown_seconds=999,
        )
        bus.add_trigger(trigger)

        # First emit matches but no handler is registered yet: not fired.
        fired = await bus.emit(Event(event_type="test"))
        assert fired == []

        # Registering the handler afterwards must still allow the trigger to
        # fire: the earlier no-handler delivery must not have started cooldown.
        observed = []

        async def log(_trigger, event):
            observed.append(event.event_type)

        bus.register_handler("log", log)
        fired = await bus.emit(Event(event_type="test"))
        assert observed == ["test"]
        assert [t.name for t in fired] == ["late-handler"]
        assert trigger.fire_count == 1

    async def test_raising_handler_is_not_counted_and_error_is_surfaced(self):
        bus = EventBus()
        trigger = Trigger(name="boom", event_types=["test"], action_type="log")
        bus.add_trigger(trigger)

        async def boom(_trigger, _event):
            raise RuntimeError("handler exploded")

        bus.register_handler("log", boom)

        with pytest.raises(TriggerActionFailure) as excinfo:
            await bus.emit(Event(event_type="test"))

        # The original exception is surfaced, not swallowed.
        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert str(excinfo.value.__cause__) == "handler exploded"
        assert [(t.name, str(err)) for t, err in excinfo.value.failures] == [
            ("boom", "handler exploded")
        ]
        # The failed emission must not count as success.
        assert trigger.fire_count == 0
        assert trigger.last_fired is None

    async def test_raising_handler_failure_does_not_start_cooldown(self):
        bus = EventBus()
        trigger = Trigger(
            name="retry",
            event_types=["test"],
            action_type="log",
            cooldown_seconds=999,
        )
        bus.add_trigger(trigger)
        calls = []

        async def flaky(_trigger, _event):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient failure")

        bus.register_handler("log", flaky)

        with pytest.raises(TriggerActionFailure):
            await bus.emit(Event(event_type="test"))

        # Second delivery must still reach the handler: the failed attempt
        # must not have armed the cooldown as if the action ran.
        fired = await bus.emit(Event(event_type="test"))
        assert [t.name for t in fired] == ["retry"]
        assert trigger.fire_count == 1
        assert len(calls) == 2

    async def test_raising_handler_does_not_abort_other_triggers_or_subscribers(self):
        bus = EventBus()
        bus.add_trigger(Trigger(name="bad", event_types=["test"], action_type="explode"))
        good = Trigger(name="good", event_types=["test"], action_type="log")
        bus.add_trigger(good)

        async def explode(_trigger, _event):
            raise RuntimeError("handler exploded")

        async def log(_trigger, _event):
            return None

        bus.register_handler("explode", explode)
        bus.register_handler("log", log)

        received = []

        async def subscriber(event):
            received.append(event.event_type)

        bus.subscribe(subscriber)

        with pytest.raises(TriggerActionFailure) as excinfo:
            await bus.emit(Event(event_type="test"))

        # The healthy trigger and the subscriber still ran; only the failing
        # one is excluded from the success counters and reported.
        assert [t.name for t, _err in excinfo.value.failures] == ["bad"]
        assert good.fire_count == 1
        assert received == ["test"]
        assert bus.get_history()[-1].event_type == "test"

    async def test_sync_handler_is_reported_as_failure_not_counted_as_success(self):
        # The declared handler contract is a coroutine function; a sync
        # callable is a contract violation and must surface as a failure
        # rather than being counted as a fired trigger via the old swallow.
        bus = EventBus()
        trigger = Trigger(name="sync", event_types=["test"], action_type="log")
        bus.add_trigger(trigger)

        def sync_handler(_trigger, _event):  # not async on purpose
            return None

        bus.register_handler("log", sync_handler)

        with pytest.raises(TriggerActionFailure):
            await bus.emit(Event(event_type="test"))

        assert trigger.fire_count == 0
        assert trigger.last_fired is None


class TestEmitRobustness:
    @pytest.mark.ac("SPEC-228/AC-4")
    async def test_bad_payload_trigger_does_not_stop_other_triggers(self):
        # A numeric-comparison condition against a non-numeric payload must not
        # abort the whole emit loop; later triggers/subscribers must still run.
        bus = EventBus()
        fired_names: list[str] = []

        async def async_log(trigger, _event):
            fired_names.append(trigger.name)

        # First trigger: gt comparison against a non-numeric payload value.
        bus.add_trigger(
            Trigger(
                name="numeric",
                event_types=["fitness"],
                conditions=[TriggerCondition(field="fitness", op="gt", value=0.5)],
                action_type="log",
            )
        )
        # Second trigger: a plain match that should still fire.
        bus.add_trigger(
            Trigger(
                name="plain",
                event_types=["fitness"],
                action_type="log",
            )
        )
        bus.register_handler("log", async_log)

        received: list[str] = []

        async def subscriber(event):
            received.append(event.event_type)

        bus.subscribe(subscriber)

        # payload fitness is non-numeric → float() would raise inside matches.
        fired = await bus.emit(Event(event_type="fitness", payload={"fitness": "n/a"}))

        # The bad numeric trigger must not match (and must not raise), and the
        # plain trigger plus the subscriber must still run.
        assert "plain" in fired_names
        assert [t.name for t in fired] == ["plain"]
        assert received == ["fitness"]

    async def test_missing_template_key_does_not_silently_drop_action(self):
        # A handler whose message template references a payload key that is
        # missing must still run (the action must not be silently dropped).
        from maistro.events.handlers import conductor_chat_action

        captured: dict[str, Any] = {}

        async def fake_post(url, json, headers, timeout):
            captured["message"] = json["messages"][0]["content"]

            class _Resp:
                status_code = 200

            return _Resp()

        import maistro.events.handlers as handlers_mod

        class _FakeClient:
            post = staticmethod(fake_post)

        handlers_mod.set_service_client(_FakeClient())  # type: ignore[arg-type]
        try:
            trigger = Trigger(
                name="escalate",
                action_type="conductor_chat",
                action_config={
                    "message": "Agent {agent_id} severity {severity}",
                    "api_key": "k",
                },
            )
            # payload is missing 'agent_id' → naive .format(**payload) raises KeyError.
            event = Event(event_type="warden_block", payload={"severity": "high"})
            await conductor_chat_action(trigger, event)
        finally:
            handlers_mod.set_service_client(None)

        # The action ran and produced a message; the missing key did not abort it.
        assert "message" in captured, "action was silently dropped on missing template key"
        assert "high" in captured["message"]


class TestRecipes:
    def test_coinswarm_fitness_alert(self):
        t = coinswarm_fitness_alert(fitness_threshold=0.3)
        assert t.event_types == ["agent_fitness"]
        assert t.conditions[0].field == "fitness"
        assert t.conditions[0].value == 0.3
        low_event = Event(event_type="agent_fitness", payload={"fitness": 0.1})
        high_event = Event(event_type="agent_fitness", payload={"fitness": 0.8})
        assert t.matches(low_event)
        assert not t.matches(high_event)

    def test_coinswarm_drawdown_alert(self):
        t = coinswarm_drawdown_alert(max_drawdown=0.15)
        assert t.event_types == ["drawdown"]
        bad = Event(event_type="drawdown", payload={"drawdown_pct": 0.20})
        good = Event(event_type="drawdown", payload={"drawdown_pct": 0.05})
        assert t.matches(bad)
        assert not t.matches(good)

    def test_evolution_complete(self):
        t = coinswarm_evolution_complete(ha_token="test")
        assert t.event_types == ["evolution_cycle_complete"]
        assert t.action_type == "ha"

    def test_security_escalation(self):
        t = security_event_escalation()
        high = Event(event_type="warden_block", payload={"severity": "high"})
        low = Event(event_type="warden_block", payload={"severity": "low"})
        assert t.matches(high)
        assert not t.matches(low)


class TestIntegrations:
    def test_ha_init(self):
        from maistro.integrations.home_assistant import HomeAssistantIntegration

        ha = HomeAssistantIntegration(url="http://ha:8123", token="abc")
        assert ha._url == "http://ha:8123"

    def test_coinswarm_init(self):
        from maistro.integrations.coinswarm import CoinSwarmIntegration

        cs = CoinSwarmIntegration(url="http://swarm:8080")
        assert cs._url == "http://swarm:8080"

    def test_turing_init(self):
        from maistro.integrations.turing import TuringIntegration

        t = TuringIntegration(chat_url="http://turing:9101")
        assert t._chat_url == "http://turing:9101"

    async def test_coinswarm_emit_without_bus(self):
        from maistro.integrations.coinswarm import CoinSwarmIntegration

        cs = CoinSwarmIntegration()
        await cs.emit_agent_fitness("agent-1")

        assert cs._bus is None

    async def test_coinswarm_emit_with_bus(self):
        from maistro.integrations.coinswarm import CoinSwarmIntegration

        bus = EventBus()
        received = []

        async def subscriber(event):
            received.append(event.event_type)

        bus.subscribe(subscriber)
        cs = CoinSwarmIntegration(event_bus=bus)
        await cs.emit_evolution_result({"generation": 5, "best_fitness": 0.85})

        assert received == ["evolution_cycle_complete"]

    async def test_turing_handles_coinswarm_event(self):
        from maistro.integrations.turing import TuringIntegration

        turing = TuringIntegration(chat_url="http://not-real:9101")
        event = Event(
            category=EventCategory.TRADING,
            event_type="evolution_cycle_complete",
            source="coinswarm",
            payload={"generation": 5, "best_fitness": 0.85},
        )
        from unittest.mock import AsyncMock

        turing.chat = AsyncMock()
        await turing.handle_coinswarm_event(event)

        turing.chat.assert_awaited_once()
        assert "Evolution cycle 5" in turing.chat.await_args.args[0]
