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
    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_the_defaults_are_absent_not_zero(self) -> None:
        """The four fields the route used to invent all default to nothing."""
        obs = _obs()

        assert (obs.latency_ms, obs.tokens_in, obs.tokens_out, obs.cost_usd) == (
            None,
            None,
            None,
            None,
        )

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
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

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_a_measured_cost_is_reported(self) -> None:
        """The control: absence must not swallow the values that exist."""
        store = NodeMetricsStore()
        store.append(_obs(cost_usd=0.25))

        agg = store.aggregate(window_seconds=3600)

        assert (agg["cost_measured"], agg["cost_usd_total"]) == (1, 0.25)

    @pytest.mark.ac("SPEC-083026-2642/AC-2")
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

    @pytest.mark.ac("SPEC-083026-2642/AC-2")
    def test_percentiles_ignore_the_unmeasured(self) -> None:
        """An untimed node used to enter the percentiles as the fastest one."""
        store = NodeMetricsStore()
        for ms in (10, 20, 30):
            store.append(_obs(node_id=f"n{ms}", latency_ms=ms))
        store.append(_obs(node_id="untimed"))

        assert store.aggregate(window_seconds=3600)["latency_ms_p50"] == 20


class TestTheIngestHasAProductionCaller:
    """`record_run_completion` read canonical NodeRuns and nothing called it."""

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
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

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
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

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    def test_a_node_run_with_no_timestamps_has_no_latency(self) -> None:
        """`None`, not `0`. Zero would be the fastest node in the window."""
        from services.node_metrics_store import _latency_ms

        assert _latency_ms(object()) is None


class TestTheReadersUseThePublicSurface:
    """Two production readers reached for `_filter` and `_aggregate`."""

    @pytest.mark.ac("SPEC-083026-2642/AC-4")
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

    @pytest.mark.ac("SPEC-083026-2642/AC-4")
    def test_the_public_surface_answers_the_same_question(self) -> None:
        """`observations` and `summarize` are what the readers moved onto."""
        store = NodeMetricsStore()
        store.append(_obs(latency_ms=40))

        found = store.observations(dag_id="d1", window_seconds=3600)

        assert [o.node_id for o in found] == ["n1"]
        assert store.summarize(found)["latency_ms_p50"] == 40


class TestTheProcessStoreIsInstalledPerStart:
    @pytest.mark.ac("SPEC-083026-2642/AC-5")
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

    @pytest.mark.ac("SPEC-083026-2642/AC-5")
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


class TestAnUnmeasuredLatencyIsNotTheFastest:
    """The review's P1, and the same defect as the rest of #698 one layer up.

    `topology_compare` normalizes p95 with `invert=True`. A bucket that
    reported `0` because nobody timed it therefore scored 1.0 on speed and
    outranked every bucket with real numbers — so the change that stopped
    fabricating per-node latency made the *comparison* worse until the readers
    of that absence were fixed too (Codex, #698).
    """

    @pytest.mark.ac("SPEC-083026-2642/AC-2")
    def test_a_percentile_over_nothing_is_absent(self) -> None:
        from services.node_metrics_store import _percentile

        assert _percentile([], 50) is None
        assert _percentile([7], 95) == 7

    @pytest.mark.ac("SPEC-083026-2642/AC-2")
    def test_a_window_with_no_timed_node_reports_no_percentiles(self) -> None:
        from services.node_metrics_store import NodeMetricsStore, NodeObservation

        store = NodeMetricsStore()
        store.append(
            NodeObservation(
                run_id="r",
                node_id="n",
                node_kind="llm",
                project_id="",
                dag_id="d",
                phase="COMPLETED",
            )
        )
        agg = store.aggregate(window_seconds=3600)
        assert agg["count"] == 1
        assert agg["latency_ms_measured"] == 0
        assert agg["latency_ms_p50"] is None
        assert agg["latency_ms_p95"] is None
        assert agg["latency_ms_p99"] is None

    @pytest.mark.ac("SPEC-083026-2642/AC-2")
    def test_an_untimed_bucket_has_no_p95(self) -> None:
        from services.node_metrics_store import NodeObservation
        from services.topology_compare import VariantBucket

        bucket = VariantBucket(label="x")
        bucket.observations.append(
            NodeObservation(
                run_id="r",
                node_id="n",
                node_kind="llm",
                project_id="",
                dag_id="d",
                phase="COMPLETED",
            )
        )
        assert bucket.p95_latency is None

    @pytest.mark.ac("SPEC-083026-2642/AC-2")
    def test_an_untimed_variant_does_not_outrank_a_timed_one_on_speed(self) -> None:
        """The midpoint, not the best score. An unmeasured bucket cannot be
        compared on speed; 1.0 says it was fastest and 0.0 says it was slowest,
        and both are claims the data does not support."""
        from services.topology_compare import _normalize_measured

        scores = _normalize_measured([100.0, 900.0, None], invert=True)
        assert scores[0] == 1.0, "the fastest measured bucket still scores best"
        assert scores[1] == 0.0
        assert scores[2] == 0.5, "the unmeasured one is neither rewarded nor penalized"

    @pytest.mark.ac("SPEC-083026-2642/AC-2")
    def test_when_nothing_is_measured_the_latency_term_stops_deciding(self) -> None:
        from services.topology_compare import _normalize_measured

        assert _normalize_measured([None, None], invert=True) == [0.5, 0.5]


