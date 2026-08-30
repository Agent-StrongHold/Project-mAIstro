"""Boy Scout — Phase 7 topology compare service + endpoints.

Tests cover:
- _resolve_label returns "(unset)" for missing / empty values
- _bucket_observations groups by the chosen field
- _normalize handles single-value lists + identical values (variance=0)
- _normalize invert flag controls smaller-is-better
- _composite uses the locked weight constants (0.5/0.3/0.2)
- compare_variants groups by model_used, node_kind, node_id
- compare_variants ranks descending by composite_score
- compare_variants returns winner
- compare_variants empty data → empty variants + empty winner
- compare_variants raises ValueError on empty dag_id + invalid group_by
- _fold_in_thumbs only attributes thumbs when group_by='node_id'
- HTTP: GET /v1/topology/{dag_id}/compare (200 / 400)
- HTTP: GET /v1/topology/group-fields
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _isolated_metrics_and_outcomes():
    from services.feedback_service import (
        InMemoryOutcomeStore,
        get_outcome_store,
        set_outcome_store,
    )
    from services.node_metrics_store import (
        NodeMetricsStore,
        get_store,
        set_store,
    )

    prev_fb = get_outcome_store()
    prev_m = get_store()
    set_outcome_store(InMemoryOutcomeStore())
    set_store(NodeMetricsStore())
    yield
    set_outcome_store(prev_fb)
    set_store(prev_m)


def _seed_obs(
    *, dag_id: str, node_id: str, model: str, kind: str, latency: int, phase: str = "COMPLETED"
) -> None:
    from services.node_metrics_store import NodeObservation, get_store

    get_store().append(
        NodeObservation(
            run_id=f"r-{node_id}-{model}",
            node_id=node_id,
            node_kind=kind,
            project_id="p",
            dag_id=dag_id,
            phase=phase,
            latency_ms=latency,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model_used=model,
        )
    )


# --- helpers --------------------------------------------------------------


def test_resolve_label_uses_attr_value() -> None:
    from services.node_metrics_store import NodeObservation
    from services.topology_compare import _resolve_label

    o = NodeObservation(
        run_id="r",
        node_id="n1",
        node_kind="x",
        project_id="p",
        dag_id="d",
        phase="COMPLETED",
        latency_ms=10,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        model_used="gpt-4",
    )
    assert _resolve_label(o, "model_used") == "gpt-4"
    assert _resolve_label(o, "node_id") == "n1"


def test_resolve_label_empty_string_falls_back_to_unset() -> None:
    from services.node_metrics_store import NodeObservation
    from services.topology_compare import _resolve_label

    o = NodeObservation(
        run_id="r",
        node_id="n1",
        node_kind="x",
        project_id="p",
        dag_id="d",
        phase="COMPLETED",
        latency_ms=10,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        model_used="",
    )
    assert _resolve_label(o, "model_used") == "(unset)"


def test_normalize_single_value_returns_half() -> None:
    """No variance → all 0.5; invert flag doesn't matter."""
    from services.topology_compare import _normalize

    assert _normalize([7.0]) == [0.5]
    assert _normalize([7.0], invert=False) == [0.5]


def test_normalize_identical_values_returns_halves() -> None:
    from services.topology_compare import _normalize

    assert _normalize([3.0, 3.0, 3.0]) == [0.5, 0.5, 0.5]


def test_normalize_invert_true_makes_smaller_better() -> None:
    from services.topology_compare import _normalize

    out = _normalize([10.0, 30.0, 50.0], invert=True)
    # 10 → 1.0 (best), 50 → 0.0 (worst)
    assert out[0] == 1.0
    assert out[2] == 0.0


def test_normalize_invert_false_keeps_natural_order() -> None:
    from services.topology_compare import _normalize

    out = _normalize([10.0, 30.0, 50.0], invert=False)
    assert out[0] == 0.0
    assert out[2] == 1.0


def test_normalize_empty_list_returns_empty() -> None:
    from services.topology_compare import _normalize

    assert _normalize([]) == []


def test_composite_uses_locked_weights() -> None:
    from services.topology_compare import _composite

    out = _composite([1.0], [1.0], [1.0])
    assert out == [0.85]  # W_SUCCESS(0.4) + W_LATENCY(0.25) + W_THUMB(0.2) + W_COST(0.15*0) = 0.85


