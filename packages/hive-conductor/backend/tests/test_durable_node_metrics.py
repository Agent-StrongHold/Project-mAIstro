"""Durable node-metric projection and canonical correlation (#337)."""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.node_metrics_store import NodeMetricsStore, NodeObservation  # noqa: E402

pytestmark = [pytest.mark.contract("behavioral")]


class SharedRecords:
    """A tiny JsonStore-shaped cache over rows shared by two replicas."""

    def __init__(self, shared: dict[str, str]) -> None:
        self.shared = shared
        self.data: dict[str, Any] = {}

    def initialize(self) -> None:
        self.data = {key: json.loads(value) for key, value in self.shared.items()}

    def values(self) -> list[Any]:
        return list(self.data.values())

    def keys(self) -> list[str]:
        return list(self.data)

    def __setitem__(self, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        self.data[key] = json.loads(encoded)
        self.shared[key] = encoded

    def pop(self, key: str, default: Any = None) -> Any:
        self.shared.pop(key, None)
        return self.data.pop(key, default)


def _observation(**overrides: Any) -> NodeObservation:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "node_id": "node-1",
        "node_kind": "llm",
        "project_id": "project-1",
        "dag_id": "dag-1",
        "phase": "COMPLETED",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "workspace_id": "workspace-1",
        "recorded_at": datetime.now(UTC),
        "latency_ms": 42,
    }
    values.update(overrides)
    return NodeObservation(**values)


@pytest.mark.ac("SPEC-083026-2642/AC-6")
def test_metrics_survive_restart_and_refresh_an_existing_replica() -> None:
    rows: dict[str, str] = {}
    writer = NodeMetricsStore(records=SharedRecords(rows))
    reader = NodeMetricsStore(records=SharedRecords(rows))

    writer.append(_observation())
    assert reader.aggregate(window_seconds=3600)["count"] == 1

    restarted = NodeMetricsStore(records=SharedRecords(rows))
    (found,) = restarted.observations(window_seconds=3600)
    assert found.run_id == "run-1"
    assert found.node_run_id == "node-run-1"
    assert found.attempt_id == "attempt-1"
    assert found.workspace_id == "workspace-1"


@pytest.mark.ac("SPEC-083026-2642/AC-7")
def test_canonical_attempt_is_the_idempotency_key() -> None:
    rows: dict[str, str] = {}
    store = NodeMetricsStore(records=SharedRecords(rows))
    store.append(_observation(latency_ms=10))
    store.append(_observation(latency_ms=11))

    assert len(store) == 1
    assert store.observations(window_seconds=3600)[0].latency_ms == 11
    assert list(rows) == ["attempt-1"]


@pytest.mark.ac("SPEC-083026-2601/AC-1")
def test_history_inspection_refreshes_before_http_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import dag_run_inspection

    class Store:
        refreshed = False

        def reload(self) -> None:
            self.refreshed = True

    store = Store()
    monkeypatch.setattr(dag_run_inspection, "get_dag_run_store", lambda: store)

    assert dag_run_inspection._fresh_store() is store
    assert store.refreshed is True


@pytest.mark.ac("SPEC-083026-2642/AC-8")
def test_completion_projection_carries_all_canonical_ids() -> None:
    from services import node_metrics_store

    class GraphNode:
        node_id = "node-1"
        node_type = "llm"

    class Graph:
        graph_id = "dag-1"
        nodes = (GraphNode(),)

    class Snapshot:
        @staticmethod
        def materialize() -> Graph:
            return Graph()

    class Run:
        run_id = "run-1"
        workspace_id = "workspace-1"
        project_id = "project-1"
        graph = Snapshot()

    class NodeRun:
        node_run_id = "node-run-1"
        node_id = "node-1"
        status = "completed"
        started_at = datetime.now(UTC)
        finished_at = started_at
        result: ClassVar[dict[str, str]] = {"model": "measured-model"}

    class Attempt:
        attempt_id = "attempt-1"
        node_run_id = "node-run-1"
        ordinal = 1

    class Record:
        run = Run()
        node_runs = (NodeRun(),)
        attempts = (Attempt(),)

    rows: dict[str, str] = {}
    store = NodeMetricsStore(records=SharedRecords(rows))
    previous = node_metrics_store.get_store()
    node_metrics_store.set_store(store)
    try:
        assert node_metrics_store.record_run_completion(Record()) == 1
    finally:
        node_metrics_store.set_store(previous)

    (found,) = store.observations(window_seconds=3600)
    assert (found.run_id, found.node_run_id, found.attempt_id) == (
        "run-1",
        "node-run-1",
        "attempt-1",
    )
    assert found.workspace_id == "workspace-1"


@pytest.mark.ac("SPEC-083026-2642/AC-9")
def test_metrics_retention_evicts_the_oldest_durable_row() -> None:
    rows: dict[str, str] = {}
    store = NodeMetricsStore(max_observations=1, records=SharedRecords(rows))
    store.append(_observation(attempt_id="attempt-old"))
    store.append(_observation(attempt_id="attempt-new"))

    assert list(rows) == ["attempt-new"]
    assert [item.attempt_id for item in store.observations(window_seconds=3600)] == ["attempt-new"]


