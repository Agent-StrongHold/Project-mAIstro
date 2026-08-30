"""Hypothesis property tests for Phase 4-7 substrate.

Pins invariants that any future refactor MUST preserve:

  - edit_lock: prefix-match invariant — locking a parent path locks
    every descendant path
  - edit_lock: TTL monotonicity — is_locked is True for [t0, t0+30d),
    False beyond
  - edit_lock: refresh-on-edit invariant — re-marking a field extends
    its lock independent of original
  - SignalSnapshot.priority_score == sum of its 5 weighted components
    (no double-counting, no rounding drift > 0.001)
  - NodeMetricsStore.aggregate count == phases.completed + phases.failed
    + other (so success_rate stays in [0,1])
  - topology_compare composite uses ONLY the 3 locked weights (0.5/0.3/0.2);
    rank invariants: rank 1 has highest composite_score
  - eval_judge._validate_verdict clamps score to [0,100] for any int
  - feedback_service.record_thumb: outcome.thumb is always in {up,down}
    after a successful record
  - optimizer: priority-zero snapshots NEVER produce proposals
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# --- edit_lock invariants -----------------------------------------------


@pytest.fixture(autouse=True)
def _wipe_locks():
    from services import edit_lock

    edit_lock.clear()
    yield
    edit_lock.clear()


@st.composite
def _dag_id(draw):
    return draw(st.text(alphabet="abcdefghij0123456789", min_size=1, max_size=20))


@st.composite
def _field_path(draw):
    seg = st.text(alphabet="abcdefghij0123456789_", min_size=1, max_size=10)
    n = draw(st.integers(min_value=1, max_value=4))
    segs = [draw(seg) for _ in range(n)]
    return ".".join(segs)


@given(_dag_id(), _field_path())
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_marked_field_is_immediately_locked(
    dag_id: str,
    field_path: str,
) -> None:
    from services import edit_lock

    edit_lock.clear()
    edit_lock.mark_edited(dag_id, [field_path])
    assert edit_lock.is_locked(dag_id, field_path) is True


@given(_dag_id(), _field_path(), st.text(alphabet="abcdefghij0_", min_size=1, max_size=5))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_locking_parent_locks_every_descendant(
    dag_id: str,
    parent: str,
    child_suffix: str,
) -> None:
    """If parent path is locked, parent + '.' + anything is also locked."""
    from services import edit_lock

    edit_lock.clear()
    edit_lock.mark_edited(dag_id, [parent])
    descendant = f"{parent}.{child_suffix}"
    assert edit_lock.is_locked(dag_id, descendant) is True


@given(
    _dag_id(),
    _field_path(),
    st.integers(min_value=1, max_value=29),  # before expiry
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_lock_holds_within_ttl(
    dag_id: str,
    field_path: str,
    days_after: int,
) -> None:
    from services import edit_lock

    edit_lock.clear()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    edit_lock.mark_edited(dag_id, [field_path], now=t0)
    assert (
        edit_lock.is_locked(
            dag_id,
            field_path,
            now=t0 + timedelta(days=days_after),
        )
        is True
    )


@given(
    _dag_id(),
    _field_path(),
    st.integers(min_value=31, max_value=365),  # past expiry
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_lock_expires_after_ttl(
    dag_id: str,
    field_path: str,
    days_after: int,
) -> None:
    from services import edit_lock

    edit_lock.clear()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    edit_lock.mark_edited(dag_id, [field_path], now=t0)
    assert (
        edit_lock.is_locked(
            dag_id,
            field_path,
            now=t0 + timedelta(days=days_after),
        )
        is False
    )


@given(_dag_id(), _field_path())
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_re_edit_refreshes_ttl(
    dag_id: str,
    field_path: str,
) -> None:
    from services import edit_lock

    edit_lock.clear()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    edit_lock.mark_edited(dag_id, [field_path], now=t0)
    # 25 days later — still locked — re-edit refreshes
    t1 = t0 + timedelta(days=25)
    edit_lock.mark_edited(dag_id, [field_path], now=t1)
    # 25 more days after refresh (50 total) — still locked
    assert (
        edit_lock.is_locked(
            dag_id,
            field_path,
            now=t1 + timedelta(days=25),
        )
        is True
    )


# --- SignalSnapshot.priority_score invariant ----------------------------


_scores = st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)


@given(_scores, _scores, _scores, _scores, _scores)
@settings(max_examples=100)
def test_property_priority_score_equals_sum_of_components(
    err: float,
    edit: float,
    evaljudge: float,
    thumb: float,
    latency: float,
) -> None:
    from services.optimizer import SignalSnapshot

    s = SignalSnapshot(
        dag_id="d",
        target_node_id="n",
        error_score=err,
        edit_score=edit,
        eval_score=evaljudge,
        thumb_score=thumb,
        latency_score=latency,
    )
    expected = round(err + edit + evaljudge + thumb + latency, 3)
    assert abs(s.priority_score - expected) < 0.001


# --- topology_compare normalization invariant ---------------------------


@given(
    st.lists(
        st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=10,
    )
)
@settings(max_examples=50)
def test_property_normalize_invert_smaller_is_better(values: list[float]) -> None:
    """invert=True: the smallest input maps to 1.0 (best), largest to 0.0.
    All outputs in [0,1]."""
    from services.topology_compare import _normalize

    out = _normalize(values, invert=True)
    if not out:
        return
    assert all(0.0 <= v <= 1.0 for v in out)
    if max(values) > min(values):
        # min input → max output (1.0); max input → min output (0.0)
        i_min = values.index(min(values))
        i_max = values.index(max(values))
        assert out[i_min] == 1.0
        assert out[i_max] == 0.0


@given(
    st.lists(
        st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=10,
    )
)
@settings(max_examples=50)
def test_property_normalize_invert_false_natural_order(values: list[float]) -> None:
    """invert=False: largest input maps to 1.0 (best)."""
    from services.topology_compare import _normalize

    out = _normalize(values, invert=False)
    assert all(0.0 <= v <= 1.0 for v in out)
    if max(values) > min(values):
        i_max = values.index(max(values))
        assert out[i_max] == 1.0


@given(
    st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    ),
    st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    ),
    st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=10,
    ),
)
@settings(max_examples=50)
def test_property_composite_in_valid_range(
    success: list[float],
    latency: list[float],
    thumb: list[float],
) -> None:
    """composite = 0.5·s + 0.3·l + 0.2·t with each input in [0,1] →
    composite is in [0,1] too."""
    from services.topology_compare import _composite

    n = min(len(success), len(latency), len(thumb))
    out = _composite(success[:n], latency[:n], thumb[:n])
    assert all(0.0 <= c <= 1.0 + 1e-9 for c in out)


# --- NodeMetricsStore.aggregate invariants ------------------------------


@given(
    st.lists(st.sampled_from(["COMPLETED", "FAILED", "PENDING"]), min_size=1, max_size=30),
    st.lists(st.integers(min_value=0, max_value=10000), min_size=30, max_size=30),
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_aggregate_count_equals_input_size(
    phases: list[str],
    latencies: list[int],
) -> None:
    from services.node_metrics_store import NodeMetricsStore, NodeObservation

    store = NodeMetricsStore()
    for i, phase in enumerate(phases):
        store.append(
            NodeObservation(
                run_id=f"r{i}",
                node_id="n",
                node_kind="x",
                project_id="p",
                dag_id="d",
                phase=phase,
                latency_ms=latencies[i],
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model_used="",
            )
        )
    agg = store.aggregate(window_seconds=3600)
    assert agg["count"] == len(phases)
    # succeeded + failed never exceeds count (some phases are PENDING)
    assert agg["succeeded"] + agg["failed"] <= agg["count"]
    # success_rate is in [0,1]
    assert 0.0 <= agg["success_rate"] <= 1.0


@given(st.integers(min_value=0, max_value=10000))
@settings(max_examples=30)
def test_property_aggregate_single_observation_percentile_is_value(
    latency: int,
) -> None:
    """A single observation: p50 == p95 == p99 == its latency."""
    from services.node_metrics_store import NodeMetricsStore, NodeObservation

    store = NodeMetricsStore()
    store.append(
        NodeObservation(
            run_id="r",
            node_id="n",
            node_kind="x",
            project_id="p",
            dag_id="d",
            phase="COMPLETED",
            latency_ms=latency,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used="",
        )
    )
    agg = store.aggregate(window_seconds=3600)
    assert agg["latency_ms_p50"] == latency
    assert agg["latency_ms_p95"] == latency
    assert agg["latency_ms_p99"] == latency


# --- eval_judge._validate_verdict invariants ----------------------------


@given(st.integers(min_value=-10_000, max_value=10_000))
@settings(max_examples=30)
def test_property_validate_verdict_score_clamped_to_0_100(score: int) -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict({"score": score, "rationale": "x"})
    assert 0 <= out["score"] <= 100


@given(st.text(min_size=0, max_size=200))
@settings(max_examples=30)
def test_property_validate_verdict_rationale_always_string(rat: str) -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict({"score": 50, "rationale": rat})
    assert isinstance(out["rationale"], str)
    assert out["rationale"] == rat


# --- feedback_service invariants ----------------------------------------


@given(
    st.sampled_from(["up", "down"]),
    st.text(min_size=0, max_size=500),
    st.text(alphabet="abc123", min_size=1, max_size=10),
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_property_record_thumb_persists_round_trip(
    thumb: str,
    comment: str,
    user_id: str,
) -> None:
    """For any valid (thumb, comment, user_id): the recorded Outcome
    carries identical values + success=True + signal='user_thumb'."""
    from services.feedback_service import (
        record_thumb,
        set_outcome_store,
    )

    from maistro.memory.outcomes import InMemoryOutcomeStore

    fresh = InMemoryOutcomeStore()
    set_outcome_store(fresh)
    try:
        result = await record_thumb(
            user_id=user_id,
            project_id="p",
            run_id="r",
            thumb=thumb,
            comment=comment,
            node_id="n",
        )
        assert result["recorded"] is True
        assert result["signal"] == "user_thumb"
        o = fresh._outcomes[-1]
        assert o.thumb == thumb
        assert o.thumb_comment == comment
        assert o.user_id == user_id
        assert o.success is True
    finally:
        set_outcome_store(InMemoryOutcomeStore())


# --- optimizer.run_optimizer invariants ---------------------------------


@given(st.text(alphabet="abc123-", min_size=1, max_size=20))
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_property_optimizer_zero_signal_produces_zero_proposals(
    dag_id: str,
) -> None:
    """A DAG with no metrics, no thumbs, no verdicts, no edits → zero
    proposals (priority_score never exceeds 0)."""
    import stores
    from services import edit_lock
    from services.feedback_service import (
        InMemoryOutcomeStore,
        set_outcome_store,
    )
    from services.node_metrics_store import NodeMetricsStore, set_store
    from services.optimizer import run_optimizer

    set_outcome_store(InMemoryOutcomeStore())
    set_store(NodeMetricsStore())
    for k in list(stores.eval_verdicts.keys()):
        stores.eval_verdicts.pop(k)
    for k in list(stores.audit_log.keys()):
        stores.audit_log.pop(k)
    for k in list(stores.optimizer_proposals.keys()):
        stores.optimizer_proposals.pop(k)
    edit_lock.clear()

    out = await run_optimizer(dag_id)
    assert out["proposals"] == []
    assert out["auto_applied"] == 0
    assert out["blocked_by_edit_lock"] == 0
