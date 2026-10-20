"""One suite over every workspace working-log store (#301, M4-H).

``InMemoryWorkspaceLogStore`` is the reference; the SQLite durable twin must
agree with it on every rule, because the whole feature rests on the log being
the lossless system of record: a twin that drops ``seq`` on readback or
silently duplicates a content-addressed result breaks the working-set
derivation in ways the in-process leg would never show.

Two regressions this suite pins, both found by running the SQLite leg before
it had ever been executed:

* ``append`` used to serialize the *pre-append* entry into the payload
  column, so every readback came back with ``seq=None`` and the projection
  filtered the entire log out. Log position belongs to the log: the row's
  ``seq`` column is authoritative over the payload.
* aiosqlite rows are tuples, so named row access (``row["payload"]``) raised
  ``TypeError`` on the first durable read.

The restart test is the point of the durable leg: it closes the connection
the writes went through, opens a fresh one over the same database file, and
re-derives the same working set — the property "log-as-context" is bought for.
"""

from __future__ import annotations

from typing import Any

import aiosqlite
import pytest

from maistro.memory.working.store import (
    InMemoryWorkspaceLogStore,
    WorkspaceLogStore,
)
from maistro.memory.working.types import (
    ObservationKind,
    WorkingResult,
    WorkspaceObservation,
    content_digest,
    make_result_id,
    observation,
    reset_entry,
    summary_entry,
)

WS = "ws-conformance"
OTHER_WS = "ws-other"


class _SqliteLeg:
    """Owns the aiosqlite connection lifecycle for the durable leg."""

    def __init__(self, tmp_path: Any) -> None:
        self._path = tmp_path / "working-log.db"
        self._conn: aiosqlite.Connection | None = None

    async def store(self) -> WorkspaceLogStore:
        from maistro.memory.working.sqlite_store import SqliteWorkspaceLogStore

        conn = await aiosqlite.connect(self._path)
        self._conn = conn
        store = SqliteWorkspaceLogStore(conn)
        await store.ensure_schema()
        return store

    async def stop(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def restart(self) -> WorkspaceLogStore:
        """Close the connection the writes went through; open a fresh one."""
        await self.stop()
        return await self.store()


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest, tmp_path: Any) -> Any:
    if request.param == "memory":
        yield InMemoryWorkspaceLogStore()
        return
    leg = _SqliteLeg(tmp_path)
    yield await leg.store()
    await leg.stop()


async def _append_three(store: WorkspaceLogStore, ws: str = WS) -> list[WorkspaceObservation]:
    first = await store.append(observation(workspace_id=ws, cycle=1, text="explored deploy"))
    second = await store.append(
        observation(
            workspace_id=ws, cycle=2, text="hypothesis: flaky", kind=ObservationKind.HYPOTHESIS
        )
    )
    third = await store.append(
        observation(workspace_id=ws, cycle=3, text="pinned fact", survive_reset=True)
    )
    return [first, second, third]


class TestAppendAndOrder:
    async def test_append_assigns_sequential_seq_ignoring_caller_seq(
        self, store: WorkspaceLogStore
    ) -> None:
        first, second, third = await _append_three(store)
        assert [e.seq for e in (first, second, third)] == [1, 2, 3]
        # A caller-chosen seq is ignored: log position belongs to the log.
        usurper = WorkspaceObservation(
            workspace_id=WS,
            entry_id=first.entry_id + "-x",
            kind=ObservationKind.OBSERVATION,
            cycle=1,
            text="claims seq 999",
            seq=999,
        )
        stored = await store.append(usurper)
        assert stored.seq == 4

    async def test_entries_read_back_with_log_position(self, store: WorkspaceLogStore) -> None:
        """The seq=None-payload regression: readbacks carry the log position."""
        appended = await _append_three(store)
        read = await store.list_entries(WS)
        assert [e.entry_id for e in read] == [e.entry_id for e in appended]
        assert [e.seq for e in read] == [1, 2, 3]

    async def test_workspaces_are_isolated(self, store: WorkspaceLogStore) -> None:
        await _append_three(store)
        await store.append(observation(workspace_id=OTHER_WS, cycle=1, text="other workspace"))
        assert len(await store.list_entries(WS)) == 3
        assert len(await store.list_entries(OTHER_WS)) == 1
        assert all(e.workspace_id == WS for e in await store.list_entries(WS))


class TestFilters:
    async def test_kinds_after_seq_limit_filters(self, store: WorkspaceLogStore) -> None:
        await _append_three(store)
        hypotheses = await store.list_entries(WS, kinds=(ObservationKind.HYPOTHESIS,))
        assert [e.seq for e in hypotheses] == [2]
        after = await store.list_entries(WS, after_seq=1)
        assert [e.seq for e in after] == [2, 3]
        limited = await store.list_entries(WS, limit=2)
        assert [e.seq for e in limited] == [1, 2]

    async def test_survive_reset_filter(self, store: WorkspaceLogStore) -> None:
        await _append_three(store)
        pinned = await store.list_entries(WS, survive_reset=True)
        assert [e.text for e in pinned] == ["pinned fact"]
        unpinned = await store.list_entries(WS, survive_reset=False)
        assert [e.seq for e in unpinned] == [1, 2]

    async def test_get_entry_and_latest_entry(self, store: WorkspaceLogStore) -> None:
        appended = await _append_three(store)
        got = await store.get_entry(WS, appended[1].entry_id)
        assert got is not None and got.text == "hypothesis: flaky" and got.seq == 2
        assert await store.get_entry(WS, "missing") is None
        latest_any = await store.latest_entry(WS)
        assert latest_any is not None and latest_any.seq == 3
        latest_hyp = await store.latest_entry(WS, kinds=(ObservationKind.HYPOTHESIS,))
        assert latest_hyp is not None and latest_hyp.seq == 2
        assert await store.latest_entry(WS, kinds=(ObservationKind.RESET,)) is None