@pytest.mark.ac("SPEC-083026-2642/AC-10")
def test_workspace_scoped_reads_are_fail_closed() -> None:
    """The HTTP seam scopes reads to a caller's Workspace universe (#1174).

    `workspace_ids` is the only door the routes pass: a member observation is
    served, a foreign one is not, and an observation that names no Workspace
    is served to nobody. `None` stays the in-process seam the optimizer reads
    through, and it is not reachable from a route.
    """
    store = NodeMetricsStore()
    store.append(_observation(attempt_id="a-mine", workspace_id="ws-mine"))
    store.append(_observation(attempt_id="a-theirs", workspace_id="ws-theirs"))
    store.append(_observation(attempt_id="a-legacy", workspace_id=""))

    mine = store.observations(window_seconds=3600, workspace_ids=frozenset({"ws-mine"}))
    assert [item.attempt_id for item in mine] == ["a-mine"]
    assert (
        store.aggregate(window_seconds=3600, workspace_ids=frozenset({"ws-theirs"}))["count"] == 1
    )
    # No Workspace at all: nothing is in scope, not even the caller's own rows.
    assert store.observations(window_seconds=3600, workspace_ids=frozenset()) == []
    # The in-process seam is unchanged for server-side collectors.
    assert store.aggregate(window_seconds=3600)["count"] == 3


@pytest.mark.ac("SPEC-083026-2642/AC-6")
def test_the_projection_store_is_registered_not_declared_in_stores_py() -> None:
    """The durable store is owned here and adopted by the central wiring.

    Declaring it in `stores.py` would add it to the cutover retirement
    ledger's census (#1046), where a retiring surface may not gain consumers,
    so a store added there is born unable to name a reader. Ownership stays
    with the only code that writes it, while `stores.register_json_store`
    keeps the deployment's persistence wiring and initialization centralized
    — the same seam `services.home_layouts` and `services.home_projections`
    use. A store that missed the wiring would silently stop surviving a
    restart.
    """
    import stores
    from services import node_metrics_store

    assert node_metrics_store.node_metrics in stores._all_json_stores
    assert not hasattr(stores, "node_metrics")


# --- store mechanics the durability contract leans on ---------------------


def test_a_non_positive_bound_is_refused_at_construction() -> None:
    """A bound of zero would silently evict every row as it is written; the
    store refuses the configuration instead of wearing it."""
    with pytest.raises(ValueError, match="max_observations must be positive"):
        NodeMetricsStore(max_observations=0)


def test_a_records_store_without_initialize_still_refreshes() -> None:
    """Any mapping is a legal records store. One without the `initialize`
    seam degenerates to a plain load on every refresh — the durable contract
    may not require a richer protocol than the deployment provides."""
    rows: dict[str, Any] = {}
    writer = NodeMetricsStore(records=rows)
    writer.append(_observation())

    assert len(writer) == 1
    assert set(rows) == {"attempt-1"}
    # A reader over the same plain mapping loads it on construction.
    assert len(NodeMetricsStore(records=rows)) == 1


def test_a_record_that_already_carries_a_datetime_loads() -> None:
    """Records are not required to round-trip through JSON: a records store
    whose values keep the native timestamp loads them as-is, and one whose
    values carry the ISO string parses it. Both door load the same row."""
    from dataclasses import asdict

    observation = _observation()
    native = asdict(observation)  # recorded_at stays a datetime
    encoded = SharedRecords({})
    encoded["attempt-1"] = NodeMetricsStore._to_record(observation)  # ISO string

    from_native = NodeMetricsStore(records={"attempt-1": native})
    from_string = NodeMetricsStore(records=encoded)

    (a,) = from_native.observations(window_seconds=3600)
    (b,) = from_string.observations(window_seconds=3600)
    assert a.attempt_id == b.attempt_id == "attempt-1"
    assert a.recorded_at == b.recorded_at == observation.recorded_at


def test_load_time_retention_trims_the_records_to_the_bound() -> None:
    """A store over pre-existing rows keeps the newest within its bound and
    drops the evicted keys from the records themselves — a bound enforced
    only in memory would let the durable rows grow without it."""
    rows: dict[str, str] = {}
    shared = SharedRecords(rows)
    for attempt in ("attempt-1", "attempt-2", "attempt-3"):
        shared[attempt] = NodeMetricsStore._to_record(_observation(attempt_id=attempt))

    store = NodeMetricsStore(max_observations=2, records=shared)

    assert set(rows) == {"attempt-2", "attempt-3"}
    # Buffer order is ascending by recorded_at, after a load just as after
    # an append (test_list_observations_returns_newest_first pins append
    # order; this pins that a reload does not scramble it).
    assert [item.attempt_id for item in store.observations(window_seconds=3600)] == [
        "attempt-2",
        "attempt-3",
    ]


def test_clear_empties_the_durable_records_too() -> None:
    """Clear on a durable store drops the records' rows, not just the buffer:
    a cleared store that reloaded its own records would resurrect what it
    was asked to forget."""
    rows: dict[str, str] = {}
    store = NodeMetricsStore(records=SharedRecords(rows))
    store.append(_observation())
    assert len(store) == 1 and rows

    store.clear()

    assert len(store) == 0
    assert rows == {}
    # And the emptiness survives a restart: nothing is left to reload.
    assert len(NodeMetricsStore(records=SharedRecords(rows))) == 0