class TestTheModelANodeRanOnIsAMeasurement:
    """Also the review's P1, and the opposite error to the rest of #698.

    The old route took the *first* node's model behind a hardcoded fallback and
    stamped it on every node, which was a fabrication. Dropping it entirely was
    the overcorrection: `graph_runner` resolves each node's own model and passes
    it to the call, so that value is measured. Without it `topology_compare`,
    whose default grouping is `model_used`, puts every new observation in one
    `(unset)` bucket and can no longer compare model variants at all.
    """

    @staticmethod
    def _runner_source() -> str:
        return (_BACKEND / "services/graph_runner.py").read_text()

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_every_llm_result_carries_the_model_it_called(self) -> None:
        """Both outcomes: which model a node *failed* on is exactly what a
        comparison of model variants needs."""
        source = self._runner_source()
        body = source[source.index("async def _run_llm_node") :]
        body = body[: body.index("def _invoke_subprocess_usage_hooks")]
        assignments = [line for line in body.splitlines() if "results[nid] = {" in line]
        assert len(assignments) == 2, assignments
        for line in assignments:
            assert '"model": model' in line

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_the_subprocess_path_reports_the_model_it_set(self) -> None:
        source = self._runner_source()
        body = source[source.index("def _run_node_subprocess") :]
        body = body[: body.index("async def _tool_web_search")]
        assert '"DAG_NODE_MODEL": model' in body, "the env var and the report are one value"
        assert body.count('"model": model') == 3, "success, failure and exception all report it"

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_the_route_records_the_model_the_runner_reported(self) -> None:
        """From the runner's own result, not re-resolved: a second copy of
        `node.get("model", ...) or CHAT_DEFAULT_MODEL or ...` in the route is
        two places to drift."""
        source = (_BACKEND / "routes/dags.py").read_text()
        call = source[source.index("NodeObservation(") : source.index("except Exception:")]
        assert 'model_used=str(nr.get("model", ""))' in call

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_a_node_that_ran_no_model_reports_none(self) -> None:
        """A tool node makes no LLM call, so it has no model, and `""` is the
        honest answer rather than the DAG's default."""
        assert str({"role": "worker", "success": True}.get("model", "")) == ""


class TestOnlyATerminalRunIsIngested:
    """The review's P2. `run_durable_graph` returns as soon as the graph stops
    advancing, and a wait or HITL node stops it in `waiting` or `paused`. Those
    NodeRuns are a partial picture: the paused one lands in the aggregate's
    denominator and everything after it is missing, and no resume path calls
    back to correct it.
    """

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    @pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "timed_out"])
    def test_a_finished_run_is_ingested(self, status: str) -> None:
        from services.dag_agents import _is_terminal

        assert _is_terminal(_record_with_status(status)) is True

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    @pytest.mark.parametrize("status", ["created", "queued", "running", "waiting", "paused"])
    def test_a_run_still_going_is_not(self, status: str) -> None:
        from services.dag_agents import _is_terminal

        assert _is_terminal(_record_with_status(status)) is False

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    def test_a_status_this_build_does_not_know_is_ingested(self) -> None:
        """Spelled as the complement of terminal on purpose: an unrecognised
        status is likelier a new terminal state than a new suspended one, and
        reading it as suspended would silently stop recording — the shape of
        defect this whole change removes."""
        from services.dag_agents import _is_terminal

        assert _is_terminal(_record_with_status("superseded")) is True
        assert _is_terminal(_record_with_status("")) is True

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    def test_a_status_carried_as_an_enum_reads_the_same_as_a_string(self) -> None:
        from services.dag_agents import _is_terminal

        from maistro.runs.model import RunStatus

        assert _is_terminal(_record_with_status(RunStatus.PAUSED)) is False
        assert _is_terminal(_record_with_status(RunStatus.COMPLETED)) is True


def _record_with_status(status: Any) -> Any:
    class _Run:
        pass

    class _Record:
        pass

    run = _Run()
    run.status = status  # type: ignore[attr-defined]
    record = _Record()
    record.run = run  # type: ignore[attr-defined]
    return record


