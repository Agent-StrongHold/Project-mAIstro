"""Boy Scout — Phase 6 optimizer.

Tests cover:

- SignalSnapshot priority_score sums all five components
- _build_snapshot_for_dag rolls up metrics + thumbs + verdicts + edits
  into one snapshot per node_id
- High error_score → AUTO_APPLY model_swap proposal
- Moderate error_score → AUTO_APPLY retry_count proposal
- High latency_score → AUTO_APPLY edge_weight proposal
- High thumb_score → PROPOSE prompt_rewrite proposal
- Eval-judge topology_proposal → PROPOSE topology_mutation proposal
- run_optimizer ranks proposals by priority_score (desc)
- apply_auto=True applies non-locked AUTO_APPLY proposals + writes
  audit_log entries
- edit_lock.is_locked() blocks auto-apply on locked fields
- apply_auto=False never applies anything (default safe mode)
- record_decision flips PENDING → ACCEPTED/REJECTED and writes audit
- record_decision invalid → ValueError
- record_decision unknown id → KeyError
- list_proposals filters by dag_id + decision and clamps limit
- run_optimizer with empty stores returns 0 proposals (no crash)
- empty dag_id raises ValueError
- HTTP: POST/run, GET/proposals, POST/accept, POST/reject
- 401 on unauthenticated
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _wipe(store: Any) -> None:
    for k in list(store.keys()):
        store.pop(k)


@pytest.fixture(autouse=True)
def _isolated():
    """Wipe every store the optimizer reads/writes for each test."""
    import stores
    from services import edit_lock
    from services.feedback_service import (
        InMemoryOutcomeStore,
        get_outcome_store,
        set_outcome_store,
    )
    from services.node_metrics_store import (
        NodeMetricsStore,
    )
    from services.node_metrics_store import (
        get_store as _get_metrics_store,
    )
    from services.node_metrics_store import (
        set_store as _set_metrics_store,
    )

    _wipe(stores.audit_log)
    _wipe(stores.eval_verdicts)
    _wipe(stores.optimizer_proposals)
    edit_lock.clear()
    prev_fb = get_outcome_store()
    set_outcome_store(InMemoryOutcomeStore())
    prev_m = _get_metrics_store()
    _set_metrics_store(NodeMetricsStore())
    yield
    _wipe(stores.audit_log)
    _wipe(stores.eval_verdicts)
    _wipe(stores.optimizer_proposals)
    edit_lock.clear()
    set_outcome_store(prev_fb)
    _set_metrics_store(prev_m)


def _seed_metrics(
    dag_id: str, node_id: str, *, count: int = 0, failed: int = 0, p95: int = 0, kind: str = "x"
) -> None:
    """Seed `count` total observations for one node, `failed` of which
    are FAILED. The p95 latency arg sets the per-observation latency."""
    from services.node_metrics_store import NodeObservation, get_store

    store = get_store()
    for i in range(count):
        phase = "FAILED" if i < failed else "COMPLETED"
        store.append(
            NodeObservation(
                run_id=f"r-{i}",
                node_id=node_id,
                node_kind=kind,
                project_id="p",
                dag_id=dag_id,
                phase=phase,
                latency_ms=p95,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                model_used="",
            )
        )


def _seed_thumb(dag_id: str, node_id: str, thumb: str, comment: str = "") -> None:
    import asyncio

    from services.feedback_service import record_thumb

    asyncio.run(
        record_thumb(
            user_id="u1",
            project_id="p",
            run_id="r",
            thumb=thumb,
            comment=comment,
            node_id=node_id,
            dag_id=dag_id,
        )
    )


def _seed_eval_verdict(
    dag_id: str,
    run_id: str,
    score: int,
    proposal: dict[str, Any] | None = None,
    *,
    scored_at: str | None = None,
) -> None:
    import stores

    stores.eval_verdicts[run_id] = {
        "run_id": run_id,
        "dag_id": dag_id,
        "score": score,
        "rationale": "stub",
        "topology_proposal": proposal,
        "scored_at": scored_at or "2026-05-22T12:00:00+00:00",
    }


# --- SignalSnapshot ------------------------------------------------------


def test_priority_score_sums_all_components() -> None:
    from services.optimizer import SignalSnapshot

    s = SignalSnapshot(
        dag_id="d",
        target_node_id="n",
        error_score=3.0,
        edit_score=1.0,
        eval_score=0.6,
        thumb_score=2.0,
        latency_score=0.5,
    )
    assert s.priority_score == 7.1


# --- _build_snapshot_for_dag --------------------------------------------


def test_build_snapshot_rolls_up_per_node() -> None:
    from services.optimizer import _build_snapshot_for_dag

    _seed_metrics("d", "n1", count=10, failed=4, p95=200)
    _seed_metrics("d", "n2", count=5, failed=0, p95=10_000)
    _seed_thumb("d", "n1", "down", "buggy")
    _seed_eval_verdict(
        "d",
        "r1",
        score=40,
        proposal={
            "kind": "swap_node_kind",
            "target_node_id": "n1",
            "from_value": "transform.alias",
            "to_value": "llm_summarize",
            "expected_improvement": "more flexible parse",
        },
    )

    snaps = _build_snapshot_for_dag("d", window_seconds=3600)
    assert "n1" in snaps
    assert "n2" in snaps
    n1 = snaps["n1"]
    # error_score = (4/10) * 3.0 = 1.2
    assert n1.error_score == 1.2
    # thumb_score (1 down) = 1.0 (weight)
    assert n1.thumb_score == 1.0
    # eval_baseline = (100-40)/100 * 1.5 = 0.9
    assert n1.eval_score == 0.9
    # n2 latency_score: p95=10_000 > threshold 5000 → 0.5
    assert snaps["n2"].latency_score == 0.5


def test_build_snapshot_no_data_returns_empty() -> None:
    from services.optimizer import _build_snapshot_for_dag

    assert _build_snapshot_for_dag("d-empty") == {}


# --- _propose_for_snapshot ----------------------------------------------


def test_propose_high_error_score_emits_model_swap() -> None:
    from services.optimizer import (
        CLASS_AUTO_APPLY,
        KIND_MODEL_SWAP,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        error_score=2.0,
        context={"metrics": {"failed": 8, "count": 10}},
    )
    out = _propose_for_snapshot(snap)
    kinds = {p["kind"] for p in out}
    classes = {p["class"] for p in out}
    assert KIND_MODEL_SWAP in kinds
    assert CLASS_AUTO_APPLY in classes


def test_propose_moderate_error_score_emits_retry_count() -> None:
    from services.optimizer import (
        KIND_MODEL_SWAP,
        KIND_RETRY_COUNT,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        error_score=0.9,
        context={"metrics": {"failed": 1, "count": 3}},
    )
    out = _propose_for_snapshot(snap)
    kinds = {p["kind"] for p in out}
    assert KIND_RETRY_COUNT in kinds
    assert KIND_MODEL_SWAP not in kinds


def test_propose_high_latency_emits_edge_weight() -> None:
    from services.optimizer import (
        KIND_EDGE_WEIGHT,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        latency_score=0.5,
        context={"metrics": {"latency_ms_p95": 9000}},
    )
    kinds = {p["kind"] for p in _propose_for_snapshot(snap)}
    assert KIND_EDGE_WEIGHT in kinds


def test_propose_high_thumb_score_emits_prompt_rewrite() -> None:
    from services.optimizer import (
        CLASS_PROPOSE,
        KIND_PROMPT,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        thumb_score=3.0,
        context={
            "thumbs": {"down": 3, "up": 0, "comments": ["weak rationale", "duplicate result"]}
        },
    )
    out = _propose_for_snapshot(snap)
    assert any(p["kind"] == KIND_PROMPT and p["class"] == CLASS_PROPOSE for p in out)


def test_propose_eval_topology_surfaced_when_target_matches() -> None:
    from services.optimizer import (
        CLASS_PROPOSE,
        KIND_TOPOLOGY,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        context={
            "eval_verdicts": [
                {
                    "score": 40,
                    "topology_proposal": {
                        "kind": "tune_param",
                        "target_node_id": "n1",
                        "from_value": "0.3",
                        "to_value": "0.7",
                        "expected_improvement": "more diversity",
                    },
                }
            ]
        },
    )
    out = _propose_for_snapshot(snap)
    topo = [p for p in out if p["kind"] == KIND_TOPOLOGY]
    assert len(topo) == 1
    assert topo[0]["class"] == CLASS_PROPOSE
    assert topo[0]["topology_proposal"]["to_value"] == "0.7"


def test_propose_eval_topology_skipped_when_target_mismatches() -> None:
    from services.optimizer import (
        KIND_TOPOLOGY,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        context={
            "eval_verdicts": [
                {
                    "score": 40,
                    "topology_proposal": {
                        "kind": "tune_param",
                        "target_node_id": "n2",  # wrong node
                    },
                }
            ]
        },
    )
    kinds = {p["kind"] for p in _propose_for_snapshot(snap)}
    assert KIND_TOPOLOGY not in kinds


def test_propose_eval_verdict_without_topology_proposal() -> None:
    """A verdict where topology_proposal is None is skipped (continue)."""
    from services.optimizer import (
        KIND_TOPOLOGY,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        context={"eval_verdicts": [{"score": 50, "topology_proposal": None}]},
    )
    kinds = {p["kind"] for p in _propose_for_snapshot(snap)}
    assert KIND_TOPOLOGY not in kinds


def test_propose_thumbs_score_high_but_no_comments() -> None:
    """thumb_score ≥ 2 with no comments — rationale falls back."""
    from services.optimizer import (
        KIND_PROMPT,
        SignalSnapshot,
        _propose_for_snapshot,
    )

    snap = SignalSnapshot(
        dag_id="d",
        target_node_id="n1",
        thumb_score=3.0,
        context={"thumbs": {"down": 3, "up": 0, "comments": []}},
    )
    out = [p for p in _propose_for_snapshot(snap) if p["kind"] == KIND_PROMPT]
    assert len(out) == 1


# --- run_optimizer end-to-end -------------------------------------------


def test_run_optimizer_with_no_signals_returns_zero_proposals() -> None:
    from services.optimizer import run_optimizer

    out = run_optimizer("d-empty")
    assert out["proposals"] == []
    assert out["auto_applied"] == 0
    assert out["blocked_by_edit_lock"] == 0


def test_run_optimizer_empty_dag_id_raises_value_error() -> None:
    from services.optimizer import run_optimizer

    with pytest.raises(ValueError, match="dag_id is required"):
        run_optimizer("")


def test_run_optimizer_default_does_not_apply() -> None:
    from services.optimizer import run_optimizer

    _seed_metrics("d1", "n1", count=10, failed=8, p95=100)
    out = run_optimizer("d1")
    # apply_auto=False default → never applied
    assert out["auto_applied"] == 0
    assert any(p["class"] == "auto_apply" for p in out["proposals"])


def test_run_optimizer_apply_auto_true_applies_unless_locked() -> None:
    from services.optimizer import run_optimizer

    _seed_metrics("d2", "n-target", count=10, failed=8, p95=100)
    out = run_optimizer("d2", apply_auto=True, actor="optimizer-bot")
    # At least the model_swap auto-applies (no edit lock)
    assert out["auto_applied"] >= 1
    # Audit log has the auto-apply entry
    import stores

    apply_entries = [e for e in stores.audit_log.values() if e["action"] == "optimizer_auto_apply"]
    assert len(apply_entries) >= 1


def test_run_optimizer_edit_lock_blocks_auto_apply() -> None:
    from services.edit_lock import mark_edited
    from services.optimizer import run_optimizer

    _seed_metrics("d3", "n1", count=10, failed=8, p95=100)
    # User just edited the model field → optimizer must NOT auto-apply on it
    mark_edited("d3", ["nodes[n1].model"], user_id="u1")
    out = run_optimizer("d3", apply_auto=True)
    # blocked_by_edit_lock incremented; proposal flagged
    assert out["blocked_by_edit_lock"] >= 1
    locked = [p for p in out["proposals"] if p["blocked_by_edit_lock"]]
    assert any(p["field_path"] == "nodes[n1].model" for p in locked)
    # The edit-locked field never got auto-applied
    assert all(not p["applied"] for p in locked)


def test_run_optimizer_ranks_by_priority_desc() -> None:
    """High error_score node should rank above low-signal node."""
    from services.optimizer import run_optimizer

    _seed_metrics("d4", "n-hot", count=10, failed=9, p95=100)
    _seed_metrics("d4", "n-cold", count=10, failed=0, p95=9000)
    out = run_optimizer("d4")
    # First proposal targets n-hot (higher error_score outweighs n-cold's latency)
    assert out["proposals"][0]["target_node_id"] == "n-hot"


def test_run_optimizer_writes_run_audit() -> None:
    import stores
    from services.optimizer import run_optimizer

    _seed_metrics("d5", "n1", count=10, failed=8, p95=100)
    run_optimizer("d5", actor="alice")
    runs = [e for e in stores.audit_log.values() if e["action"] == "optimizer_run"]
    assert len(runs) == 1
    assert runs[0]["actor"] == "alice"
    assert runs[0]["target"] == "d5"
    assert runs[0]["detail"]["proposal_count"] >= 1


# --- record_decision -----------------------------------------------------


def test_record_decision_accepts_proposal() -> None:
    import stores
    from services.optimizer import record_decision, run_optimizer

    _seed_metrics("d-dec", "n1", count=10, failed=8, p95=100)
    out = run_optimizer("d-dec")
    pid = out["proposals"][0]["id"]
    decision = record_decision(pid, "accepted", actor="alice")
    assert decision["decision"] == "accepted"
    assert decision["decided_by"] == "alice"
    # Audit log has the decision entry
    assert any(
        e["action"] == "optimizer_decision" and e["detail"]["proposal_id"] == pid
        for e in stores.audit_log.values()
    )


def test_record_decision_rejects_proposal() -> None:
    from services.optimizer import record_decision, run_optimizer

    _seed_metrics("d-rej", "n1", count=10, failed=8, p95=100)
    out = run_optimizer("d-rej")
    pid = out["proposals"][0]["id"]
    d = record_decision(pid, "rejected", actor="bob")
    assert d["decision"] == "rejected"


def test_record_decision_invalid_raises_value_error() -> None:
    from services.optimizer import record_decision

    with pytest.raises(ValueError, match="decision must be one of"):
        record_decision("any", "maybe", actor="u")


def test_record_decision_unknown_id_raises_key_error() -> None:
    from services.optimizer import record_decision

    with pytest.raises(KeyError):
        record_decision("missing-id", "accepted", actor="u")


# --- list_proposals ------------------------------------------------------


def test_list_proposals_filter_by_dag_id() -> None:
    from services.optimizer import list_proposals, run_optimizer

    _seed_metrics("d-A", "n", count=10, failed=8, p95=100)
    _seed_metrics("d-B", "n", count=10, failed=8, p95=100)
    run_optimizer("d-A")
    run_optimizer("d-B")
    items_a = list_proposals(dag_id="d-A")
    assert items_a
    assert all(p["dag_id"] == "d-A" for p in items_a)


def test_list_proposals_filter_by_decision() -> None:
    from services.optimizer import list_proposals, record_decision, run_optimizer

    # Two nodes with different failure rates → two AUTO_APPLY proposals.
    _seed_metrics("d", "n1", count=10, failed=8, p95=100)
    _seed_metrics("d", "n2", count=10, failed=7, p95=100)
    out = run_optimizer("d")
    assert len(out["proposals"]) >= 2  # spec invariant for this test
    # Accept the first; leave the rest pending.
    record_decision(out["proposals"][0]["id"], "accepted", actor="u")
    accepted = list_proposals(decision="accepted")
    assert len(accepted) == 1
    pending = list_proposals(decision="pending")
    assert len(pending) >= 1


def test_list_proposals_limit_clamped() -> None:
    from services.optimizer import list_proposals, run_optimizer

    _seed_metrics("d", "n", count=10, failed=8, p95=100)
    run_optimizer("d")
    # limit clamps to 1 minimum
    items = list_proposals(limit=0)
    assert len(items) == 1


# --- HTTP route tests ----------------------------------------------------


def test_run_endpoint_returns_ranked_proposals(admin_client: Any) -> None:
    _seed_metrics("d-http", "n1", count=10, failed=8, p95=100)
    r = admin_client.post("/v1/optimizer/d-http/run")
    assert r.status_code == 200
    body = r.json()
    assert body["dag_id"] == "d-http"
    assert body["proposals"]
    assert body["auto_applied"] == 0  # default apply_auto=False


def test_run_endpoint_with_apply_auto_true(admin_client: Any) -> None:
    _seed_metrics("d-apply", "n1", count=10, failed=8, p95=100)
    r = admin_client.post("/v1/optimizer/d-apply/run?apply_auto=true")
    assert r.status_code == 200
    assert r.json()["auto_applied"] >= 1


def test_run_endpoint_empty_dag_id_returns_400(admin_client: Any) -> None:
    """FastAPI's path can't be empty, but if a service-level ValueError
    bubbles, the route translates it to 400."""

    # Monkeypatch via the route's binding
    from routes import optimizer as routes_opt

    original = routes_opt.run_optimizer

    def _raise(*a: Any, **kw: Any) -> Any:
        raise ValueError("synthetic")

    routes_opt.run_optimizer = _raise
    try:
        r = admin_client.post("/v1/optimizer/anything/run")
        assert r.status_code == 400
    finally:
        routes_opt.run_optimizer = original


def test_list_endpoint_returns_proposals(admin_client: Any) -> None:
    _seed_metrics("d-list", "n", count=10, failed=8, p95=100)
    from services.optimizer import run_optimizer

    run_optimizer("d-list")
    r = admin_client.get("/v1/optimizer/d-list/proposals")
    assert r.status_code == 200
    items = r.json()
    assert items
    assert all(p["dag_id"] == "d-list" for p in items)


def test_list_all_endpoint(admin_client: Any) -> None:
    _seed_metrics("d-all", "n", count=10, failed=8, p95=100)
    from services.optimizer import run_optimizer

    run_optimizer("d-all")
    r = admin_client.get("/v1/optimizer/proposals?decision=pending")
    assert r.status_code == 200
    assert r.json()


def test_accept_endpoint(admin_client: Any) -> None:
    _seed_metrics("d-acc", "n", count=10, failed=8, p95=100)
    from services.optimizer import run_optimizer

    out = run_optimizer("d-acc")
    pid = out["proposals"][0]["id"]
    r = admin_client.post(f"/v1/optimizer/proposals/{pid}/accept")
    assert r.status_code == 200
    assert r.json()["decision"] == "accepted"


def test_reject_endpoint(admin_client: Any) -> None:
    _seed_metrics("d-rejhttp", "n", count=10, failed=8, p95=100)
    from services.optimizer import run_optimizer

    out = run_optimizer("d-rejhttp")
    pid = out["proposals"][0]["id"]
    r = admin_client.post(f"/v1/optimizer/proposals/{pid}/reject")
    assert r.status_code == 200
    assert r.json()["decision"] == "rejected"


def test_accept_endpoint_missing_id_returns_404(admin_client: Any) -> None:
    r = admin_client.post("/v1/optimizer/proposals/missing-id/accept")
    assert r.status_code == 404


def test_reject_endpoint_missing_id_returns_404(admin_client: Any) -> None:
    r = admin_client.post("/v1/optimizer/proposals/missing-id/reject")
    assert r.status_code == 404


def test_accept_endpoint_invalid_decision_returns_400(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force record_decision to raise ValueError — route → 400."""
    import routes.optimizer as routes_opt

    def _raise(*a: Any, **kw: Any) -> Any:
        raise ValueError("oops")

    monkeypatch.setattr(routes_opt, "record_decision", _raise)
    r = admin_client.post("/v1/optimizer/proposals/anything/accept")
    assert r.status_code == 400


