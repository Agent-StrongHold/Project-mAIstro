"""DAG run history survives a restart, and says what it keeps (#697).

`DagRunStore` was a `dict` plus a `deque(maxlen=100)` behind a page headed
"Live DAG Runs" with a "Recent runs" sidebar. After a restart it was empty;
after 100 runs the oldest were gone; and nothing at the API said either. It
had no setter at all -- not even the unused kind the other state families
carry -- so there was no seam through which durability could arrive.

The records now go through `stores.dag_runs`, the same `JsonStore` registry
that already backs missions, DAG definitions and dashboard layouts. Subscribers
do not and cannot: an `asyncio.Queue` belongs to one open connection in one
process.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.dag_run_store import (  # noqa: E402
    MAX_EVENTS_PER_RUN,
    MAX_RESULT_CHARS,
    MAX_RUNS,
    DagRun,
    DagRunStore,
)

pytestmark = [pytest.mark.contract("behavioral")]


class FakeRecords:
    """A `JsonStore` narrowed to what the run store uses of it.

    Round-tripping through `json` rather than holding the dict is the point:
    the real store serialises, so a record carrying something unserialisable
    would pass against a plain dict and fail in production.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        import json

        self._data[key] = json.dumps(value)

    def pop(self, key: str, *default: Any) -> Any:
        import json

        if key in self._data:
            return json.loads(self._data.pop(key))
        if default:
            return default[0]
        raise KeyError(key)

    def values(self) -> list[Any]:
        import json

        return [json.loads(raw) for raw in self._data.values()]

    def __len__(self) -> int:
        return len(self._data)


class TestARunSurvivesTheProcess:
    @pytest.mark.ac("SPEC-083026-2601/AC-1")
    async def test_a_run_and_its_events_come_back_after_a_restart(self) -> None:
        records = FakeRecords()
        store = DagRunStore(records=records)
        await store.start_run(run_id="r1", dag_id="d1", user_id="u1")
        await store.append_event(
            "r1", event_type="pm_node_completed", role="intake", capability="parse"
        )
        await store.finish_run("r1", status="completed", result={"cycles": 2})

        restarted = DagRunStore(records=records)

        detail = restarted.get_run("r1")
        assert detail is not None
        assert detail["status"] == "completed"
        assert detail["dag_id"] == "d1"
        assert detail["user_id"] == "u1"
        assert [e["capability"] for e in detail["events"]] == ["parse"]

    @pytest.mark.ac("SPEC-083026-2601/AC-1")
    async def test_a_reader_started_after_the_write_sees_it(self) -> None:
        """A process that starts after a write sees it. That is the claim.

        Named for what it proves. It was called "a second reader sees the same
        history", which reads as live multi-replica freshness -- and that is
        not what this delivers: `JsonStore` is a process cache filled once at
        `initialize()`, so a replica that was *already running* does not see
        another's write until it reloads (Codex, #697).
        """
        records = FakeRecords()
        writer = DagRunStore(records=records)
        await writer.start_run(run_id="r1", dag_id="d1")

        reader = DagRunStore(records=records)

        assert [r["id"] for r in reader.list_runs()] == ["r1"]

    @pytest.mark.ac("SPEC-083026-2601/AC-1")
    async def test_a_running_reader_is_stale_until_it_reloads(self) -> None:
        """The limit, asserted rather than left for a reader to discover.

        `reload()` is the seam. Writing this as a passing test rather than a
        caveat is what stops the next change from assuming freshness it does
        not have.
        """
        records = FakeRecords()
        reader = DagRunStore(records=records)
        writer = DagRunStore(records=records)
        await writer.start_run(run_id="r1", dag_id="d1")

        assert reader.list_runs() == []

        reader.reload()

        assert [r["id"] for r in reader.list_runs()] == ["r1"]

    @pytest.mark.ac("SPEC-083026-2601/AC-1")
    async def test_without_a_records_store_history_is_process_local(self) -> None:
        """The honest fallback, not a silent one: no records, no durability.

        A Conductor started without persistence keeps the behaviour it had.
        What changes is that `retention` says so rather than presenting it as
        history.
        """
        store = DagRunStore()
        await store.start_run(run_id="r1")

        assert store.is_durable is False
        assert DagRunStore().get_run("r1") is None


