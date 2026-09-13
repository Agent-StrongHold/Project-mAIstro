"""Per-node latency and token metrics over a bounded durable projection.

The canonical Run/NodeRun/Attempt spine owns execution identity and lifecycle.
This module owns only a bounded, query-friendly observation projection. When
Conductor persistence is configured, observations are written to
``stores.node_metrics`` and read through that shared state database, so a
restart or another replica sees the same measurements. ``memory://`` remains
an explicit ephemeral deployment choice.

The UI run path must produce canonical identities before an observation can be
written. Legacy observations without those identities remain supported for
migration/tests, but are not allowed to masquerade as canonical execution.

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
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
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
    #: Canonical execution identities. Empty values are retained only for
    #: pre-convergence records and test doubles; canonical writers fill them.
    node_run_id: str = ""
    attempt_id: str = ""
    workspace_id: str = ""
    #: `None` where nothing measured it. Every one of these was a required
    #: field whose only non-durable writer supplied a zero or a guess.
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    model_used: str = ""
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class NodeMetricsStore:
    """Bounded observations, optionally backed by a shared JsonStore.

    ``records`` is deliberately a projection store, not a second Run store.
    Canonical ids make writes idempotent when recovery or a retry replays the
    completion callback. Reads refresh the JsonStore cache so an already
    running replica does not serve an obsolete metrics window.
    """

    def __init__(
        self,
        *,
        max_observations: int = DEFAULT_MAX_OBSERVATIONS,
        records: Any | None = None,
    ) -> None:
        if max_observations <= 0:
            raise ValueError("max_observations must be positive")
        self._buf: deque[NodeObservation] = deque(maxlen=max_observations)
        self._max_observations = max_observations
        self._records = records
        self._load_records()

    @property
    def is_durable(self) -> bool:
        return self._records is not None

    def _key(self, obs: NodeObservation) -> str:
        identity = obs.attempt_id or obs.node_run_id
        if identity:
            return identity
        # Legacy records have no canonical identity. Timestamp keeps separate
        # test/compatibility observations distinct without inventing an id.
        return f"legacy:{obs.run_id}:{obs.node_id}:{obs.recorded_at.isoformat()}"

    @staticmethod
    def _from_record(raw: dict[str, Any]) -> NodeObservation:
        data = dict(raw)
        timestamp = data.get("recorded_at")
        if isinstance(timestamp, str):
            data["recorded_at"] = datetime.fromisoformat(timestamp)
        return NodeObservation(**data)

    @staticmethod
    def _to_record(obs: NodeObservation) -> dict[str, Any]:
        raw = asdict(obs)
        raw["recorded_at"] = obs.recorded_at.isoformat()
        return raw

    def _load_records(self) -> None:
        if self._records is None:
            return
        values = getattr(self._records, "values", lambda: ())()
        observations = [self._from_record(raw) for raw in values if isinstance(raw, dict)]
        observations.sort(key=lambda item: item.recorded_at)
        kept = observations[-self._max_observations :]
        self._buf = deque(kept, maxlen=self._max_observations)
        for old in observations[: -len(kept)] if kept else observations:
            self._records.pop(self._key(old), None)

    def _refresh(self) -> None:
        if self._records is None:
            return
        initialize = getattr(self._records, "initialize", None)
        if callable(initialize):
            initialize()
        self._load_records()

    def append(self, obs: NodeObservation) -> None:
        self._refresh()
        key = self._key(obs)
        # Canonical completion callbacks may be replayed. Replace that
        # projection row rather than counting one Attempt twice.
        existing = [item for item in self._buf if self._key(item) != key]
        existing.append(obs)
        existing.sort(key=lambda item: item.recorded_at)
        evicted = existing[: -self._max_observations]
        self._buf = deque(existing[-self._max_observations :], maxlen=self._max_observations)
        if self._records is not None:
            for old in evicted:
                self._records.pop(self._key(old), None)
            self._records[key] = self._to_record(obs)

    def __len__(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        if self._records is not None:
            for key in list(self._records.keys()):
                self._records.pop(key, None)
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
        self._refresh()
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


def _percentile(values: list[int], pct: float) -> int | None:
    """Linear-interpolation percentile over a pre-sorted list, or None.

    `None` and not `0` for an empty list, and this is the same rule the rest of
    this module turns on rather than a separate nicety: a window whose nodes
    nobody timed used to report p50/p95/p99 of zero, and `topology_compare`
    normalizes p95 with `invert=True` — so a wholly unmeasured variant ranked
    as the fastest one in the comparison (Codex, #698).
    """
    if not values:
        return None
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
            "latency_ms_p50": None,
            "latency_ms_p95": None,
            "latency_ms_p99": None,
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
        "node_run_id": obs.node_run_id,
        "attempt_id": obs.attempt_id,
        "workspace_id": obs.workspace_id,
        "recorded_at": obs.recorded_at.isoformat(),
    }


_store = NodeMetricsStore()


def get_store() -> NodeMetricsStore:
    return _store


def set_store(store: NodeMetricsStore) -> None:
    """Replace the process projection. Tests and startup wiring use this seam."""
    global _store
    _store = store


def configure_store(records: Any) -> NodeMetricsStore:
    """Bind observations to the Conductor's shared durable JsonStore."""
    store = NodeMetricsStore(records=records)
    set_store(store)
    return store


def reset_store() -> NodeMetricsStore:
    """Install a fresh store, and return it.

    The Conductor's startup caller. `set_store` had no production caller
    either, which is the same wired-but-unread shape #236 gates -- and a
    store carried across an engine restart would mix one run's observations
    into the next process's window (#698).
    """
    records = _store._records
    set_store(NodeMetricsStore(records=records))
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
    workspace_id = str(getattr(run, "workspace_id", "") or "")
    project_id = str(getattr(run, "project_id", "") or "")
    dag_id = str(getattr(graph, "graph_id", "") or "")
    records = getattr(run_record, "node_runs", None) or ()
    attempts = getattr(run_record, "attempts", None) or ()

    appended = 0
    for node_run in records:
        status = getattr(node_run, "status", "")
        phase = str(getattr(status, "value", status) or "").upper()
        node_id = str(getattr(node_run, "node_id", "") or "")
        # The model the runner itself reported, not a re-resolution from node
        # config or environment: a second copy of `node.get("model", ...) or
        # CHAT_DEFAULT_MODEL` here would be two places to drift (#835 moved
        # this recording off the route and onto the canonical completion).
        result = getattr(node_run, "result", None)
        reported_model = str(result.get("model", "")) if isinstance(result, Mapping) else ""
        node_run_id = str(getattr(node_run, "node_run_id", "") or "")
        node_attempts = [
            attempt
            for attempt in attempts
            if str(getattr(attempt, "node_run_id", "") or "") == node_run_id
        ]
        latest_attempt = max(
            node_attempts,
            key=lambda attempt: int(getattr(attempt, "ordinal", 0) or 0),
            default=None,
        )
        obs = NodeObservation(
            run_id=run_id,
            node_id=node_id,
            node_kind=node_kinds.get(node_id, ""),
            project_id=project_id,
            dag_id=dag_id,
            phase=phase,
            node_run_id=node_run_id,
            attempt_id=str(getattr(latest_attempt, "attempt_id", "") or ""),
            workspace_id=workspace_id,
            latency_ms=_latency_ms(node_run),
            model_used=reported_model,
            # Absent, not zero. Attempt-level tokens and cost are not in the
            # durable slice yet; recording them as zeroes would make every
            # canonical run look free next to a measured one.
        )
        _store.append(obs)
        appended += 1
    return appended
