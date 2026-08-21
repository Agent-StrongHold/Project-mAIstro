"""Tests for InMemoryScheduleStore CRUD + cron field validation."""

from __future__ import annotations

import pytest

from maistro.scheduling.store import (
    MAX_TASKS_PER_USER,
    InMemoryScheduleStore,
    ScheduledTask,
    TaskExecution,
    _expand_field,
    validate_cron,
)


class TestValidateCronFieldCount:
    def test_wrong_field_count_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 5 fields"):
            validate_cron("* * * *")

    def test_too_many_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 5 fields"):
            validate_cron("* * * * * *")


class TestValidateCronFieldShapes:
    def test_invalid_minute_field_raises(self) -> None:
        with pytest.raises(ValueError, match="bad minute field"):
            validate_cron("99 * * * *")

    def test_invalid_hour_field_raises(self) -> None:
        with pytest.raises(ValueError, match="bad hour field"):
            validate_cron("0 99 * * *")

    def test_invalid_day_of_month_field_raises(self) -> None:
        with pytest.raises(ValueError, match="bad day-of-month field"):
            validate_cron("0 0 99 * *")

    def test_invalid_month_field_raises(self) -> None:
        with pytest.raises(ValueError, match="bad month field"):
            validate_cron("0 0 1 99 *")

    def test_invalid_day_of_week_field_raises(self) -> None:
        with pytest.raises(ValueError, match="bad day-of-week field"):
            validate_cron("0 0 1 1 99")

    def test_step_value_zero_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="bad minute field"):
            validate_cron("*/0 * * * *")

    def test_range_out_of_bounds_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="bad hour field"):
            validate_cron("0 20-30 * * *")

    def test_range_reversed_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="bad hour field"):
            validate_cron("0 10-5 * * *")

    def test_list_with_out_of_bounds_value_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="bad minute field"):
            validate_cron("0,99 * * * *")

    def test_non_numeric_field_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="bad minute field"):
            validate_cron("abc * * * *")