class TestACompletedRunSaysSo:
    """The route assigned `run.status` and `run.result` to a dataclass that
    declared neither. Python attached both, `to_summary` read neither, and the
    list endpoint therefore never showed a completed run as completed.
    """

    @pytest.mark.ac("SPEC-083026-2601/AC-2")
    async def test_a_new_run_is_running(self) -> None:
        store = DagRunStore()
        await store.start_run(run_id="r1")

        assert store.list_runs()[0]["status"] == "running"

    @pytest.mark.ac("SPEC-083026-2601/AC-2")
    async def test_a_finished_run_reports_its_status_to_the_list(self) -> None:
        store = DagRunStore()
        await store.start_run(run_id="r1")
        await store.finish_run("r1", status="completed", result={"ok": True})

        (summary,) = store.list_runs()

        assert summary["status"] == "completed"
        assert summary["finished_at"] is not None

    @pytest.mark.ac("SPEC-083026-2601/AC-2")
    async def test_a_failed_run_is_finished_too(self) -> None:
        """The branch a reader is likelier to go looking for."""
        store = DagRunStore()
        await store.start_run(run_id="r1")
        await store.finish_run("r1", status="failed")

        (summary,) = store.list_runs()

        assert summary["status"] == "failed"
        assert summary["finished_at"] is not None

    @pytest.mark.ac("SPEC-083026-2601/AC-2")
    async def test_the_status_is_a_declared_field_not_an_attached_attribute(self) -> None:
        """The defect in one assertion: `DagRun` must declare what it reports.

        Against the old dataclass this raises, because `status` was not a
        field -- which is exactly why assigning it silently did nothing.
        """
        assert "status" in DagRun.__dataclass_fields__
        assert "result" in DagRun.__dataclass_fields__