_SYNTH_DAG = {
    "id": "synth-metrics",
    "name": "Synth Metrics",
    "description": "single alias node, for driving the canonical run path",
    "entry_node": "only",
    "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
    "edges": [],
}


@pytest.fixture()
def synth_dag_id():
    from services.dag_agents import get_registry

    registry = get_registry()
    registry.register(dict(_SYNTH_DAG))
    try:
        yield "synth-metrics"
    finally:
        registry.deregister("synth-metrics")


class TestTheIngestDecisionDrivenThroughTheRealPath:
    """The classes above assert on `_is_terminal` and on source shape; these
    run `run_registered_dag` itself, which is where the decision is actually
    taken and where its two consequences (a warning, a deferral) live.
    """

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    async def test_a_finished_run_reaches_the_ingest(self, synth_dag_id: str) -> None:
        import services.node_metrics_store as metrics_module
        from services.dag_agents import run_registered_dag

        seen: list[Any] = []
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(metrics_module, "record_run_completion", lambda r: seen.append(r) or 1)
            patch.setattr(
                "services.dag_agents.record_run_completion", lambda r: seen.append(r) or 1
            )
            await run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1")
        assert len(seen) == 1

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    async def test_a_failing_ingest_does_not_fail_the_run(
        self, synth_dag_id: str, caplog: Any
    ) -> None:
        """Named rather than bare: a metrics write must not fail a run that
        already produced a result, but an operator has to be able to find out
        that the observations were dropped."""
        import logging

        from services.dag_agents import run_registered_dag

        def _boom(record: Any) -> int:
            raise RuntimeError("the metrics buffer is gone")

        with pytest.MonkeyPatch.context() as patch, caplog.at_level(logging.WARNING):
            patch.setattr("services.dag_agents.record_run_completion", _boom)
            _graph, record = await run_registered_dag(
                synth_dag_id, workspace_id="w1", project_id="p1"
            )
        assert record is not None, "the run still returns its record"
        assert "node_metrics_not_recorded" in caplog.text

    @pytest.mark.ac("SPEC-083026-2642/AC-3")
    async def test_a_run_that_stopped_at_a_pause_is_deferred_not_ingested(
        self, synth_dag_id: str, caplog: Any
    ) -> None:
        """`run_durable_graph` returns as soon as the graph stops advancing, so
        a wait or HITL node hands back a record that is not a finished run."""
        import logging

        import services.dag_agents as dag_agents

        real = dag_agents.run_durable_graph
        seen: list[Any] = []

        async def _paused(*a: Any, **k: Any) -> Any:
            record = await real(*a, **k)
            record.run.status = "paused"
            return record

        with pytest.MonkeyPatch.context() as patch, caplog.at_level(logging.INFO):
            patch.setattr(dag_agents, "run_durable_graph", _paused)
            patch.setattr(dag_agents, "record_run_completion", lambda r: seen.append(r) or 1)
            await dag_agents.run_registered_dag(synth_dag_id, workspace_id="w1", project_id="p1")
        assert seen == [], "a partial record must not enter the aggregate"
        assert "node_metrics_deferred" in caplog.text


class TestTheSubprocessNodeReportsItsModelOnEveryOutcome:
    """Line-level cover for the failure return, which the source assertion
    above counts but does not execute."""

    @staticmethod
    def _node() -> dict[str, Any]:
        return {"id": "n1", "role": "worker", "model": "gemma-27b", "prompt": "hi"}

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_a_failed_subprocess_node_still_names_its_model(self) -> None:
        import services.hyperlight_executor as executor_module
        from services.graph_runner import _run_node_subprocess

        class _Executor:
            @staticmethod
            async def execute_node(*a: Any, **k: Any) -> dict[str, Any]:
                return {"success": False, "error": "the sandbox refused", "isolation": "bwrap"}

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(executor_module, "get_executor", lambda: _Executor())
            result = _run_node_subprocess(self._node(), "task", "", {}, "interactive")
        assert result["success"] is False
        assert result["model"] == "gemma-27b"
        assert result["isolation"] == "bwrap"

    @pytest.mark.ac("SPEC-083026-2642/AC-1")
    def test_a_subprocess_node_that_raised_still_names_its_model(self) -> None:
        import services.hyperlight_executor as executor_module
        from services.graph_runner import _run_node_subprocess

        def _boom() -> Any:
            raise RuntimeError("no executor here")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(executor_module, "get_executor", _boom)
            result = _run_node_subprocess(self._node(), "task", "", {}, "interactive")
        assert result["success"] is False
        assert result["model"] == "gemma-27b"
