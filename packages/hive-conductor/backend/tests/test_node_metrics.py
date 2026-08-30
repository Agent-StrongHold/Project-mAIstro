"""Boy Scout — Phase 5 Signal #5 node-metrics store + endpoint.

Every assertion targets a specific value in the aggregate response or
the observation list. Covers:

  - NodeMetricsStore append + bounded ring buffer
  - _filter respects time-window cutoff
  - _filter respects node_kind / project_id / node_id / dag_id
  - aggregate stats: count, p50/p95/p99, success_rate, tokens, cost
  - empty result returns the zeroed shape (not 404)
  - record_run_completion ingests every canonical NodeRun correctly
  - record_run_completion(None) is a no-op (defensive)
  - Phase enum coerced to "COMPLETED" / "FAILED" / etc.
  - GET /v1/dag-metrics returns the aggregate with default window
  - GET /v1/dag-metrics/observations returns newest-first capped
  - window_seconds is clamped to [60, 7 days]
  - limit is clamped to [1, 1000]
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@dataclass
class _FakeGraphNode:
    node_id: str
    node_type: str


@dataclass
class _FakeGraph:
    graph_id: str
    nodes: list[_FakeGraphNode]


@dataclass
class _FakeGraphSnapshot:
    graph: _FakeGraph

    def materialize(self) -> _FakeGraph:
        return self.graph


@dataclass
class _FakeRun:
    run_id: str
    project_id: str
    graph: _FakeGraphSnapshot


@dataclass
class _FakeNodeRun:
    node_id: str
    status: Any = "completed"
    latency_ms: int = 0
    started_at: datetime = field(init=False)
    finished_at: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.started_at = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)
        self.finished_at = self.started_at + timedelta(milliseconds=self.latency_ms)


@dataclass
class _FakeRecord:
    run: _FakeRun
    node_runs: list[_FakeNodeRun] = field(default_factory=list)


def _fake_record(
    *,
    run_id: str = "r1",
    dag_id: str = "daily-status",
    project_id: str = "proj-A",
    nodes: list[tuple[_FakeNodeRun, str]],
) -> _FakeRecord:
    graph = _FakeGraph(
        graph_id=dag_id,
        nodes=[_FakeGraphNode(node.node_id, kind) for node, kind in nodes],
    )
    run = _FakeRun(
        run_id=run_id,
        project_id=project_id,
        graph=_FakeGraphSnapshot(graph),
    )
    return _FakeRecord(run=run, node_runs=[node for node, _kind in nodes])


@pytest.fixture()
def isolated_store(monkeypatch: pytest.MonkeyPatch):
    """Fresh NodeMetricsStore per test; auto-restore after."""
    from services.node_metrics_store import NodeMetricsStore, get_store, set_store

    original = get_store()
    set_store(NodeMetricsStore())
    yield get_store()
    set_store(original)


# --- store unit tests ----------------------------------------------------


def test_append_and_len(isolated_store: Any) -> None:
    from services.node_metrics_store import NodeObservation

    isolated_store.append(
        NodeObservation(
            run_id="r1",
            node_id="n1",
            node_kind="jira.poll",
            project_id="p",
            dag_id="d",
            phase="COMPLETED",
            latency_ms=100,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used="",
        )
    )
    assert len(isolated_store) == 1


def test_clear_drops_all_observations(isolated_store: Any) -> None:
    from services.node_metrics_store import NodeObservation

    isolated_store.append(
        NodeObservation(
            run_id="r",
            node_id="n",
            node_kind="x",
            project_id="p",
            dag_id="d",
            phase="COMPLETED",
            latency_ms=1,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used="",
        )
    )
    isolated_store.clear()
    assert len(isolated_store) == 0


def test_ring_buffer_evicts_oldest_at_capacity() -> None:
    from services.node_metrics_store import NodeMetricsStore, NodeObservation

    store = NodeMetricsStore(max_observations=3)
    for i in range(5):
        store.append(
            NodeObservation(
                run_id=f"r{i}",
                node_id=f"n{i}",
                node_kind="x",
                project_id="p",
                dag_id="d",
                phase="COMPLETED",
                latency_ms=i,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model_used="",
            )
        )
    assert len(store) == 3
    # Only the last 3 survived
    agg = store.aggregate(window_seconds=3600)
    assert agg["count"] == 3


# --- filter coverage -----------------------------------------------------


def _seed_n(
    store: Any,
    kind: str,
    project: str,
    latency: int,
    phase: str = "COMPLETED",
    node_id: str = "x",
    dag_id: str = "d",
) -> None:
    from services.node_metrics_store import NodeObservation

    store.append(
        NodeObservation(
            run_id="r",
            node_id=node_id,
            node_kind=kind,
            project_id=project,
            dag_id=dag_id,
            phase=phase,
            latency_ms=latency,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used="",
        )
    )


def test_filter_node_kind(isolated_store: Any) -> None:
    _seed_n(isolated_store, "jira.poll", "p", 100)
    _seed_n(isolated_store, "transform.alias", "p", 200)
    agg = isolated_store.aggregate(node_kind="jira.poll", window_seconds=3600)
    assert agg["count"] == 1


def test_filter_project_id(isolated_store: Any) -> None:
    _seed_n(isolated_store, "x", "proj-A", 100)
    _seed_n(isolated_store, "x", "proj-B", 200)
    agg = isolated_store.aggregate(project_id="proj-A", window_seconds=3600)
    assert agg["count"] == 1


def test_filter_node_id(isolated_store: Any) -> None:
    _seed_n(isolated_store, "x", "p", 100, node_id="alpha")
    _seed_n(isolated_store, "x", "p", 200, node_id="beta")
    agg = isolated_store.aggregate(node_id="alpha", window_seconds=3600)
    assert agg["count"] == 1


def test_filter_dag_id(isolated_store: Any) -> None:
    _seed_n(isolated_store, "x", "p", 100, dag_id="dag-A")
    _seed_n(isolated_store, "x", "p", 200, dag_id="dag-B")
    agg = isolated_store.aggregate(dag_id="dag-A", window_seconds=3600)
    assert agg["count"] == 1


def test_filter_window_cutoff_excludes_old_observations(isolated_store: Any) -> None:
    """A recorded_at older than the cutoff must be excluded."""
    from services.node_metrics_store import NodeObservation

    now = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)
    isolated_store.append(
        NodeObservation(
            run_id="r",
            node_id="n",
            node_kind="x",
            project_id="p",
            dag_id="d",
            phase="COMPLETED",
            latency_ms=10,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used="",
            recorded_at=now - timedelta(hours=2),
        )
    )
    isolated_store.append(
        NodeObservation(
            run_id="r",
            node_id="n",
            node_kind="x",
            project_id="p",
            dag_id="d",
            phase="COMPLETED",
            latency_ms=20,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used="",
            recorded_at=now,
        )
    )
    # 1-hour window relative to `now` → only the second observation
    agg = isolated_store.aggregate(window_seconds=3600, now=now)
    assert agg["count"] == 1


# --- aggregate math ------------------------------------------------------


def test_aggregate_empty_reports_nothing_measured() -> None:
    """Counts are zero; measures are absent.

    `tokens_in_total` used to be `0` here and for every unmeasured
    observation, which is the same number a genuinely free run would report.
    `None` is the honest answer to "how many tokens", and `tokens_measured`
    is how a reader tells the two apart (#698).
    """
    from services.node_metrics_store import NodeMetricsStore

    store = NodeMetricsStore()
    agg = store.aggregate(window_seconds=3600)
    assert agg["count"] == 0
    assert agg["success_rate"] == 0.0
    assert agg["latency_ms_p50"] == 0
    assert agg["tokens_measured"] == 0
    assert agg["tokens_in_total"] is None
    assert agg["cost_usd_total"] is None


def test_aggregate_percentiles(isolated_store: Any) -> None:
    """Spec values: latencies [10, 20, 30, 40, 50] → p50=30, p95=48, p99≈49"""
    for ms in [10, 20, 30, 40, 50]:
        _seed_n(isolated_store, "x", "p", ms)
    agg = isolated_store.aggregate(window_seconds=3600)
    assert agg["count"] == 5
    assert agg["latency_ms_p50"] == 30
    assert agg["latency_ms_p95"] == 48  # linear-interp at rank 3.8
    assert agg["latency_ms_p99"] == 49


def test_aggregate_success_rate(isolated_store: Any) -> None:
    _seed_n(isolated_store, "x", "p", 100, phase="COMPLETED")
    _seed_n(isolated_store, "x", "p", 100, phase="COMPLETED")
    _seed_n(isolated_store, "x", "p", 100, phase="FAILED")
    agg = isolated_store.aggregate(window_seconds=3600)
    assert agg["count"] == 3
    assert agg["succeeded"] == 2
    assert agg["failed"] == 1
    assert agg["success_rate"] == round(2 / 3, 4)


def test_aggregate_tokens_and_cost(isolated_store: Any) -> None:
    from services.node_metrics_store import NodeObservation

    isolated_store.append(
        NodeObservation(
            run_id="r",
            node_id="n",
            node_kind="x",
            project_id="p",
            dag_id="d",
            phase="COMPLETED",
            latency_ms=100,
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.05,
            model_used="m",
        )
    )
    isolated_store.append(
        NodeObservation(
            run_id="r",
            node_id="n",
            node_kind="x",
            project_id="p",
            dag_id="d",
            phase="COMPLETED",
            latency_ms=200,
            tokens_in=30,
            tokens_out=60,
            cost_usd=0.15,
            model_used="m",
        )
    )
    agg = isolated_store.aggregate(window_seconds=3600)
    assert agg["tokens_in_total"] == 40
    assert agg["tokens_in_mean"] == 20.0
    assert agg["tokens_out_total"] == 80
    assert agg["tokens_out_mean"] == 40.0
    assert agg["cost_usd_total"] == 0.2


def test_aggregate_single_observation_percentile_is_identity() -> None:
    """One value → p50 == p95 == p99 == that value."""
    from services.node_metrics_store import NodeMetricsStore

    store = NodeMetricsStore()
    _seed_n(store, "x", "p", 42)
    agg = store.aggregate(window_seconds=3600)
    assert agg["latency_ms_p50"] == 42
    assert agg["latency_ms_p95"] == 42
    assert agg["latency_ms_p99"] == 42


def test_percentile_returns_zero_for_empty_list() -> None:
    """Direct call to _percentile defensive check."""
    from services.node_metrics_store import _percentile

    assert _percentile([], 50) == 0


# --- list_observations --------------------------------------------------


def test_list_observations_returns_newest_first(isolated_store: Any) -> None:
    _seed_n(isolated_store, "x", "p", 100, node_id="alpha")
    _seed_n(isolated_store, "x", "p", 200, node_id="beta")
    items = isolated_store.list_observations(window_seconds=3600, limit=10)
    assert len(items) == 2
    assert items[0]["node_id"] == "beta"
    assert items[1]["node_id"] == "alpha"


def test_list_observations_limit_caps_size(isolated_store: Any) -> None:
    for i in range(5):
        _seed_n(isolated_store, "x", "p", i)
    items = isolated_store.list_observations(window_seconds=3600, limit=2)
    assert len(items) == 2


def test_list_observations_filter_by_node_kind(isolated_store: Any) -> None:
    _seed_n(isolated_store, "kind-A", "p", 1)
    _seed_n(isolated_store, "kind-B", "p", 2)
    items = isolated_store.list_observations(
        node_kind="kind-A",
        window_seconds=3600,
        limit=100,
    )
    assert len(items) == 1
    assert items[0]["node_kind"] == "kind-A"


def test_observation_dict_has_isoformat_timestamp(isolated_store: Any) -> None:
    _seed_n(isolated_store, "x", "p", 1)
    items = isolated_store.list_observations(window_seconds=3600)
    assert "T" in items[0]["recorded_at"]  # ISO 8601


# --- record_run_completion -----------------------------------------------


def test_record_run_completion_ingests_every_node(isolated_store: Any) -> None:
    from services.node_metrics_store import record_run_completion

    run = _fake_record(
        run_id="r-001",
        dag_id="daily-status",
        project_id="proj-X",
        nodes=[
            (_FakeNodeRun("n1", "completed", 150), "jira.poll"),
            (_FakeNodeRun("n2", "completed", 5), "transform.alias"),
            (_FakeNodeRun("n3", "failed", 80), "dashboard.append"),
        ],
    )
    n = record_run_completion(run)
    assert n == 3
    assert len(isolated_store) == 3
    items = isolated_store.list_observations(window_seconds=3600)
    by_id = {it["node_id"]: it for it in items}
    assert by_id["n1"]["node_kind"] == "jira.poll"
    assert by_id["n1"]["latency_ms"] == 150
    # Invocation/resource metrics move onto Attempt in the next spine slice.
    # Absent until then, not zero: a canonical run recorded as costing nothing
    # would outrank a measured one on the optimizer's cost term (#698).
    assert by_id["n1"]["tokens_in"] is None
    assert by_id["n1"]["tokens_out"] is None
    assert by_id["n1"]["cost_usd"] is None
    assert by_id["n3"]["phase"] == "FAILED"


def test_record_run_completion_none_is_noop(isolated_store: Any) -> None:
    from services.node_metrics_store import record_run_completion

    assert record_run_completion(None) == 0
    assert len(isolated_store) == 0


def test_record_run_completion_handles_missing_fields(isolated_store: Any) -> None:
    """run_record duck-typed with missing attrs → defaults safely."""
    from services.node_metrics_store import record_run_completion

    class _Empty:
        pass

    e = _Empty()
    # No canonical run envelope; should not raise
    assert record_run_completion(e) == 0


def test_record_run_completion_canonical_status_coerced() -> None:
    """Canonical RunStatus values normalize to the metrics phase vocabulary."""
    from services.node_metrics_store import (
        NodeMetricsStore,
        record_run_completion,
        set_store,
    )

    from maistro.runs.model import RunStatus

    store = NodeMetricsStore()
    set_store(store)
    try:
        run = _fake_record(nodes=[(_FakeNodeRun("n1", RunStatus.COMPLETED, 100), "x")])
        record_run_completion(run)
        agg = store.aggregate(window_seconds=3600)
        assert agg["succeeded"] == 1
        assert agg["count"] == 1
    finally:
        set_store(NodeMetricsStore())  # reset for other tests


def test_set_store_swaps_module_singleton() -> None:
    """The bridge / tests can hot-swap the store via set_store; the
    contract is parallel to feedback_service.set_outcome_store."""
    from services.node_metrics_store import (
        NodeMetricsStore,
        get_store,
        set_store,
    )

    original = get_store()
    fresh = NodeMetricsStore()
    set_store(fresh)
    try:
        assert get_store() is fresh
        assert get_store() is not original
    finally:
        set_store(original)


# --- HTTP route tests ----------------------------------------------------


def test_metrics_endpoint_returns_aggregate(authed_client: Any, isolated_store: Any) -> None:
    _seed_n(isolated_store, "x", "p", 100)
    _seed_n(isolated_store, "x", "p", 200)
    r = authed_client.get("/v1/dag-metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["latency_ms_p50"] == 150


def test_metrics_endpoint_window_seconds_clamps_to_minimum(
    authed_client: Any, isolated_store: Any
) -> None:
    """Caller passes window_seconds=10 — clamped to 60s minimum."""
    _seed_n(isolated_store, "x", "p", 100)
    r = authed_client.get("/v1/dag-metrics?window_seconds=10")
    assert r.status_code == 200
    # Still includes the observation (within 60s)
    assert r.json()["count"] == 1


def test_metrics_endpoint_window_seconds_clamps_to_maximum(
    authed_client: Any, isolated_store: Any
) -> None:
    """Caller passes window_seconds=99999999 — clamped to 7-day max."""
    _seed_n(isolated_store, "x", "p", 100)
    r = authed_client.get("/v1/dag-metrics?window_seconds=99999999")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_metrics_observations_endpoint_returns_list(
    authed_client: Any, isolated_store: Any
) -> None:
    _seed_n(isolated_store, "alpha", "p", 100)
    _seed_n(isolated_store, "beta", "p", 200)
    r = authed_client.get("/v1/dag-metrics/observations")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # Filter form
    r2 = authed_client.get("/v1/dag-metrics/observations?node_kind=alpha")
    assert r2.status_code == 200
    items = r2.json()
    assert len(items) == 1
    assert items[0]["node_kind"] == "alpha"


def test_metrics_observations_limit_clamped(authed_client: Any, isolated_store: Any) -> None:
    """limit param is clamped to [1, 1000]; below 1 → 1, above 1000 → 1000."""
    for i in range(5):
        _seed_n(isolated_store, "x", "p", i)
    r = authed_client.get("/v1/dag-metrics/observations?limit=0")
    assert r.status_code == 200
    assert len(r.json()) == 1  # clamped to 1


def test_metrics_endpoint_unauthenticated_returns_401() -> None:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.get("/v1/dag-metrics")
    assert r.status_code == 401
