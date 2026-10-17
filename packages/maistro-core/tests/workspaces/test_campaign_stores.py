"""One suite over every campaign store (SPEC-092626-1831, #103).

`InMemoryCampaignStore` is the reference; the SQLite durable twin must agree
with it on every rule, because a store that drifts from its protocol is how
operator controls quietly stop surviving a restart (AC-5).

The restart test is the point of the durable leg: it closes the connection
the writes went through, opens a fresh one over the same database file, and
reads the controls back with their actor and time intact. The in-memory leg
cannot run it — an in-memory store *is* its process memory — which is exactly
why the wiring refuses to ship it to real deployments silently.
"""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite
import pytest

from maistro.workspaces.campaigns import (
    Actor,
    ActorKind,
    AuditKind,
    AutonomyMode,
    BudgetUsage,
    CampaignPolicy,
    ControlKind,
    InMemoryCampaignStore,
    ParkEvidence,
)
from maistro.workspaces.campaigns.sqlite_store import SqliteCampaignStore
from maistro.workspaces.campaigns.store import (
    CampaignNotFound,
    CampaignStore,
    ControlNotFound,
    ParkNotFound,
)

OPERATOR = Actor(kind=ActorKind.USER, id="operator-1")
OTHER = Actor(kind=ActorKind.USER, id="operator-2")


def _sqlite_store(tmp_path):
    return _SqliteLeg(tmp_path)


class _SqliteLeg:
    """Owns the connection lifecycle for the durable leg."""

    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "campaigns.db"
        self._conn: aiosqlite.Connection | None = None

    async def store(self) -> CampaignStore:
        from maistro.workspaces.campaigns.sqlite_store import SqliteCampaignStore

        conn = await aiosqlite.connect(self._path)
        self._conn = conn
        sqlite_store = SqliteCampaignStore(conn)
        await sqlite_store.ensure_schema()
        return sqlite_store

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest, tmp_path) -> CampaignStore:
    if request.param == "memory":
        yield InMemoryCampaignStore()
        return
    leg = _sqlite_store(tmp_path)
    try:
        yield await leg.store()
    finally:
        await leg.close()


async def test_campaign_round_trip_and_versioning(store: CampaignStore) -> None:
    created = await store.create_campaign(
        workspace_id="w1",
        name="sprint",
        actor=OPERATOR,
        policy=CampaignPolicy(),
    )
    fetched = await store.get_campaign(created.campaign_id)
    assert fetched is not None
    assert fetched.name == "sprint"
    assert fetched.workspace_id == "w1"
    assert fetched.created_by == OPERATOR
    assert fetched.policy_version == 1

    updated = await store.update_policy(created.campaign_id, CampaignPolicy(), actor=OTHER)
    assert updated.policy_version == 2
    assert updated.superseded_version == 1
    # The latest read answers with the new version; history stays readable.
    assert (await store.get_campaign(created.campaign_id)).policy_version == 2  # type: ignore[union-attr]
    versions = await store.list_campaigns("w1", latest_only=False)
    assert [c.policy_version for c in versions] == [1, 2]
    assert (await store.list_campaigns("w1"))[0].campaign_id == created.campaign_id


async def test_get_unknown_campaign_is_none_but_require_raises(store: CampaignStore) -> None:
    assert await store.get_campaign("nope") is None
    with pytest.raises(CampaignNotFound):
        await store.require_campaign("nope")


async def test_controls_round_trip_with_actor_and_policy_version(
    store: CampaignStore,
) -> None:
    campaign = await store.create_campaign(workspace_id="w1", name="c", actor=OPERATOR)
    control = await store.set_control(
        campaign.campaign_id,
        ControlKind.PIN_NEXT,
        actor=OPERATOR,
        item_id="item-1",
    )
    listed = await store.list_controls(campaign.campaign_id)
    assert len(listed) == 1
    assert listed[0].kind is ControlKind.PIN_NEXT
    assert listed[0].item_id == "item-1"
    assert listed[0].set_by == OPERATOR
    assert listed[0].policy_version == 1
    assert listed[0].active

    cleared = await store.clear_control(control.control_id, actor=OTHER)
    assert not cleared.active
    assert cleared.cleared_by == OTHER
    # active_only filters, but history remains.
    assert await store.list_controls(campaign.campaign_id, active_only=True) == []
    assert len(await store.list_controls(campaign.campaign_id)) == 1
    # Clearing twice is read-idempotent, not a second decision.
    again = await store.clear_control(control.control_id, actor=OTHER)
    assert again.cleared_at == cleared.cleared_at
    kinds = [r.kind for r in await store.audit_trail(campaign.campaign_id)]
    assert kinds.count(AuditKind.CONTROL_CLEARED) == 1


