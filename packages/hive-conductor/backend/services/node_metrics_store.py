"""Per-node latency and token metrics, aggregated over a ring buffer.

The buffer is in-memory and bounded, and this module says so rather than
calling itself durable: three docstrings here used to, while the destination
was a `deque` (#698). Making the observations themselves durable needs the
Conductor's UI run path to mint a canonical Run, which it does not — that is
#53.

**An unmeasured field is absent, not zero.** `tokens_in`, `tokens_out`,
`cost_usd` and `model_used` are optional, and the aggregate reports what it has
rather than averaging invented zeros in. The route that runs a DAG from the UI
used to hand-build an observation with `cost_usd=0.0`, zero tokens and a
hardcoded model name, so the optimizer -- which weights cost at 0.15 -- scored
every variant as free. A number nobody measured is worse than no number,
because only one of them is visibly missing.

Attempt-level tokens, model and cost are not part of the durable slice yet, so
`record_run_completion` leaves them absent too, for the same reason.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_MAX_OBSERVATIONS = 10_000


@dataclass(frozen=True)
class NodeObservation:
    """One per-node completion event, captured for metric aggregation."""

    run_id: str
    node_id: str
    node_kind: str
    project_id: str
    dag_id: str
    phase: str
    #: `None` where nothing measured it. Every one of these was a required
    #: field whose only non-durable writer supplied a zero or a guess.
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    model_used: str = ""
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class NodeMetricsStore:
    """In-memory ring buffer of node observations."""

    def __init__(self, *, max_observations: int = DEFAULT_MAX_OBSERVATIONS) -> None:
        self._buf: deque[NodeObservation] = deque(maxlen=max_observations)

    def append(self, obs: NodeObservation) -> None:
        self._buf.append(obs)

    def __len__(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        self._buf.clear()

    def _filter(
        self,
        *,
        node_kind: str = "",
        project_id: str = "",
        node_id: str = "",
        dag_id: str = "",
        window_seconds: int = 3600,
        now: datetime | None = None,
    ) -> list[NodeObservation]:
        cutoff = (now or datetime.now(UTC)) - timedelta(seconds=window_seconds)
        out: list[NodeObservation] = []
        for obs in self._buf:
            if obs.recorded_at < cutoff:
                continue
            if node_kind and obs.node_kind != node_kind:
                continue
            if project_id and obs.project_id != project_id:
                continue
            if node_id and obs.node_id != node_id:
                continue
            if dag_id and obs.dag_id != dag_id:
                continue
            out.append(obs)
        return out

    def aggregate(
        self,
        *,
        node_kind: str = "",
        project_id: str = "",
        node_id: str = "",
        dag_id: str = "",
        window_seconds: int = 3600,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return aggregate stats for the filtered observation set."""
        obs = self._filter(
            node_kind=node_kind,
            project_id=project_id,
            node_id=node_id,
            dag_id=dag_id,
            window_seconds=window_seconds,
            now=now,
        )
        return _aggregate(obs)

    def observations(
        self,
        *,
        node_kind: str = "",
        project_id: str = "",
        node_id: str = "",
        dag_id: str = "",
        window_seconds: int = 3600,
        now: datetime | None = None,
    ) -> list[NodeObservation]:
        """The filtered observations themselves.

        Public because two production readers reached for `store._filter` and
        `_aggregate` instead -- private names that only this implementation
        has, which is what makes swapping the store a silent change rather
        than a compile error (#698).
        """
        return self._filter(
            node_kind=node_kind,
            project_id=project_id,
            node_id=node_id,
            dag_id=dag_id,
            window_seconds=window_seconds,
            now=now,
        )

    @staticmethod
    def summarize(observations: Iterable[NodeObservation]) -> dict[str, Any]:
        """Aggregate a set the caller already holds, by the store's own rules."""
        return _aggregate(observations)

    def list_observations(
        self,
        *,
        node_kind: str = "",
        project_id: str = "",
        window_seconds: int = 3600,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        obs = self._filter(
            node_kind=node_kind,
            project_id=project_id,
            window_seconds=window_seconds,
            now=now,
        )
        return [_to_dict(o) for o in reversed(obs[-limit:])]


def _percentile(values: list[int], pct: float) -> int:
    """Linear-interpolation percentile over a pre-sorted list."""
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    rank = (pct / 100.0) * (len(values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return values[lo]
    frac = rank - lo
    return int(values[lo] + (values[hi] - values[lo]) * frac)


def _aggregate(obs: Iterable[NodeObservation]) -> dict[str, Any]:
    items = list(obs)
    n = len(items)
    if n == 0:
        return {
            "count": 0,
            "succeeded": 0,
            "failed": 0,
            "success_rate": 0.0,
            "latency_ms_measured": 0,
            "latency_ms_p50": 0,
            "latency_ms_p95": 0,
            "latency_ms_p99": 0,
            "latency_ms_mean": None,
            "tokens_measured": 0,
            "tokens_in_total": None,
            "tokens_in_mean": None,
            "tokens_out_total": None,
            "tokens_out_mean": None,
            "cost_measured": 0,
            "cost_usd_total": None,
        }
    # Each measure is averaged over the observations that *carry* it, and
    # reports how many that was. Dividing by `n` would fold every unmeasured
    # node in as a zero, which is how a DAG whose cost nobody recorded came
    # out as costing nothing rather than as unknown (#698).
    latencies = sorted(o.latency_ms for o in items if o.latency_ms is not None)
    succeeded = sum(1 for o in items if o.phase == "COMPLETED")
    failed = sum(1 for o in items if o.phase == "FAILED")
    tokens_in = [o.tokens_in for o in items if o.tokens_in is not None]
    tokens_out = [o.tokens_out for o in items if o.tokens_out is not None]
    costs = [o.cost_usd for o in items if o.cost_usd is not None]
    return {
        "count": n,
        "succeeded": succeeded,
        "failed": failed,
        "success_rate": round(succeeded / n, 4),
        "latency_ms_measured": len(latencies),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "latency_ms_p99": _percentile(latencies, 99),
        "latency_ms_mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "tokens_measured": len(tokens_in),
        "tokens_in_total": sum(tokens_in) if tokens_in else None,
        "tokens_in_mean": round(sum(tokens_in) / len(tokens_in), 1) if tokens_in else None,
        "tokens_out_total": sum(tokens_out) if tokens_out else None,
        "tokens_out_mean": round(sum(tokens_out) / len(tokens_out), 1) if tokens_out else None,
        "cost_measured": len(costs),
        "cost_usd_total": round(sum(costs), 4) if costs else None,
    }


def _to_dict(obs: NodeObservation) -> dict[str, Any]:
    return {
        "run_id": obs.run_id,
        "node_id": obs.node_id,
        "node_kind": obs.node_kind,
        "project_id": obs.project_id,
        "dag_id": obs.dag_id,
        "phase": obs.phase,
        "latency_ms": obs.latency_ms,
        "tokens_in": obs.tokens_in,
        "tokens_out": obs.tokens_out,
        "cost_usd": obs.cost_usd,
        "model_used": obs.model_used,
        "recorded_at": obs.recorded_at.isoformat(),
    }


_store = NodeMetricsStore()


def get_store() -> NodeMetricsStore:
    return _store


def set_store(store: NodeMetricsStore) -> None:
    """Replace the process store. Tests use this; so does `reset_store`."""
    global _store
    _store = store


def reset_store() -> NodeMetricsStore:
    """Install a fresh store, and return it.

    The Conductor's startup caller. `set_store` had no production caller
    either, which is the same wired-but-unread shape #236 gates -- and a
    store carried across an engine restart would mix one run's observations
    into the next process's window (#698).
    """
    set_store(NodeMetricsStore())
    return _store


def _latency_ms(node_run: Any) -> int | None:
    """Elapsed milliseconds, or `None` when the record does not say.

    `None` rather than `0`: a NodeRun missing a timestamp has an unknown
    latency, and returning zero put it into the percentiles as the fastest
    node in the window.
    """
    started = getattr(node_run, "started_at", None)
    finished = getattr(node_run, "finished_at", None)
    if not isinstance(started, datetime) or not isinstance(finished, datetime):
        return None
    return max(0, int((finished - started).total_seconds() * 1000))


def record_run_completion(run_record: Any) -> int:
    """Ingest canonical NodeRuns from a finished durable run record.

    Called from `dag_agents.run_registered_dag`, which is the Conductor's
    canonical execution path. It had no production caller at all before --
    a function that read real Run/NodeRun state, materialized the graph
    snapshot to get node types, and was reachable only from its own tests
    (#698). The observations it produces are the measured ones; the UI's
    `/v1/dags/{id}/run` path does not reach here because it mints no
    canonical Run, which is #53.
    """
    if run_record is None:
        return 0

    run = getattr(run_record, "run", None)
    if run is None:
        return 0
    graph_snapshot = getattr(run, "graph", None)
    graph = graph_snapshot.materialize() if graph_snapshot is not None else None
    node_kinds = {node.node_id: node.node_type for node in getattr(graph, "nodes", ())}

    run_id = str(getattr(run, "run_id", "") or "")
    project_id = str(getattr(run, "project_id", "") or "")
    dag_id = str(getattr(graph, "graph_id", "") or "")
    records = getattr(run_record, "node_runs", None) or ()

    appended = 0
    for node_run in records:
        status = getattr(node_run, "status", "")
        phase = str(getattr(status, "value", status) or "").upper()
        node_id = str(getattr(node_run, "node_id", "") or "")
        obs = NodeObservation(
            run_id=run_id,
            node_id=node_id,
            node_kind=node_kinds.get(node_id, ""),
            project_id=project_id,
            dag_id=dag_id,
            phase=phase,
            latency_ms=_latency_ms(node_run),
            # Absent, not zero. Attempt-level tokens, model and cost are not
            # in the durable slice yet; recording them as zeroes would make
            # every canonical run look free next to a measured one.
        )
        _store.append(obs)
        appended += 1
    return appended