def test_reject_endpoint_invalid_decision_returns_400(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same path but on reject."""
    import routes.optimizer as routes_opt

    def _raise(*a: Any, **kw: Any) -> Any:
        raise ValueError("oops")

    monkeypatch.setattr(routes_opt, "record_decision", _raise)
    r = admin_client.post("/v1/optimizer/proposals/anything/reject")
    assert r.status_code == 400


def test_run_endpoint_unauthenticated() -> None:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.post("/v1/optimizer/any/run")
    assert r.status_code == 401


def test_accept_endpoint_unauthenticated() -> None:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.post("/v1/optimizer/proposals/x/accept")
    assert r.status_code == 401


def test_reject_endpoint_unauthenticated() -> None:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.post("/v1/optimizer/proposals/x/reject")
    assert r.status_code == 401


# --- collector edge cases -----------------------------------------------


def test_collect_thumbs_ignores_blank_thumb_outcomes() -> None:
    """An Outcome with thumb='' (e.g. recorded by a non-thumbs flow)
    must NOT count toward the optimizer's signal."""
    import asyncio

    from services.feedback_service import get_outcome_store
    from services.optimizer import _collect_thumbs

    from maistro.memory.types import Outcome

    store = get_outcome_store()
    asyncio.run(store.record(Outcome(task_type="x", thumb="", dag_id="d", node_id="n")))
    out = _collect_thumbs("d")
    assert out == {}


def test_collect_thumbs_ignores_other_dag_ids() -> None:
    """A thumb tagged dag_id="other" must NOT appear in dag_id="d"'s
    aggregator."""
    _seed_thumb("other-dag", "n1", "down")
    from services.optimizer import _collect_thumbs

    assert _collect_thumbs("d") == {}


def test_collect_thumbs_thumbs_with_no_dag_id_attribution_pass_through() -> None:
    """The loose filter: outcomes with no dag_id attribution still
    surface (the wire wasn't there in older runs)."""
    import asyncio

    from services.feedback_service import record_thumb
    from services.optimizer import _collect_thumbs

    asyncio.run(
        record_thumb(
            user_id="u",
            project_id="p",
            run_id="r",
            thumb="up",
            node_id="legacy",
            dag_id="",
        )
    )
    out = _collect_thumbs("d")
    assert "legacy" in out
    assert out["legacy"]["up"] == 1


def test_user_edit_count_caps_at_five() -> None:
    """5+ dag_edit audit entries → edit_score plateaus at WEIGHT_USER_EDIT."""
    import stores
    from services.optimizer import WEIGHT_USER_EDIT, _build_snapshot_for_dag

    for i in range(7):
        stores.audit_log[f"a-{i}"] = {
            "action": "dag_edit",
            "target": "d-edits",
            "actor": "u",
            "detail": {"changed": ["name"]},
        }
    _seed_metrics("d-edits", "n", count=2, failed=0, p95=0)
    snaps = _build_snapshot_for_dag("d-edits")
    assert snaps["n"].edit_score == WEIGHT_USER_EDIT  # 1.0 * weight = weight


def test_eval_baseline_uses_most_recent_verdict() -> None:
    """Multiple verdicts → the newest one (by scored_at) drives the
    baseline."""
    from services.optimizer import _build_snapshot_for_dag

    _seed_metrics("d-multi", "n", count=2, failed=0, p95=0)
    _seed_eval_verdict("d-multi", "r-old", score=80, scored_at="2026-01-01T00:00:00+00:00")
    _seed_eval_verdict("d-multi", "r-new", score=30, scored_at="2026-05-22T12:00:00+00:00")
    snaps = _build_snapshot_for_dag("d-multi")
    # 30 → baseline (100-30)/100 = 0.7 → * 1.5 = 1.05
    assert snaps["n"].eval_score == 1.05


def test_collect_thumbs_down_without_comment_skips_append() -> None:
    """Thumbs-down with empty comment hits the `if o.thumb_comment:` =
    False branch (142→129). The down count still increments, no
    comments appended."""
    import asyncio

    from services.feedback_service import record_thumb
    from services.optimizer import _collect_thumbs

    asyncio.run(
        record_thumb(
            user_id="u",
            project_id="p",
            run_id="r",
            thumb="down",
            comment="",
            node_id="n9",
            dag_id="d-no-comment",
        )
    )
    out = _collect_thumbs("d-no-comment")
    assert out["n9"]["down"] == 1
    assert out["n9"]["comments"] == []


def test_collect_thumbs_unknown_value_falls_through() -> None:
    """Direct Outcome.thumb='weird' (bypasses service validation) must
    NOT crash. Hits the 'neither up nor down' fall-through (140→129)."""
    import asyncio

    from services.feedback_service import get_outcome_store
    from services.optimizer import _collect_thumbs

    from maistro.memory.types import Outcome

    asyncio.run(
        get_outcome_store().record(
            Outcome(
                task_type="x",
                thumb="sideways",
                dag_id="d-weird",
                node_id="n",
                user_id="u",
            )
        )
    )
    out = _collect_thumbs("d-weird")
    # Node slot was created but neither up nor down incremented.
    assert out["n"]["up"] == 0
    assert out["n"]["down"] == 0


def test_route_user_id_helper_raises_401_for_missing_id() -> None:
    """Defensive check in routes/optimizer._user_id — fires only if
    AuthMiddleware lets through a user dict without 'id' (covers route
    line 41)."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes.optimizer import _user_id

    req = SimpleNamespace(state=SimpleNamespace(user={"username": "x"}))
    with pytest.raises(HTTPException) as ei:
        _user_id(req)  # type: ignore[arg-type]
    assert ei.value.status_code == 401


def test_only_zero_score_snapshots_are_skipped() -> None:
    """A snapshot with priority_score=0 should NOT produce proposals."""
    from services.optimizer import run_optimizer

    # Seed a clean run: success-only, no thumbs, no eval, no edits.
    _seed_metrics("d-clean", "n", count=10, failed=0, p95=100)
    out = run_optimizer("d-clean")
    assert out["proposals"] == []