class TestStoreCreate:
    @pytest.mark.asyncio
    async def test_create_assigns_id_and_created_at(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        assert task.id != ""
        assert task.created_at > 0

    @pytest.mark.asyncio
    async def test_create_enforces_max_tasks_per_user(self) -> None:
        store = InMemoryScheduleStore()
        for i in range(MAX_TASKS_PER_USER):
            await store.create(ScheduledTask(user_id="u1", name=f"t{i}", schedule="0 * * * *"))
        with pytest.raises(ValueError, match="maximum"):
            await store.create(ScheduledTask(user_id="u1", name="overflow", schedule="0 * * * *"))

    @pytest.mark.asyncio
    async def test_create_max_tasks_is_per_user(self) -> None:
        store = InMemoryScheduleStore()
        for i in range(MAX_TASKS_PER_USER):
            await store.create(ScheduledTask(user_id="u1", name=f"t{i}", schedule="0 * * * *"))
        # A different user is unaffected by u1's limit.
        task = await store.create(ScheduledTask(user_id="u2", name="t", schedule="0 * * * *"))
        assert task.id != ""

    @pytest.mark.asyncio
    async def test_create_invalid_schedule_raises_before_storing(self) -> None:
        store = InMemoryScheduleStore()
        with pytest.raises(ValueError):
            await store.create(ScheduledTask(user_id="u1", name="t", schedule="bad"))
        assert await store.list_for_user(user_id="u1") == []


class TestStoreGet:
    @pytest.mark.asyncio
    async def test_get_existing_task(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        fetched = await store.get(task.id)
        assert fetched is task

    @pytest.mark.asyncio
    async def test_get_missing_task_returns_none(self) -> None:
        store = InMemoryScheduleStore()
        assert await store.get("nonexistent") is None


class TestStoreListForUser:
    @pytest.mark.asyncio
    async def test_list_for_user_filters_by_user(self) -> None:
        store = InMemoryScheduleStore()
        mine = await store.create(ScheduledTask(user_id="u1", name="mine", schedule="0 * * * *"))
        await store.create(ScheduledTask(user_id="u2", name="theirs", schedule="0 * * * *"))
        tasks = await store.list_for_user(user_id="u1")
        assert [t.id for t in tasks] == [mine.id]


class TestStoreUpdate:
    @pytest.mark.asyncio
    async def test_update_missing_task_returns_none(self) -> None:
        store = InMemoryScheduleStore()
        assert await store.update("nonexistent", name="new") is None

    @pytest.mark.asyncio
    async def test_update_mutable_field(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        updated = await store.update(task.id, name="renamed")
        assert updated is not None
        assert updated.name == "renamed"

    @pytest.mark.asyncio
    async def test_update_schedule_validates_new_cron(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        updated = await store.update(task.id, schedule="0 0 * * *")
        assert updated is not None
        assert updated.schedule == "0 0 * * *"

    @pytest.mark.asyncio
    async def test_update_protects_id_user_id_created_at(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        original_id, original_user, original_created = task.id, task.user_id, task.created_at
        updated = await store.update(
            task.id, id="hacked", user_id="hacked", created_at=999.0, name="ok"
        )
        assert updated is not None
        assert updated.id == original_id
        assert updated.user_id == original_user
        assert updated.created_at == original_created
        assert updated.name == "ok"

    @pytest.mark.asyncio
    async def test_update_ignores_unknown_attribute(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        updated = await store.update(task.id, nonexistent_field="x")
        assert updated is not None
        assert not hasattr(updated, "nonexistent_field")


class TestStoreDelete:
    @pytest.mark.asyncio
    async def test_delete_existing_task_returns_true(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        assert await store.delete(task.id) is True
        assert await store.get(task.id) is None

    @pytest.mark.asyncio
    async def test_delete_missing_task_returns_false(self) -> None:
        store = InMemoryScheduleStore()
        assert await store.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete_clears_execution_history(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        await store.record_execution(task.id, TaskExecution(id="e1", task_id=task.id))
        await store.delete(task.id)
        assert task.id not in store._executions


class TestStoreExecutionHistory:
    @pytest.mark.asyncio
    async def test_record_and_get_history_most_recent_first(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        await store.record_execution(task.id, TaskExecution(id="e1", task_id=task.id))
        await store.record_execution(task.id, TaskExecution(id="e2", task_id=task.id))
        history = await store.get_history(task.id)
        assert [e.id for e in history] == ["e2", "e1"]

    @pytest.mark.asyncio
    async def test_get_history_respects_limit(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        for i in range(5):
            await store.record_execution(task.id, TaskExecution(id=f"e{i}", task_id=task.id))
        history = await store.get_history(task.id, limit=2)
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_get_history_for_unknown_task_returns_empty(self) -> None:
        store = InMemoryScheduleStore()
        assert await store.get_history("nonexistent") == []

    @pytest.mark.asyncio
    async def test_get_history_for_task_with_no_executions_returns_empty(self) -> None:
        store = InMemoryScheduleStore()
        task = await store.create(ScheduledTask(user_id="u1", name="t", schedule="0 * * * *"))
        assert await store.get_history(task.id) == []


class TestStoreListEnabled:
    @pytest.mark.asyncio
    async def test_list_enabled_filters_disabled_tasks(self) -> None:
        store = InMemoryScheduleStore()
        enabled = await store.create(ScheduledTask(user_id="u1", name="on", schedule="0 * * * *"))
        disabled_task = await store.create(
            ScheduledTask(user_id="u1", name="off", schedule="0 0 * * *")
        )
        await store.update(disabled_task.id, enabled=False)
        result = await store.list_enabled()
        assert [t.id for t in result] == [enabled.id]


class TestExpandFieldFallback:
    def test_signed_numeric_value_falls_back_to_single_value(self) -> None:
        # Defensive fallback for direct calls with unvalidated input — a
        # signed numeric string matches none of the wildcard/step/range/list
        # patterns but is still int()-parseable.
        assert _expand_field("-5", 0, 59) == [-5]