class TestAddressableResults:
    async def test_put_result_is_idempotent_on_content_address(
        self, store: WorkspaceLogStore
    ) -> None:
        result = WorkingResult(
            workspace_id=WS,
            result_id=make_result_id(WS, "tool", "payload"),
            source="tool",
            content="payload",
        )
        assert await store.put_result(result) is True
        # Identical payloads inside one Workspace are one record.
        again = WorkingResult(
            workspace_id=WS,
            result_id=make_result_id(WS, "tool", "payload"),
            source="tool",
            content="payload",
        )
        assert await store.put_result(again) is False
        got = await store.get_result(WS, result.result_id)
        assert got is not None
        assert got.content == "payload" and got.digest == content_digest("payload")

    async def test_results_are_workspace_scoped(self, store: WorkspaceLogStore) -> None:
        result = WorkingResult(
            workspace_id=WS,
            result_id=make_result_id(WS, "tool", "payload"),
            source="tool",
            content="payload",
        )
        await store.put_result(result)
        # The same payload in another Workspace is a different record; its
        # content address mixes the Workspace in.
        assert await store.get_result(OTHER_WS, result.result_id) is None

    async def test_results_are_addressable_by_id(self, store: WorkspaceLogStore) -> None:
        one = WorkingResult(workspace_id=WS, result_id="res-one", source="a", content="one")
        two = WorkingResult(workspace_id=WS, result_id="res-two", source="b", content="two")
        await store.put_result(one)
        await store.put_result(two)
        got = await store.get_result(WS, "res-two")
        assert got is not None and got.content == "two"
        # The id decides: same Workspace, unknown id, other Workspace — none.
        assert await store.get_result(WS, "res-missing") is None
        assert await store.get_result(OTHER_WS, "res-one") is None


class TestMarkerEntries:
    async def test_summary_and_reset_roundtrip_meta(self, store: WorkspaceLogStore) -> None:
        appended = await _append_three(store)
        summary = await store.append(
            summary_entry(
                workspace_id=WS,
                cycle=3,
                folded_ids=[appended[0].entry_id],
                text="rolled summary",
            )
        )
        reset = await store.append(
            reset_entry(workspace_id=WS, cycle=3, survival_ids=[appended[2].entry_id])
        )
        latest = await store.latest_entry(WS, kinds=(ObservationKind.RESET,))
        assert latest is not None and latest.entry_id == reset.entry_id
        assert latest.meta["survival"] == [appended[2].entry_id]
        read_summary = await store.get_entry(WS, summary.entry_id)
        assert read_summary is not None
        assert read_summary.meta["folds"] == [appended[0].entry_id]


class TestPurge:
    async def test_purge_workspace_is_the_driven_deletion(self, store: WorkspaceLogStore) -> None:
        await _append_three(store)
        await store.put_result(
            WorkingResult(workspace_id=WS, result_id="res-x", source="a", content="x")
        )
        await store.append(observation(workspace_id=OTHER_WS, cycle=1, text="kept"))
        assert await store.purge_workspace(WS) == 3
        assert len(await store.list_entries(WS)) == 0
        assert await store.get_result(WS, "res-x") is None
        # The other Workspace is untouched.
        assert len(await store.list_entries(OTHER_WS)) == 1
        assert await store.purge_workspace(WS) == 0


class TestSqliteRestart:
    async def test_log_and_results_survive_a_reconnect(self, tmp_path: Any) -> None:
        """The durable leg's reason to exist: the working set a reset left
        behind is exactly what a restart re-reads."""
        leg = _SqliteLeg(tmp_path)
        store = await leg.store()
        appended = await _append_three(store)
        result = WorkingResult(workspace_id=WS, result_id="res-keep", source="a", content="keep me")
        await store.put_result(result)
        await store.append(
            reset_entry(workspace_id=WS, cycle=3, survival_ids=[appended[2].entry_id])
        )
        await leg.stop()

        reopened = await leg.restart()
        assert len(await reopened.list_entries(WS)) == 4
        latest = await reopened.latest_entry(WS, kinds=(ObservationKind.RESET,))
        assert latest is not None
        assert latest.meta["survival"] == [appended[2].entry_id]
        got = await reopened.get_result(WS, "res-keep")
        assert got is not None and got.content == "keep me"
        # And the schema upgrade is idempotent over an existing database.
        from maistro.memory.working.sqlite_store import SqliteWorkspaceLogStore

        assert isinstance(reopened, SqliteWorkspaceLogStore)
        await reopened.ensure_schema()
        assert len(await reopened.list_entries(WS)) == 4