async def test_unknown_control_raises(store: CampaignStore) -> None:
    with pytest.raises(ControlNotFound):
        await store.clear_control("missing", actor=OPERATOR)


async def test_create_campaign_accepts_an_explicit_id_and_timestamp(
    store: CampaignStore,
) -> None:
    """A caller that already owns the identity (a migration, a restore) can
    supply it; the record comes back exactly as given, not re-stamped."""
    created = await store.create_campaign(
        workspace_id="w1",
        name="imported",
        actor=OPERATOR,
        campaign_id="fixed-id",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert created.campaign_id == "fixed-id"
    assert created.created_at == datetime(2026, 9, 1, tzinfo=UTC)
    fetched = await store.get_campaign("fixed-id")
    assert fetched is not None
    assert fetched.created_at == created.created_at


async def test_list_campaigns_without_a_workspace_lists_across_workspaces(
    store: CampaignStore,
) -> None:
    await store.create_campaign(workspace_id="w1", name="one", actor=OPERATOR, campaign_id="a-one")
    await store.create_campaign(workspace_id="w2", name="two", actor=OPERATOR, campaign_id="b-two")
    listed = await store.list_campaigns()
    assert [(campaign.workspace_id, campaign.name) for campaign in listed] == [
        ("w1", "one"),
        ("w2", "two"),
    ]


async def test_set_control_accepts_an_explicit_timestamp(store: CampaignStore) -> None:
    """Replayed decisions keep the moment they were made, not the replay's."""
    campaign = await store.create_campaign(workspace_id="w1", name="c", actor=OPERATOR)
    control = await store.set_control(
        campaign.campaign_id,
        ControlKind.PIN_NEXT,
        actor=OPERATOR,
        item_id="item-1",
        set_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert control.set_at == datetime(2026, 9, 2, tzinfo=UTC)


@pytest.mark.parametrize(
    ("override", "expected_restored"),
    [
        (None, "autonomous"),
        (AutonomyMode.HUMAN_REVIEW_REQUIRED, "human-review-required"),
        # A human-only override clears back to the campaign default, not to
        # itself: the control and the override are two records, and the clear
        # returns the item to where the campaign would have put it.
        (AutonomyMode.HUMAN_ONLY, "autonomous"),
    ],
)
async def test_clearing_human_only_records_the_restored_mode(
    store: CampaignStore, override: AutonomyMode | None, expected_restored: str
) -> None:
    campaign = await store.create_campaign(workspace_id="w1", name="c", actor=OPERATOR)
    if override is not None:
        await store.set_item_record(
            campaign.campaign_id, "item-1", actor=OPERATOR, mode_override=override
        )
    control = await store.set_control(
        campaign.campaign_id,
        ControlKind.HUMAN_ONLY,
        actor=OPERATOR,
        item_id="item-1",
    )
    await store.clear_control(control.control_id, actor=OTHER)
    (decision,) = [
        record
        for record in await store.audit_trail(campaign.campaign_id)
        if record.kind is AuditKind.CONTROL_CLEARED
    ]
    assert decision.payload["restored_mode"] == expected_restored
    assert decision.actor == OTHER


async def test_unparking_twice_is_read_idempotent(store: CampaignStore) -> None:
    campaign = await store.create_campaign(workspace_id="w1", name="c", actor=OPERATOR)
    park = await store.park_item(
        campaign.campaign_id,
        "item-1",
        ParkEvidence(reason="blocked upstream"),
        actor=OPERATOR,
    )
    first = await store.unpark_item(park.park_id, actor=OTHER)
    assert not first.active
    again = await store.unpark_item(park.park_id, actor=OTHER)
    assert again.unparked is not None
    assert again.unparked == first.unparked
    unpark_decisions = sum(
        1
        for record in await store.audit_trail(campaign.campaign_id)
        if record.kind is AuditKind.ITEM_UNPARKED
    )
    assert unpark_decisions == 1


async def test_append_audit_with_no_records_appends_nothing(store: CampaignStore) -> None:
    before = await store.audit_trail()
    await store.append_audit()
    assert await store.audit_trail() == before


async def test_item_records_store_mode_and_priority_as_given(
    store: CampaignStore,
) -> None:
    campaign = await store.create_campaign(workspace_id="w1", name="c", actor=OPERATOR)
    await store.set_item_record(
        campaign.campaign_id,
        "item-1",
        actor=OPERATOR,
        mode_override=AutonomyMode.HUMAN_REVIEW_REQUIRED,
        human_priority=2.5,
    )
    records = await store.list_item_records(campaign.campaign_id)
    assert len(records) == 1
    assert records[0].mode_override is AutonomyMode.HUMAN_REVIEW_REQUIRED
    assert records[0].human_priority == 2.5
    # A whole-record replace clears what it does not carry.
    await store.set_item_record(campaign.campaign_id, "item-1", actor=OPERATOR, human_priority=4.0)
    records = await store.list_item_records(campaign.campaign_id)
    assert records[0].human_priority == 4.0
    assert records[0].mode_override is None


async def test_parks_hold_evidence_and_unpark_is_attributed(
    store: CampaignStore,
) -> None:
    campaign = await store.create_campaign(workspace_id="w1", name="c", actor=OPERATOR)
    park = await store.park_item(
        campaign.campaign_id,
        "item-1",
        ParkEvidence(reason="waiting on upstream", failing_check="ci/lint"),
        actor=OPERATOR,
    )
    active = await store.list_parks(campaign.campaign_id, active_only=True)
    assert len(active) == 1
    assert active[0].evidence.reason == "waiting on upstream"
    assert active[0].evidence.failing_check == "ci/lint"

    unparked = await store.unpark_item(park.park_id, actor=OTHER)
    assert not unparked.active
    assert unparked.unparked is not None
    assert unparked.unparked.unparked_by == OTHER
    assert await store.list_parks(campaign.campaign_id, active_only=True) == []
    with pytest.raises(ParkNotFound):
        await store.unpark_item("missing", actor=OPERATOR)


async def test_usage_accumulates(store: CampaignStore) -> None:
    campaign = await store.create_campaign(workspace_id="w1", name="c", actor=OPERATOR)
    await store.record_usage(campaign.campaign_id, actor=OPERATOR, cost_usd=1.25, minutes=10.0)
    usage = await store.record_usage(
        campaign.campaign_id, actor=OPERATOR, cost_usd=0.75, completions=1
    )
    assert usage.cost_usd == pytest.approx(2.0)
    assert usage.minutes == pytest.approx(10.0)
    assert usage.completions == 1
    assert (await store.get_usage(campaign.campaign_id)).cost_usd == pytest.approx(2.0)
    assert await store.get_usage("nope") == BudgetUsage()


async def test_audit_trail_is_attributed_and_scoped(store: CampaignStore) -> None:
    first = await store.create_campaign(workspace_id="w1", name="one", actor=OPERATOR)
    second = await store.create_campaign(workspace_id="w2", name="two", actor=OPERATOR)
    await store.set_control(first.campaign_id, ControlKind.PAUSE, actor=OPERATOR)
    trail = await store.audit_trail(first.campaign_id)
    assert [r.kind for r in trail] == [
        AuditKind.CAMPAIGN_CREATED,
        AuditKind.CONTROL_SET,
    ]
    assert all(r.actor == OPERATOR for r in trail)
    assert all(r.policy_version == 1 for r in trail)
    assert len(await store.audit_trail()) >= 3  # both campaigns' records
    limited = await store.audit_trail(limit=1)
    assert len(limited) == 1
    assert limited[0].kind is AuditKind.CONTROL_SET
    _ = second


@pytest.mark.ac("SPEC-092626-1831/AC-5")
async def test_operator_controls_survive_a_restart(tmp_path) -> None:
    """AC-5 against the real durable store: write controls through one
    connection, close it, reopen the database, and read them back with their
    actor, timestamps and policy version intact."""
    from maistro.workspaces.campaigns.sqlite_store import SqliteCampaignStore

    path = tmp_path / "restart.db"
    campaign_id: str
    control_ids: dict[ControlKind, str]
    async with aiosqlite.connect(path) as conn:
        store = SqliteCampaignStore(conn)
        await store.ensure_schema()
        campaign = await store.create_campaign(workspace_id="w1", name="durable", actor=OPERATOR)
        campaign_id = campaign.campaign_id
        control_ids = {}
        for kind, item_id in (
            (ControlKind.PIN_NEXT, "item-1"),
            (ControlKind.PAUSE, None),
            (ControlKind.EXCLUDE, "item-2"),
            (ControlKind.HUMAN_ONLY, "item-3"),
        ):
            control = await store.set_control(campaign_id, kind, actor=OPERATOR, item_id=item_id)
            control_ids[kind] = control.control_id
        await store.park_item(
            campaign_id,
            "item-4",
            ParkEvidence(reason="flaky suite", failing_check="ci/e2e"),
            actor=OPERATOR,
        )
        await store.set_item_record(campaign_id, "item-5", actor=OPERATOR, human_priority=1.5)
    # Connection closed: everything above is only in the database now.

    async with aiosqlite.connect(path) as conn:
        reopened = SqliteCampaignStore(conn)
        await reopened.ensure_schema()
        campaign = await reopened.require_campaign(campaign_id)
        assert campaign.name == "durable"
        assert campaign.created_by == OPERATOR

        controls = {
            control.kind: control
            for control in await reopened.list_controls(campaign_id, active_only=True)
        }
        assert set(controls) == set(ControlKind)
        for kind, control in controls.items():
            assert control.set_by == OPERATOR
            assert control.set_at is not None
            assert control.policy_version == 1
            assert control.control_id == control_ids[kind]

        parks = await reopened.list_parks(campaign_id, active_only=True)
        assert [p.evidence.reason for p in parks] == ["flaky suite"]

        records = await reopened.list_item_records(campaign_id)
        assert records[0].human_priority == 1.5

        trail = await reopened.audit_trail(campaign_id)
        assert trail
        assert all(r.actor == OPERATOR for r in trail)

        # The deletion path clears every bounded row.
        removed = await reopened.delete_campaign(campaign_id)
        assert removed > 0
        assert await reopened.get_campaign(campaign_id) is None
        assert await reopened.list_controls(campaign_id) == []
        assert await reopened.list_parks(campaign_id) == []
        assert await reopened.audit_trail(campaign_id) == []


# -- concurrency: the database, not the process, is the authority --------
#
# Two connections share one database file: the second plays the concurrent
# writer that clears/unparks between the first's read and its write. The
# conditional UPDATE matches zero rows, and the first writer must return what
# the database actually holds instead of its own stale copy.


async def _two_writers(
    tmp_path,
) -> tuple[SqliteCampaignStore, SqliteCampaignStore, str]:
    first_conn = await aiosqlite.connect(tmp_path / "shared.db")
    second_conn = await aiosqlite.connect(tmp_path / "shared.db")
    first = SqliteCampaignStore(first_conn)
    second = SqliteCampaignStore(second_conn)
    await first.ensure_schema()
    await second.ensure_schema()
    campaign = await first.create_campaign(workspace_id="w1", name="shared", actor=OPERATOR)
    return first, second, campaign.campaign_id


async def test_a_control_cleared_concurrently_returns_the_databases_record(
    tmp_path,
) -> None:
    first, second, campaign_id = await _two_writers(tmp_path)
    try:
        control = await first.set_control(
            campaign_id, ControlKind.EXCLUDE, actor=OPERATOR, item_id="item-1"
        )
        # The concurrent writer wins the race.
        await second.clear_control(control.control_id, actor=OTHER)
        # The first writer's read is stale; its conditional UPDATE matches
        # nothing, and the decision reads what the database holds.
        cleared = await first.clear_control(control.control_id, actor=OPERATOR)
        assert not cleared.active
        assert cleared.cleared_by == OTHER
        decisions = sum(
            1
            for record in await first.audit_trail(campaign_id)
            if record.kind is AuditKind.CONTROL_CLEARED
        )
        assert decisions == 1
    finally:
        await first._conn.close()
        await second._conn.close()


async def test_a_control_cleared_concurrently_for_a_missing_row_is_refused(
    tmp_path,
) -> None:
    first, second, campaign_id = await _two_writers(tmp_path)
    try:
        control = await first.set_control(
            campaign_id, ControlKind.PIN_NEXT, actor=OPERATOR, item_id="item-1"
        )
        # The row disappears between the read and the write: the database is
        # the authority, and it no longer holds the control.
        async with first._conn.execute(
            "DELETE FROM campaign_controls WHERE control_id = ?", (control.control_id,)
        ):
            pass
        await first._conn.commit()
        with pytest.raises(ControlNotFound):
            await first.clear_control(control.control_id, actor=OPERATOR)
    finally:
        await first._conn.close()
        await second._conn.close()


async def test_require_control_raises_for_an_unknown_control(tmp_path) -> None:
    first, second, _campaign_id = await _two_writers(tmp_path)
    try:
        with pytest.raises(ControlNotFound):
            await first.require_control("missing")
    finally:
        await first._conn.close()
        await second._conn.close()


async def test_a_park_unparked_concurrently_returns_the_databases_record(
    tmp_path,
) -> None:
    first, second, campaign_id = await _two_writers(tmp_path)
    try:
        park = await first.park_item(
            campaign_id,
            "item-1",
            ParkEvidence(reason="blocked upstream"),
            actor=OPERATOR,
        )
        await second.unpark_item(park.park_id, actor=OTHER)
        unparked = await first.unpark_item(park.park_id, actor=OPERATOR)
        assert not unparked.active
        assert unparked.unparked is not None
        assert unparked.unparked.unparked_by == OTHER
        unpark_decisions = sum(
            1
            for record in await first.audit_trail(campaign_id)
            if record.kind is AuditKind.ITEM_UNPARKED
        )
        assert unpark_decisions == 1
    finally:
        await first._conn.close()
        await second._conn.close()


async def test_require_park_raises_for_an_unknown_park(tmp_path) -> None:
    first, second, _campaign_id = await _two_writers(tmp_path)
    try:
        with pytest.raises(ParkNotFound):
            await first.require_park("missing")
    finally:
        await first._conn.close()
        await second._conn.close()
