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


@pytest.mark.ac("M1-E/metrics-restart-and-replica")
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


@pytest.mark.ac("M1-E/metrics-idempotent-correlation")
def test_canonical_attempt_is_the_idempotency_key() -> None:
    rows: dict[str, str] = {}
    store = NodeMetricsStore(records=SharedRecords(rows))
    store.append(_observation(latency_ms=10))
    store.append(_observation(latency_ms=11))

    assert len(store) == 1
    assert store.observations(window_seconds=3600)[0].latency_ms == 11
    assert list(rows) == ["attempt-1"]


@pytest.mark.ac("M1-E/history-replica-refresh")
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


@pytest.mark.ac("M1-E/metrics-canonical-correlation")
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


@pytest.mark.ac("M1-E/metrics-retention")
def test_metrics_retention_evicts_the_oldest_durable_row() -> None:
    rows: dict[str, str] = {}
    store = NodeMetricsStore(max_observations=1, records=SharedRecords(rows))
    store.append(_observation(attempt_id="attempt-old"))
    store.append(_observation(attempt_id="attempt-new"))

    assert list(rows) == ["attempt-new"]
    assert [item.attempt_id for item in store.observations(window_seconds=3600)] == ["attempt-new"]


@pytest.mark.ac("M1-E/metrics-scope-authorization")
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


@pytest.mark.ac("M1-E/metrics-restart-and-replica")
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
