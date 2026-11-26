"""Targeted tests for PgScheduleStore uncovered branches."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from maistro.scheduling.model import Schedule
from maistro.scheduling.pg_store import PgScheduleStore

pytestmark = pytest.mark.pg


@pytest_asyncio.fixture
async def pg_store(pg_pool):
    """Create a PgScheduleStore with a real PG pool."""
    return PgScheduleStore(pg_pool)


@pytest_asyncio.fixture
async def sample_schedule():
    """Create a sample schedule for testing."""
    return Schedule(
        schedule_id=str(uuid.uuid4()),
        workspace_id="test-workspace",
        project_id="test-project",
        enabled=True,
        next_due_at=datetime.now(UTC) + timedelta(hours=1),
        max_runs=10,
        fires=0,
    )


class TestPgScheduleStorePut:
    """Test PgScheduleStore.put - covers lines 54-90."""

    @pytest.mark.asyncio
    async def test_put_new_schedule(self, pg_store, sample_schedule):
        """Test putting a new schedule creates it with cursors zeroed."""
        result = await pg_store.put(sample_schedule)
        assert result.schedule_id == sample_schedule.schedule_id
        assert result.workspace_id == sample_schedule.workspace_id
        assert result.fires == 0  # Cursors zeroed on put

    @pytest.mark.asyncio
    async def test_put_overwrites_existing(self, pg_store, sample_schedule):
        """Test putting over existing schedule preserves cursors."""
        await pg_store.put(sample_schedule)

        # Modify and put again
        modified = Schedule(
            schedule_id=sample_schedule.schedule_id,
            workspace_id=sample_schedule.workspace_id,
            project_id=sample_schedule.project_id,
            enabled=False,
            next_due_at=datetime.now(UTC) + timedelta(hours=2),
            max_runs=5,
            fires=3,  # This should be preserved
        )
        result = await pg_store.put(modified)
        assert result.enabled is False
        assert result.fires == 3  # Cursors preserved

    @pytest.mark.asyncio
    async def test_put_after_delete_restores_tombstone(self, pg_store, sample_schedule):
        """Test put after delete removes tombstone (line 80-86)."""
        await pg_store.put(sample_schedule)
        await pg_store.delete(sample_schedule.schedule_id)

        # Put again - should remove tombstone
        restored = Schedule(
            schedule_id=sample_schedule.schedule_id,
            workspace_id=sample_schedule.workspace_id,
            project_id=sample_schedule.project_id,
            enabled=True,
            next_due_at=datetime.now(UTC) + timedelta(hours=1),
        )
        result = await pg_store.put(restored)
        assert result.enabled is True
        # Tombstone should be removed


class TestPgScheduleStoreListAll:
    """Test PgScheduleStore.list_all and tombstoned_ids - covers lines 127-136."""

    @pytest.mark.asyncio
    async def test_list_all_returns_all_schedules(self, pg_store, sample_schedule):
        """Test list_all returns all non-deleted schedules."""
        await pg_store.put(sample_schedule)
        schedules = await pg_store.list_all()
        assert any(s.schedule_id == sample_schedule.schedule_id for s in schedules)

    @pytest.mark.asyncio
    async def test_tombstoned_ids_returns_deleted_ids(self, pg_store, sample_schedule):
        """Test tombstoned_ids returns deleted schedule IDs."""
        await pg_store.put(sample_schedule)
        await pg_store.delete(sample_schedule.schedule_id)
        tombstoned = await pg_store.tombstoned_ids()
        assert sample_schedule.schedule_id in tombstoned

    @pytest.mark.asyncio
    async def test_list_all_excludes_tombstoned(self, pg_store, sample_schedule):
        """Test list_all excludes tombstoned schedules."""
        await pg_store.put(sample_schedule)
        await pg_store.delete(sample_schedule.schedule_id)
        schedules = await pg_store.list_all()
        assert not any(s.schedule_id == sample_schedule.schedule_id for s in schedules)


class TestPgScheduleStoreRecordFire:
    """Test PgScheduleStore.record_fire - covers lines 170-195."""

    @pytest.mark.asyncio
    async def test_record_fire_basic(self, pg_store, sample_schedule):
        """Test basic record_fire advances schedule."""
        await pg_store.put(sample_schedule)
        fired_at = datetime.now(UTC)
        result = await pg_store.record_fire(
            sample_schedule.schedule_id,
            fired_at=fired_at,
            run_id=str(uuid.uuid4()),
        )
        assert result.fires == 1
        assert result.next_due_at > datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_record_fire_max_runs_disables(self, pg_store, sample_schedule):
        """Test record_fire disables schedule when max_runs reached."""
        schedule = Schedule(
            schedule_id=str(uuid.uuid4()),
            workspace_id="test-workspace",
            project_id="test-project",
            enabled=True,
            next_due_at=datetime.now(UTC) + timedelta(hours=1),
            max_runs=1,
            fires=0,
        )
        await pg_store.put(schedule)

        # Fire once - should reach max_runs
        result = await pg_store.record_fire(
            schedule.schedule_id,
            fired_at=datetime.now(UTC),
            run_id=str(uuid.uuid4()),
        )
        assert result.fires == 1
        assert result.enabled is False  # Disabled at max_runs

    @pytest.mark.asyncio
    async def test_record_fire_nonexistent_returns_none(self, pg_store):
        """Test record_fire returns None for nonexistent schedule."""
        result = await pg_store.record_fire(
            str(uuid.uuid4()),
            fired_at=datetime.now(UTC),
            run_id=str(uuid.uuid4()),
        )
        assert result is None


class TestPgScheduleStoreReserveFire:
    """Test PgScheduleStore.reserve_fire - covers lines 198-215."""

    @pytest.mark.asyncio
    async def test_reserve_fire_basic(self, pg_store, sample_schedule):
        """Test reserve_fire reserves a fire slot."""
        await pg_store.put(sample_schedule)
        fire_id = str(uuid.uuid4())
        result = await pg_store.reserve_fire(sample_schedule.schedule_id, fire_id=fire_id)
        assert result is not None
        # Check pending fire was added

    @pytest.mark.asyncio
    async def test_reserve_fire_nonexistent_returns_none(self, pg_store):
        """Test reserve_fire returns None for nonexistent schedule."""
        result = await pg_store.reserve_fire(str(uuid.uuid4()), fire_id=str(uuid.uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_reserve_fire_exhausted_returns_none(self, pg_store, sample_schedule):
        """Test reserve_fire returns None when no fires left."""
        schedule = Schedule(
            schedule_id=str(uuid.uuid4()),
            workspace_id="test-workspace",
            project_id="test-project",
            enabled=True,
            next_due_at=datetime.now(UTC) + timedelta(hours=1),
            max_runs=0,  # No fires allowed
            fires=0,
        )
        await pg_store.put(schedule)
        result = await pg_store.reserve_fire(schedule.schedule_id, fire_id=str(uuid.uuid4()))
        assert result is None


class TestPgScheduleStoreSettlePendingFire:
    """Test PgScheduleStore.settle_pending_fire - covers lines 218-231."""

    @pytest.mark.asyncio
    async def test_settle_pending_fire_success(self, pg_store, sample_schedule):
        """Test settling a pending fire."""
        await pg_store.put(sample_schedule)
        fire_id = str(uuid.uuid4())
        await pg_store.reserve_fire(sample_schedule.schedule_id, fire_id=fire_id)
        run_id = str(uuid.uuid4())
        result = await pg_store.settle_pending_fire(
            sample_schedule.schedule_id,
            fire_id=fire_id,
            run_id=run_id,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_settle_pending_fire_nonexistent_returns_none(self, pg_store):
        """Test settle_pending_fire returns None for nonexistent."""
        result = await pg_store.settle_pending_fire(
            str(uuid.uuid4()),
            fire_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_settle_pending_fire_invalid_fire_id_returns_none(
        self, pg_store, sample_schedule
    ):
        """Test settle_pending_fire returns None for invalid fire_id."""
        await pg_store.put(sample_schedule)
        result = await pg_store.settle_pending_fire(
            sample_schedule.schedule_id,
            fire_id="invalid-fire-id",
            run_id=str(uuid.uuid4()),
        )
        assert result is None


class TestPgScheduleStoreDelete:
    """Test PgScheduleStore.delete and tombstone behavior."""

    @pytest.mark.asyncio
    async def test_delete_creates_tombstone(self, pg_store, sample_schedule):
        """Test delete creates tombstone entry."""
        await pg_store.put(sample_schedule)
        result = await pg_store.delete(sample_schedule.schedule_id)
        assert result is True

        tombstoned = await pg_store.tombstoned_ids()
        assert sample_schedule.schedule_id in tombstoned

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, pg_store):
        """Test delete returns False for nonexistent."""
        result = await pg_store.delete(str(uuid.uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_put_after_delete_removes_tombstone(self, pg_store, sample_schedule):
        """Test put after delete removes tombstone (line 80-86)."""
        await pg_store.put(sample_schedule)
        await pg_store.delete(sample_schedule.schedule_id)

        restored = Schedule(
            schedule_id=sample_schedule.schedule_id,
            workspace_id=sample_schedule.workspace_id,
            project_id=sample_schedule.project_id,
            enabled=True,
            next_due_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await pg_store.put(restored)

        tombstoned = await pg_store.tombstoned_ids()
        assert sample_schedule.schedule_id not in tombstoned