def test_bucket_observations_groups_by_field() -> None:
    from services.node_metrics_store import NodeObservation
    from services.topology_compare import _bucket_observations

    a = NodeObservation(
        run_id="r",
        node_id="n1",
        node_kind="k",
        project_id="p",
        dag_id="d",
        phase="COMPLETED",
        latency_ms=10,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        model_used="gpt-4",
    )
    b = NodeObservation(
        run_id="r",
        node_id="n1",
        node_kind="k",
        project_id="p",
        dag_id="d",
        phase="COMPLETED",
        latency_ms=20,
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.0,
        model_used="claude",
    )
    buckets = _bucket_observations([a, b], "model_used")
    assert set(buckets) == {"gpt-4", "claude"}
    assert buckets["gpt-4"].observations == [a]
    assert buckets["claude"].observations == [b]


def test_variant_bucket_success_rate_zero_when_empty() -> None:
    from services.topology_compare import VariantBucket

    b = VariantBucket(label="x")
    assert b.success_rate == 0.0
    # Was `== 0`. A bucket with nothing in it has no p95, and reporting zero
    # made it the fastest variant once the scoring inverted it (Codex, #698).
    assert b.p95_latency is None
    assert b.thumb_down_rate == 0.0


def test_variant_bucket_thumb_down_rate_no_total_is_zero() -> None:
    from services.topology_compare import VariantBucket

    b = VariantBucket(label="x")  # no thumbs at all
    assert b.thumb_down_rate == 0.0


# --- compare_variants end-to-end ----------------------------------------


def test_compare_variants_returns_ranked_variants() -> None:
    from services.topology_compare import compare_variants

    # Two variants: gpt-4 succeeds, claude fails
    for _ in range(5):
        _seed_obs(
            dag_id="d", node_id="n1", model="gpt-4", kind="llm", latency=100, phase="COMPLETED"
        )
    for _ in range(5):
        _seed_obs(dag_id="d", node_id="n1", model="claude", kind="llm", latency=300, phase="FAILED")

    out = compare_variants("d", group_by="model_used")
    assert out["dag_id"] == "d"
    assert out["group_by"] == "model_used"
    assert len(out["variants"]) == 2
    # gpt-4 wins (100% success, lower latency, no thumb-down)
    assert out["winner"] == "gpt-4"
    assert out["variants"][0]["label"] == "gpt-4"
    assert out["variants"][0]["rank"] == 1
    assert out["variants"][1]["rank"] == 2
    # Success rates
    assert out["variants"][0]["success_rate"] == 1.0
    assert out["variants"][1]["success_rate"] == 0.0


def test_compare_variants_empty_returns_no_winner() -> None:
    from services.topology_compare import compare_variants

    out = compare_variants("d-empty")
    assert out["winner"] == ""
    assert out["variants"] == []


def test_compare_variants_groups_by_node_kind() -> None:
    from services.topology_compare import compare_variants

    _seed_obs(dag_id="d", node_id="n1", model="x", kind="jira.poll", latency=100)
    _seed_obs(dag_id="d", node_id="n2", model="x", kind="transform.alias", latency=10)
    out = compare_variants("d", group_by="node_kind")
    assert {v["label"] for v in out["variants"]} == {"jira.poll", "transform.alias"}


def test_compare_variants_groups_by_node_id_includes_thumbs() -> None:
    """When group_by='node_id', thumbs attribute to the matching bucket."""
    import asyncio

    from services.feedback_service import record_thumb
    from services.topology_compare import compare_variants

    _seed_obs(dag_id="d", node_id="n-good", model="x", kind="k", latency=100)
    _seed_obs(dag_id="d", node_id="n-bad", model="x", kind="k", latency=100)
    asyncio.run(
        record_thumb(
            user_id="u",
            project_id="p",
            run_id="r",
            thumb="down",
            node_id="n-bad",
            dag_id="d",
        )
    )
    out = compare_variants("d", group_by="node_id")
    bad = next(v for v in out["variants"] if v["label"] == "n-bad")
    good = next(v for v in out["variants"] if v["label"] == "n-good")
    assert bad["thumb_down"] == 1
    assert good["thumb_down"] == 0
    # The thumbs-down should hurt n-bad's composite
    assert good["composite_score"] >= bad["composite_score"]


def test_compare_variants_thumbs_not_folded_for_non_node_id_group() -> None:
    import asyncio

    from services.feedback_service import record_thumb
    from services.topology_compare import compare_variants

    _seed_obs(dag_id="d", node_id="n1", model="gpt-4", kind="k", latency=100)
    asyncio.run(
        record_thumb(
            user_id="u",
            project_id="p",
            run_id="r",
            thumb="down",
            node_id="n1",
            dag_id="d",
        )
    )
    out = compare_variants("d", group_by="model_used")
    # No thumb counts attributed when grouping by model
    assert out["variants"][0]["thumb_down"] == 0


def test_compare_variants_empty_dag_id_raises() -> None:
    from services.topology_compare import compare_variants

    with pytest.raises(ValueError, match="dag_id is required"):
        compare_variants("")


