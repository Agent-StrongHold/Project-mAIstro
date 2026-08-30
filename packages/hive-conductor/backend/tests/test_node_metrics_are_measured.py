"""An unmeasured metric is absent, and the ingest has a caller (#698).

`node_metrics_store` called itself durable in three docstrings while writing
to a `deque`, and `record_run_completion` — which reads real NodeRuns and the
Run's own graph snapshot — had no production caller at all. The only
observations the optimizer ever saw came from `routes/dags.py`, which built
them by hand with `cost_usd=0.0`, zero tokens, a hardcoded model name and the
whole-DAG elapsed time divided by the cycle count.

The optimizer weights cost at 0.15 and latency at 0.25. Fed zeroes, it scored
every variant as free and every node as equally fast — a number nobody
measured, ranked against numbers somebody did.
"""

from __future__ import annotations

import ast
import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.node_metrics_store import (  # noqa: E402
    NodeMetricsStore,
    NodeObservation,
)

pytestmark = [pytest.mark.contract("behavioral")]


def _obs(**overrides: Any) -> NodeObservation:
    base: dict[str, Any] = {
        "run_id": "r1",
        "node_id": "n1",
        "node_kind": "llm",
        "project_id": "p1",
        "dag_id": "d1",
        "phase": "COMPLETED",
    }
    base.update(overrides)
    return NodeObservation(**base)


class TestAnUnmeasuredMetricIsAbsent:
    @pytest.mark.ac("SPEC-083026-7a4e/AC-1")
    def test_the_defaults_are_absent_not_zero(self) -> None:
        """The four fields the route used to invent all default to nothing."""
        obs = _obs()

        assert (obs.latency_ms, obs.tokens_in, obs.tokens_out, obs.cost_usd) == (
            None,
            None,
            None,
            None,
        )

    @pytest.mark.ac("SPEC-083026-7a4e/AC-1")
    def test_an_unmeasured_cost_is_not_a_zero_cost(self) -> None:
        """The finding in one assertion.

        A window holding only unmeasured observations must report that it
        measured no cost, not that the cost was nothing — those rank
        differently against a variant whose cost *was* measured.
        """
        store = NodeMetricsStore()
        store.append(_obs())
        store.append(_obs(node_id="n2"))

        agg = store.aggregate(window_seconds=3600)

        assert agg["count"] == 2
        assert agg["cost_measured"] == 0
        assert agg["cost_usd_total"] is None

    @pytest.mark.ac("SPEC-083026-7a4e/AC-1")
    def test_a_measured_cost_is_reported(self) -> None:
        """The control: absence must not swallow the values that exist."""
        store = NodeMetricsStore()
        store.append(_obs(cost_usd=0.25))

        agg = store.aggregate(window_seconds=3600)

        assert (agg["cost_measured"], agg["cost_usd_total"]) == (1, 0.25)

    @pytest.mark.ac("SPEC-083026-7a4e/AC-2")
    def test_a_mean_divides_by_what_was_measured(self) -> None:
        """One node at 100ms beside one unmeasured is a 100ms mean, not 50ms.

        Dividing by the observation count folded every absent value in as a
        zero, which halved the mean for each node nobody timed.
        """
        store = NodeMetricsStore()
        store.append(_obs(latency_ms=100))
        store.append(_obs(node_id="n2"))

        agg = store.aggregate(window_seconds=3600)

        assert agg["latency_ms_measured"] == 1
        assert agg["latency_ms_mean"] == 100.0

    @pytest.mark.ac("SPEC-083026-7a4e/AC-2")
    def test_percentiles_ignore_the_unmeasured(self) -> None:
        """An untimed node used to enter the percentiles as the fastest one."""
        store = NodeMetricsStore()
        for ms in (10, 20, 30):
            store.append(_obs(node_id=f"n{ms}", latency_ms=ms))
        store.append(_obs(node_id="untimed"))

        assert store.aggregate(window_seconds=3600)["latency_ms_p50"] == 20