class TestTheBoundIsStatedAndEnforced:
    @pytest.mark.ac("SPEC-083026-2601/AC-3")
    async def test_an_evicted_run_leaves_the_records_too(self) -> None:
        """Or it would come back on the next load and re-expand past the bound."""
        records = FakeRecords()
        store = DagRunStore(max_runs=2, records=records)
        for rid in ("r1", "r2", "r3"):
            await store.start_run(run_id=rid)

        assert len(records) == 2
        assert DagRunStore(max_runs=2, records=records).get_run("r1") is None

    @pytest.mark.ac("SPEC-083026-2601/AC-3")
    async def test_a_reload_keeps_the_newest_and_drops_the_oldest(self) -> None:
        """Order is restored from `started_at`, not from the store's iteration.

        A bounded deque rebuilt in an arbitrary order would evict an arbitrary
        run on the next append, which is worse than the bound itself.
        """
        records = FakeRecords()
        seed = DagRunStore(records=records)
        for rid in ("old", "mid", "new"):
            run = await seed.start_run(run_id=rid)
            run.started_at = {"old": 1.0, "mid": 2.0, "new": 3.0}[rid]
            seed._persist(run)

        restarted = DagRunStore(max_runs=2, records=records)

        assert [r["id"] for r in restarted.list_runs()] == ["new", "mid"]

    @pytest.mark.ac("SPEC-083026-2601/AC-3")
    async def test_the_retention_endpoint_states_the_bound(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes import dag_runs as dag_runs_routes
        from services import dag_run_store

        app = FastAPI()
        app.include_router(dag_runs_routes.router, prefix="/v1/dag-runs")
        records = FakeRecords()
        previous = dag_run_store._global_store
        dag_run_store._global_store = DagRunStore(records=records)
        try:
            body = TestClient(app).get("/v1/dag-runs/retention").json()
        finally:
            dag_run_store._global_store = previous

        assert body == {
            "durable": True,
            "max_runs": MAX_RUNS,
            "max_events_per_run": MAX_EVENTS_PER_RUN,
        }

    @pytest.mark.ac("SPEC-083026-2601/AC-3")
    async def test_retention_is_not_swallowed_by_the_run_id_route(self) -> None:
        """`/retention` is declared before `/{run_id}`, and order is the reason.

        FastAPI matches in definition order, so the parameterised route would
        otherwise claim this path and answer 404 for it. Asserting the status
        rather than the body is what makes this about routing.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes import dag_runs as dag_runs_routes

        app = FastAPI()
        app.include_router(dag_runs_routes.router, prefix="/v1/dag-runs")

        assert TestClient(app).get("/v1/dag-runs/retention").status_code == 200


class TestSubscribersAreNotHistory:
    @pytest.mark.ac("SPEC-083026-2601/AC-4")
    async def test_a_subscriber_is_not_written_to_the_records(self) -> None:
        """A queue has no stored form, and another replica could not use one.

        The record must round-trip through JSON; a store that tried to persist
        its subscribers would raise on the first `json.dumps`.
        """
        records = FakeRecords()
        store = DagRunStore(records=records)
        await store.start_run(run_id="r1")
        store.subscribe("r1")

        await store.append_event("r1", event_type="pm_node_started", role="a", capability="b")

        (stored,) = records.values()
        assert set(stored) == {
            "id",
            "started_at",
            "user_id",
            "finished_at",
            "dag_id",
            "status",
            "result",
            "canonical_run_id",
            "events",
        }


class TestTheCanonicalIdentityHasSomewhereToGo:
    """`POST /v1/dags/{id}/run` mints no canonical Run -- that is #53.

    `execute_dag` creates none, so this path's `canonical_run_id` is empty and
    the field is a place for the identity rather than a claim that one exists.
    Stated as a test so the gap is recorded rather than implied.
    """

    @pytest.mark.ac("SPEC-083026-2601/AC-5")
    async def test_a_run_carries_the_canonical_id_when_given_one(self) -> None:
        store = DagRunStore()
        await store.start_run(run_id="r1", canonical_run_id="run-canonical-1")

        assert store.list_runs()[0]["canonical_run_id"] == "run-canonical-1"

    @pytest.mark.ac("SPEC-083026-2601/AC-5")
    async def test_a_run_without_one_says_so_rather_than_inventing_it(self) -> None:
        """Empty, not the DAG-run id: those are different identities.

        Reusing `id` here would make the run look correlated to a canonical Run
        that does not exist, which is the over-claim the whole convergence
        matrix exists to prevent.
        """
        store = DagRunStore()
        await store.start_run(run_id="r1")

        assert store.list_runs()[0]["canonical_run_id"] == ""


class TestTheStoredRecordIsBounded:
    """`execute_dag` returns every node's full response; the record must not."""

    @pytest.mark.ac("SPEC-083026-2601/AC-3")
    async def test_a_long_response_is_truncated_in_the_record(self) -> None:
        """The run route caps the copy it puts in each event at the same length.

        Without this the result went in verbatim, so a hundred runs of a DAG
        with verbose nodes could grow the SQLite state without bound -- and
        retain more output than the history API ever exposes (Codex, #697).
        """
        records = FakeRecords()
        store = DagRunStore(records=records)
        await store.start_run(run_id="r1")
        await store.finish_run(
            "r1",
            status="completed",
            result={"node_results": {"n1": {"response": "x" * (MAX_RESULT_CHARS + 500)}}},
        )

        (stored,) = records.values()

        assert len(stored["result"]["node_results"]["n1"]["response"]) == MAX_RESULT_CHARS

    @pytest.mark.ac("SPEC-083026-2601/AC-3")
    async def test_the_rest_of_the_result_survives(self) -> None:
        """Truncated, not dropped: the outcome shape is what a reader wants."""
        records = FakeRecords()
        store = DagRunStore(records=records)
        await store.start_run(run_id="r1")
        await store.finish_run(
            "r1",
            status="completed",
            result={"cycles": 3, "node_results": {"n1": {"success": True, "response": "ok"}}},
        )

        (stored,) = records.values()

        assert stored["result"]["cycles"] == 3
        assert stored["result"]["node_results"]["n1"]["success"] is True
        assert stored["result"]["node_results"]["n1"]["response"] == "ok"


class TestLoweringTheBoundRemovesTheRows:
    @pytest.mark.ac("SPEC-083026-2601/AC-3")
    async def test_records_beyond_the_bound_are_deleted_on_load(self) -> None:
        """A store already over `max_runs` must come back down and stay down.

        The truncating slice dropped runs from the working set and left their
        rows, so the backing history stayed permanently above the retention the
        API advertises -- re-dropped on every load, never deleted (Codex, #697).
        """
        records = FakeRecords()
        seeded = DagRunStore(max_runs=5, records=records)
        for i in range(4):
            run = await seeded.start_run(run_id=f"r{i}")
            run.started_at = float(i)
            seeded._persist(run)
        assert len(records) == 4

        DagRunStore(max_runs=2, records=records)

        assert len(records) == 2
        assert sorted(r["id"] for r in records.values()) == ["r2", "r3"]