def test_compare_variants_invalid_group_by_raises() -> None:
    from services.topology_compare import compare_variants

    with pytest.raises(ValueError, match="group_by must be one of"):
        compare_variants("d", group_by="something_weird")


def test_compare_variants_unknown_thumb_value_does_not_increment() -> None:
    """Direct outcome bypass: thumb='sideways' must not increment up or
    down. Hits the elif fall-through inside _fold_in_thumbs (line 116)."""
    import asyncio

    from services.feedback_service import get_outcome_store
    from services.topology_compare import compare_variants

    from maistro.memory.types import Outcome

    _seed_obs(dag_id="d", node_id="n1", model="x", kind="k", latency=10)
    asyncio.run(
        get_outcome_store().record(
            Outcome(
                task_type="x",
                thumb="sideways",
                dag_id="d",
                node_id="n1",
                user_id="u",
            )
        )
    )
    out = compare_variants("d", group_by="node_id")
    bucket = next(v for v in out["variants"] if v["label"] == "n1")
    assert bucket["thumb_up"] == 0
    assert bucket["thumb_down"] == 0


def test_fold_in_thumbs_skips_other_dag_outcomes() -> None:
    """An Outcome tagged with a different dag_id must NOT contribute to
    this DAG's buckets (covers `continue` on line 110)."""
    import asyncio

    from services.feedback_service import record_thumb
    from services.topology_compare import compare_variants

    _seed_obs(dag_id="d-target", node_id="n", model="x", kind="k", latency=10)
    asyncio.run(
        record_thumb(
            user_id="u",
            project_id="p",
            run_id="r",
            thumb="down",
            node_id="n",
            dag_id="some-other-dag",
        )
    )
    out = compare_variants("d-target", group_by="node_id")
    bucket = next(v for v in out["variants"] if v["label"] == "n")
    assert bucket["thumb_down"] == 0


def test_fold_in_thumbs_skips_outcomes_with_blank_thumb() -> None:
    """An Outcome with thumb='' (e.g. one recorded by a non-feedback
    flow) is skipped (covers `continue` on line 112)."""
    import asyncio

    from services.feedback_service import get_outcome_store
    from services.topology_compare import compare_variants

    from maistro.memory.types import Outcome

    _seed_obs(dag_id="d-blank", node_id="n", model="x", kind="k", latency=10)
    asyncio.run(
        get_outcome_store().record(
            Outcome(
                task_type="x",
                thumb="",
                dag_id="d-blank",
                node_id="n",
                user_id="u",
            )
        )
    )
    out = compare_variants("d-blank", group_by="node_id")
    bucket = next(v for v in out["variants"] if v["label"] == "n")
    assert bucket["thumb_up"] == 0
    assert bucket["thumb_down"] == 0


def test_compare_variants_thumbs_for_unseeded_node_creates_bucket() -> None:
    """A thumb on a node that has NO observations still creates a
    bucket — the user told us something even if the metrics didn't."""
    import asyncio

    from services.feedback_service import record_thumb
    from services.topology_compare import compare_variants

    # Seed a different node so the dag has observations at all
    _seed_obs(dag_id="d", node_id="n-seen", model="x", kind="k", latency=10)
    asyncio.run(
        record_thumb(
            user_id="u",
            project_id="p",
            run_id="r",
            thumb="up",
            node_id="n-only-thumbs",
            dag_id="d",
        )
    )
    out = compare_variants("d", group_by="node_id")
    labels = {v["label"] for v in out["variants"]}
    assert "n-only-thumbs" in labels


# --- HTTP routes ---------------------------------------------------------


def test_topology_compare_endpoint_returns_payload(authed_client: Any) -> None:
    _seed_obs(dag_id="d-http", node_id="n", model="gpt-4", kind="k", latency=100)
    _seed_obs(dag_id="d-http", node_id="n", model="claude", kind="k", latency=100, phase="FAILED")
    r = authed_client.get("/v1/topology/d-http/compare")
    assert r.status_code == 200
    body = r.json()
    assert body["winner"] == "gpt-4"


def test_topology_compare_endpoint_400_on_invalid_group_by(authed_client: Any) -> None:
    r = authed_client.get("/v1/topology/d/compare?group_by=bogus")
    assert r.status_code == 400


def test_topology_group_fields_endpoint(authed_client: Any) -> None:
    r = authed_client.get("/v1/topology/group-fields")
    assert r.status_code == 200
    fields = r.json()
    assert "model_used" in fields
    assert "node_id" in fields
    assert "node_kind" in fields


def test_topology_compare_endpoint_unauthenticated() -> None:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.get("/v1/topology/d/compare")
    assert r.status_code == 401