class TestTheIngestHasAProductionCaller:
    """`record_run_completion` read canonical NodeRuns and nothing called it."""

    @pytest.mark.ac("SPEC-083026-7a4e/AC-3")
    def test_the_canonical_path_records_the_run(self) -> None:
        """Asserted on the source: reaching the call needs a live container.

        `run_registered_dag` builds a Graph, admits a Run and executes it. What
        this pins is that the finished record reaches the metrics ingest at
        all, which is what had no path into it.
        """
        from services import dag_agents

        source = pathlib.Path(dag_agents.__file__).read_text(encoding="utf-8")
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "record_run_completion"
        ]

        assert calls, "the canonical run path no longer records node metrics"

    @pytest.mark.ac("SPEC-083026-7a4e/AC-3")
    def test_an_unmeasured_ingest_leaves_the_fields_absent(self) -> None:
        """The ingest itself: real latency, absent tokens and cost."""
        from services.node_metrics_store import record_run_completion, set_store

        store = NodeMetricsStore()
        previous = _current_store()
        set_store(store)
        try:
            assert record_run_completion(_FakeRecord()) == 1
        finally:
            set_store(previous)

        (obs,) = store.observations(window_seconds=3600)
        assert obs.latency_ms == 1500
        assert (obs.tokens_in, obs.tokens_out, obs.cost_usd) == (None, None, None)

    @pytest.mark.ac("SPEC-083026-7a4e/AC-3")
    def test_a_node_run_with_no_timestamps_has_no_latency(self) -> None:
        """`None`, not `0`. Zero would be the fastest node in the window."""
        from services.node_metrics_store import _latency_ms

        assert _latency_ms(object()) is None


class TestTheReadersUseThePublicSurface:
    """Two production readers reached for `_filter` and `_aggregate`."""

    @pytest.mark.ac("SPEC-083026-7a4e/AC-4")
    @pytest.mark.parametrize("module", ["optimizer", "topology_compare"])
    def test_no_reader_touches_a_private_helper(self, module: str) -> None:
        source = (_BACKEND / "services" / f"{module}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        private = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in {"_filter", "_aggregate"}
        }
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("node_metrics_store")
            for alias in node.names
            if alias.name.startswith("_")
        }

        assert private == set(), f"{module} reaches into the metrics store"
        assert imported == set(), f"{module} imports a private metrics helper"

    @pytest.mark.ac("SPEC-083026-7a4e/AC-4")
    def test_the_public_surface_answers_the_same_question(self) -> None:
        """`observations` and `summarize` are what the readers moved onto."""
        store = NodeMetricsStore()
        store.append(_obs(latency_ms=40))

        found = store.observations(dag_id="d1", window_seconds=3600)

        assert [o.node_id for o in found] == ["n1"]
        assert store.summarize(found)["latency_ms_p50"] == 40


class TestTheProcessStoreIsInstalledPerStart:
    @pytest.mark.ac("SPEC-083026-7a4e/AC-5")
    def test_reset_store_installs_a_fresh_buffer(self) -> None:
        """`set_store` had no production caller; a carried buffer mixes windows."""
        from services.node_metrics_store import get_store, reset_store, set_store

        previous = get_store()
        stale = NodeMetricsStore()
        stale.append(_obs())
        set_store(stale)
        try:
            fresh = reset_store()

            assert fresh is get_store()
            assert len(fresh) == 0
        finally:
            set_store(previous)

    @pytest.mark.ac("SPEC-083026-7a4e/AC-5")
    def test_the_engine_installs_one_at_start(self) -> None:
        from services import engine as engine_module

        source = pathlib.Path(engine_module.__file__).read_text(encoding="utf-8")

        assert "reset_store()" in source


def _current_store() -> NodeMetricsStore:
    from services.node_metrics_store import get_store

    return get_store()


class _FakeNodeRun:
    node_id = "n1"
    status = "completed"

    def __init__(self) -> None:
        from datetime import UTC, datetime, timedelta

        self.started_at = datetime.now(UTC)
        self.finished_at = self.started_at + timedelta(milliseconds=1500)


class _FakeGraphNode:
    node_id = "n1"
    node_type = "llm"


class _FakeGraph:
    graph_id = "d1"
    nodes = (_FakeGraphNode(),)


class _FakeSnapshot:
    @staticmethod
    def materialize() -> _FakeGraph:
        return _FakeGraph()


class _FakeRun:
    run_id = "run-1"
    project_id = "p1"
    graph = _FakeSnapshot()


class _FakeRecord:
    run = _FakeRun()
    node_runs = (_FakeNodeRun(),)
