"""Tests for trigger definitions and glob pattern matching (SPEC-070226-b234)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.events.invocations import ReplaySafety
from maistro.events.trigger_store import (
    InMemoryTriggerStore,
    SqliteTriggerStore,
    TriggerDefinition,
    TriggerStore,
    pattern_matches,
)


class TestPatternMatching:
    @pytest.mark.parametrize(
        ("pattern", "event_type", "expected"),
        [
            ("agent.*", "agent.created", True),
            ("agent.*", "agent.delegated", True),
            ("agent.*", "task.created", False),
            ("agent.*", "agent.task.created", False),  # * is one segment
            ("agent.created", "agent.created", True),
            ("agent.created", "agent.deleted", False),
            ("*.failed", "task.failed", True),
            ("*.failed", "handler.failed", True),
            ("*.failed", "task.completed", False),
            ("*", "agent", True),
            ("*", "agent.created", False),
            ("agent.*.done", "agent.build.done", True),
            ("agent.*.done", "agent.done", False),
            ("", "agent.created", False),
            ("agent.*", "", False),
        ],
    )
    @pytest.mark.ac("SPEC-070226-b234/AC-2")
    def test_glob(self, pattern: str, event_type: str, expected: bool) -> None:
        assert pattern_matches(pattern, event_type) is expected

    @pytest.mark.ac("SPEC-070226-b234/AC-2")
    def test_disabled_trigger_never_matches(self) -> None:
        t = TriggerDefinition(event_pattern="agent.*", enabled=False)
        assert not t.matches("agent.created")


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[TriggerStore]:
    if request.param == "memory":
        yield InMemoryTriggerStore()
    else:
        conn = await aiosqlite.connect(":memory:")
        s = SqliteTriggerStore(conn)
        await s.ensure_schema()
        yield s
        await conn.close()


class TestTriggerStore:
    async def test_add_get_roundtrip(self, store: TriggerStore) -> None:
        t = TriggerDefinition(
            name="log-delegations",
            event_pattern="agent.delegated",
            handler_url="http://localhost:8000/handlers/log",
            replay_safety=ReplaySafety.IDEMPOTENT,
            contract_ref="log-handler-contract-v3",
        )
        await store.add(t)
        got = await store.get(t.trigger_id)
        assert got is not None
        assert got.name == "log-delegations"
        assert got.event_pattern == "agent.delegated"
        assert got.handler_url == "http://localhost:8000/handlers/log"
        assert got.enabled
        assert got.replay_safety is ReplaySafety.IDEMPOTENT
        assert got.contract_ref == "log-handler-contract-v3"

    async def test_unknown_replay_safety_defaults_unproven(self, store: TriggerStore) -> None:
        """#1060 §2 fail-closed default: existing rows (and new ones without an
        explicit enrollment) are unsafe for automatic replay."""
        trigger = TriggerDefinition(trigger_id="unproven", event_pattern="task.created")
        await store.add(trigger)
        got = await store.get("unproven")
        assert got is not None
        assert got.replay_safety is ReplaySafety.UNPROVEN
        assert got.effective_replay_safety is ReplaySafety.UNPROVEN

    async def test_a_safe_declaration_without_contract_ref_reads_unproven(
        self, store: TriggerStore
    ) -> None:
        """Idempotent/read_only enrollment requires the operator-approved
        contract ref; the stored declaration is never allowed to upgrade an
        invalid enrollment (#1060 §2)."""
        for safety in (ReplaySafety.IDEMPOTENT, ReplaySafety.READ_ONLY):
            trigger = TriggerDefinition(
                trigger_id=f"noref-{safety.value}",
                event_pattern="task.created",
                replay_safety=safety,
                contract_ref="",
            )
            await store.add(trigger)
            got = await store.get(trigger.trigger_id)
            assert got is not None
            assert got.replay_safety is safety  # the declaration round-trips
            assert got.effective_replay_safety is ReplaySafety.UNPROVEN  # but does not act

    async def test_read_only_enrollment_round_trips(self, store: TriggerStore) -> None:
        trigger = TriggerDefinition(
            trigger_id="ro",
            event_pattern="task.created",
            replay_safety=ReplaySafety.READ_ONLY,
            contract_ref="readonly-v1",
        )
        await store.add(trigger)
        got = await store.get("ro")
        assert got is not None
        assert got.effective_replay_safety is ReplaySafety.READ_ONLY

    async def test_get_missing(self, store: TriggerStore) -> None:
        assert await store.get("nope") is None

    async def test_remove(self, store: TriggerStore) -> None:
        t = TriggerDefinition(event_pattern="a.b")
        await store.add(t)
        await store.remove(t.trigger_id)
        assert await store.get(t.trigger_id) is None
        assert await store.list_triggers() == []

    @pytest.mark.ac("SPEC-070226-b234/AC-2")
    async def test_get_matching(self, store: TriggerStore) -> None:
        t1 = TriggerDefinition(name="agents", event_pattern="agent.*")
        t2 = TriggerDefinition(name="tasks", event_pattern="task.*")
        t3 = TriggerDefinition(name="exact", event_pattern="agent.created")
        await store.add(t1)
        await store.add(t2)
        await store.add(t3)
        matched = await store.get_matching("agent.created")
        assert {t.name for t in matched} == {"agents", "exact"}

    @pytest.mark.ac("SPEC-070226-b234/AC-2")
    async def test_set_enabled_excludes_from_matching(self, store: TriggerStore) -> None:
        t = TriggerDefinition(name="agents", event_pattern="agent.*")
        await store.add(t)
        await store.set_enabled(t.trigger_id, False)
        assert await store.get_matching("agent.created") == []
        await store.set_enabled(t.trigger_id, True)
        assert len(await store.get_matching("agent.created")) == 1
