"""Optimizer auto-promotion is gated on completed independent validation (#2501).

`POST /v1/optimizer/{dag_id}/run?validate=true&apply_auto=true` used to mean
apply-then-validate: ``run_optimizer`` promoted every AUTO_APPLY candidate the
moment it was proposed, and only afterwards did the route run the baseline and
filter the proposal list. A worse, failed or never-evaluated candidate could
therefore become the active template version, and a baseline that raised was
scored as a synthetic ``0.0``.

These tests pin the ordered operations that replace it:

  1. propose        — candidates are *staged*; nothing is applied;
  2. evaluate       — the incumbent is measured as typed evidence (a failure is
                      "unavailable", never ``0.0``) and each staged candidate is
                      measured against it;
  3. approve        — the canonical promotion contract (#116) gates on the
                      evidence: Run ids, evaluator version, staleness, approver;
  4. promote        — only an approved candidate reaches ``commit_candidate``.

Every route test drives the real ASGI app through ``admin_client``; the store
tests drive the service seams. The DAG executor and evaluator are faked at
their module seams with realistic shapes (canonical Run ids, judge Run ids,
Invocation ids, usage) so lineage assertions are about plumbing, not luck.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_EVALUATOR_VERSION = "benchmark-eval/1"


def _wipe(store: Any) -> None:
    for key in list(store.keys()):
        store.pop(key)


@pytest.fixture(autouse=True)
def _isolated():
    """Fresh proposal/audit/verdict stores, a fresh template store, no locks."""
    import stores
    from services import edit_lock
    from services.feedback_service import InMemoryOutcomeStore, get_outcome_store, set_outcome_store
    from services.node_metrics_store import NodeMetricsStore
    from services.node_metrics_store import get_store as _get_metrics_store
    from services.node_metrics_store import set_store as _set_metrics_store
    from services.optimizer_candidates import set_template_store

    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.memory.exposure import MemoryExposureMode

    for store in (stores.audit_log, stores.eval_verdicts, stores.optimizer_proposals):
        _wipe(store)
    edit_lock.clear()
    prev_fb = get_outcome_store()
    set_outcome_store(InMemoryOutcomeStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED))
    prev_metrics = _get_metrics_store()
    _set_metrics_store(NodeMetricsStore())
    template_store = InMemoryGraphTemplateStore()
    set_template_store(template_store)
    yield template_store
    set_template_store(None)
    for store in (stores.audit_log, stores.eval_verdicts, stores.optimizer_proposals):
        _wipe(store)
    edit_lock.clear()
    set_outcome_store(prev_fb)
    _set_metrics_store(prev_metrics)


def _seed_retry_signal(dag_id: str, node_id: str) -> None:
    """2 of 10 runs failed → error_score 0.6 → the retry_count_tune proposal.

    The one AUTO_APPLY kind that carries a concrete value, so the only one that
    can stage a committable candidate."""
    from services.node_metrics_store import NodeObservation, get_store

    store = get_store()
    for i in range(10):
        store.append(
            NodeObservation(
                run_id=f"r-{i}",
                node_id=node_id,
                node_kind="worker",
                project_id="p",
                dag_id=dag_id,
                phase="FAILED" if i < 2 else "COMPLETED",
                latency_ms=None,
            )
        )


def _seed_dag(dag_id: str) -> dict[str, Any]:
    """A realistic editable DAG record, the shape routes/dags.py persists."""
    import stores

    snapshot = {
        "id": dag_id,
        "name": f"DAG {dag_id}",
        "description": "promotion-gate fixture",
        "entry_node": "n1",
        "max_cycles": 5,
        "run_scout": False,
        "status": "draft",
        "created_at": "2026-11-01T00:00:00+00:00",
        "updated_at": "2026-11-01T00:00:00+00:00",
        "nodes": [
            {"id": "n1", "role": "worker", "name": "Worker", "model": "m-a", "prompt": "p"},
            {"id": "n2", "role": "reviewer", "name": "Review", "model": "m-b", "prompt": "q"},
        ],
        "edges": [{"id": "e1", "from_node": "n1", "to_node": "n2"}],
    }
    stores.dags[dag_id] = snapshot
    return snapshot


def _without_retry_budget(dag_data: dict[str, Any]) -> dict[str, Any]:
    """The snapshot with every node's retry budget removed."""
    clone = copy.deepcopy(dag_data)
    for node in clone.get("nodes", []):
        config = node.get("config")
        if config is not None:
            config.pop("max_retries", None)
            if not config:
                node.pop("config")
    return clone


def _classify(dag_data: dict[str, Any], source: dict[str, Any] | None) -> str:
    """Which measurement an executed snapshot is: the incumbent itself, the
    staged candidate (the incumbent plus a retry budget, nothing else), or a
    hill-climb variant (a model swap or a param sweep)."""
    if source is None:
        has_budget = any(
            "max_retries" in (n.get("config") or {}) for n in dag_data.get("nodes", [])
        )
        return "candidate" if has_budget else "baseline"
    if dag_data == source:
        return "baseline"
    if _without_retry_budget(dag_data) == _without_retry_budget(source):
        return "candidate"
    return "other"


class _EvaluatorHarness:
    """Deterministic executor + evaluator fakes with full canonical lineage.

    Records every measurement so tests can assert on paid work: how many times
    the incumbent ran, how many times the candidate was judged. The kind of
    each measurement travels on the execution *result* (not a call index), so
    the count stays right under concurrent (interleaved) evaluation.
    """

    def __init__(
        self,
        *,
        baseline_total: float | None = 10,
        candidate_total: float | None = 10,
        baseline_error: str = "",
        candidate_error: str = "",
        baseline_raises: BaseException | None = None,
        candidate_raises: BaseException | None = None,
        drop_lineage: bool = False,
        yield_control: bool = False,
        source: dict[str, Any] | None = None,
    ) -> None:
        self.baseline_total = baseline_total
        self.candidate_total = candidate_total
        self.baseline_error = baseline_error
        self.candidate_error = candidate_error
        self.baseline_raises = baseline_raises
        self.candidate_raises = candidate_raises
        self.drop_lineage = drop_lineage
        self.yield_control = yield_control
        self.source = source
        self.measurements: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> _EvaluatorHarness:
        import services.benchmark_eval as benchmark_eval
        import services.graph_runner as graph_runner

        async def fake_execute(dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
            if self.yield_control:
                # Let a concurrent request reach the same in-flight evaluation.
                await asyncio.sleep(0)
            kind = _classify(dag_data, self.source)
            self.measurements.append(kind)
            raises = self.candidate_raises if kind == "candidate" else self.baseline_raises
            if raises is not None:
                raise raises
            return {
                "status": "completed",
                "run_id": f"run-{len(self.measurements)}",
                "workspace_id": "ws",
                "project_id": "proj",
                "node_results": {},
                # Test-only markers: which variant this result is the output
                # of, and its ordinal among executions.
                "_variant_kind": kind,
                "_variant_index": len(self.measurements),
            }

        async def fake_score(result: Any, _task: Any) -> dict[str, Any]:
            kind = str(result.get("_variant_kind") or "other")
            index = int(result.get("_variant_index") or 0)
            error = self.candidate_error if kind == "candidate" else self.baseline_error
            if error and kind != "other":
                # The exact refusal shape benchmark_eval returns for a missing
                # Binding, a billing refusal, or any other governed-egress
                # refusal: a typed error with a synthetic ``total: 0``.
                return {"error": error, "error_kind": "authorization", "total": 0, "pass": False}
            if kind == "candidate":
                total = self.candidate_total
            elif kind == "baseline":
                total = self.baseline_total
            else:
                total = 10
            if total is None:
                return {}
            score: dict[str, Any] = {
                "total": total,
                "pass": total >= 35,
                "invocation_id": f"inv-{index}",
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "cost_usd": 0.0001},
                "evaluator_version": _EVALUATOR_VERSION,
            }
            if not self.drop_lineage or kind != "candidate":
                score["evaluation_run_id"] = f"eval-run-{index}"
            return score

        monkeypatch.setattr(graph_runner, "execute_dag", fake_execute)
        monkeypatch.setattr(benchmark_eval, "evaluate_dag_run", fake_score)
        return self

    def count(self, kind: str) -> int:
        return sum(1 for measured in self.measurements if measured == kind)

    @property
    def candidate_evaluations(self) -> int:
        return self.count("candidate")

    @property
    def baseline_evaluations(self) -> int:
        return self.count("baseline")


def _workspace(client: Any) -> str:
    response = client.post(
        "/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": "Promotion Gate"}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _real_dag(client: Any, name: str) -> dict[str, Any]:
    response = client.post("/v1/dags", json={"name": name, "description": "promotion gate"})
    assert response.status_code == 201
    return response.json()


def _run(client: Any, dag_id: str, workspace_id: str, *, validate: bool = True) -> Any:
    query = (
        f"apply_auto=true&validate={'true' if validate else 'false'}&workspace_id={workspace_id}"
    )
    return client.post(f"/v1/optimizer/{dag_id}/run?{query}")


def _retry_proposal(body: dict[str, Any]) -> dict[str, Any]:
    proposals = [p for p in body["proposals"] if p.get("kind") == "retry_count_tune"]
    assert len(proposals) == 1, body["proposals"]
    return proposals[0]


def _promotion_audit(dag_id: str) -> list[dict[str, Any]]:
    """Every audit entry a promotion leaves behind, for one DAG."""
    import stores

    return [
        e
        for e in stores.audit_log.values()
        if e.get("target") == dag_id
        and e.get("action")
        in {
            "template_promotion_attempt",
            "template_promotion_committed",
            "optimizer_apply",
        }
    ]


def _descriptor_hash(dag_id: str) -> str:
    import stores
    from services.optimizer_candidates import snapshot_hash

    return snapshot_hash(stores.dags[dag_id])


async def _versions(dag_id: str) -> list[int]:
    from services.optimizer_candidates import template_store

    return await template_store().versions(dag_id)


# --- AC: a worse or failed candidate never becomes the active version ----------


def test_worse_candidate_is_not_promoted_through_the_route(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """validate=true&apply_auto=true against a seeded failure-signal candidate
    whose independent score is WORSE than the incumbent: the active version is
    unchanged, nothing is accepted/applied, no promotion audit exists, and
    auto_applied does not count it."""
    dag = _real_dag(admin_client, "Gate: worse candidate")
    _seed_retry_signal(dag["id"], dag["nodes"][1]["id"])
    workspace_id = _workspace(admin_client)
    _EvaluatorHarness(baseline_total=10, candidate_total=5, source=dag).install(monkeypatch)
    hash_before = _descriptor_hash(dag["id"])

    response = _run(admin_client, dag["id"], workspace_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_applied"] == 0
    assert not any(p.get("applied") for p in body["proposals"])
    assert not any(p.get("decision") == "accepted" for p in body["proposals"])
    retry = _retry_proposal(body)
    assert retry["apply_outcome"] == "not_improving"
    assert retry["applied"] is False
    assert retry["decision"] == "pending"
    # The comparison is on the record: the candidate was measured, and lost.
    assert retry["variant_b_score"] == 5
    assert retry["baseline_score"] == 10
    # Active version unchanged: no version exists, the descriptor is intact.
    assert asyncio.run(_versions(dag["id"])) == []
    assert _descriptor_hash(dag["id"]) == hash_before
    assert _promotion_audit(dag["id"]) == []
    # The persisted row agrees with the response.
    import stores

    assert stores.optimizer_proposals[retry["id"]]["apply_outcome"] == "not_improving"


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param("execution_raise", id="baseline-exception"),
        pytest.param("timeout", id="timeout"),
        pytest.param("binding_refused", id="missing-binding"),
        pytest.param("billing_refused", id="billing-refusal"),
    ],
)
def test_unavailable_baseline_is_typed_never_zero_and_blocks_promotion(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A baseline that raises, times out, or is refused by the governed egress
    is UNAVAILABLE evidence — not score 0.0 — and no candidate is judged or
    promoted against it."""
    dag = _real_dag(admin_client, f"Gate: {failure}")
    _seed_retry_signal(dag["id"], dag["nodes"][1]["id"])
    workspace_id = _workspace(admin_client)
    raises: BaseException | None = None
    error = ""
    if failure == "execution_raise":
        raises = RuntimeError("canonical Run ended failed")
    elif failure == "timeout":
        raises = TimeoutError()
    elif failure == "binding_refused":
        error = "no capability Binding resolves model m-a"
    elif failure == "billing_refused":
        error = "InvocationDenied: billing quota exhausted"
    harness = _EvaluatorHarness(baseline_raises=raises, baseline_error=error, source=dag).install(
        monkeypatch
    )
    hash_before = _descriptor_hash(dag["id"])

    response = _run(admin_client, dag["id"], workspace_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_applied"] == 0
    # Typed unavailable evidence, not a synthetic zero.
    assert body["baseline_score"] is None
    assert body["baseline_status"] == "unavailable"
    assert body["baseline_detail"]
    assert body["validated"] is False
    retry = _retry_proposal(body)
    assert retry["applied"] is False
    assert retry["apply_outcome"] == "unevaluated"
    assert "variant_b_score" not in retry
    # The candidate was never judged — no paid evaluation against a fake zero.
    assert harness.candidate_evaluations == 0
    assert asyncio.run(_versions(dag["id"])) == []
    assert _descriptor_hash(dag["id"]) == hash_before
    assert _promotion_audit(dag["id"]) == []


def test_missing_evaluator_is_unavailable_not_a_zero_score(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An evaluator that returns nothing usable is unavailable evidence."""
    dag = _real_dag(admin_client, "Gate: missing evaluator")
    _seed_retry_signal(dag["id"], dag["nodes"][1]["id"])
    workspace_id = _workspace(admin_client)
    harness = _EvaluatorHarness(baseline_total=None, source=dag).install(monkeypatch)

    response = _run(admin_client, dag["id"], workspace_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["baseline_score"] is None
    assert body["baseline_status"] == "unavailable"
    assert body["auto_applied"] == 0
    assert harness.candidate_evaluations == 0
    assert asyncio.run(_versions(dag["id"])) == []


def test_validate_false_cannot_skip_policy_required_evaluation(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply_auto=true&validate=false does not silently skip the evaluation a
    promotion requires: nothing is executed, nothing is promoted, and the
    staged candidate says exactly why."""
    dag = _real_dag(admin_client, "Gate: validate=false")
    _seed_retry_signal(dag["id"], dag["nodes"][1]["id"])
    workspace_id = _workspace(admin_client)
    harness = _EvaluatorHarness(baseline_total=0, candidate_total=100, source=dag).install(
        monkeypatch
    )
    hash_before = _descriptor_hash(dag["id"])

    response = _run(admin_client, dag["id"], workspace_id, validate=False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_applied"] == 0
    retry = _retry_proposal(body)
    assert retry["applied"] is False
    assert retry["apply_outcome"] == "unevaluated"
    assert "validation" in retry["apply_detail"]
    assert harness.measurements == []
    assert asyncio.run(_versions(dag["id"])) == []
    assert _descriptor_hash(dag["id"]) == hash_before
    assert _promotion_audit(dag["id"]) == []


# --- AC: an independently better candidate is promoted once, with lineage ------


def test_improving_candidate_is_promoted_once_with_full_lineage(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent validation improves on the incumbent and the policy passes:
    the exact candidate version is promoted exactly once, the Run / evaluator
    Invocation / cost lineage is recorded on the proposal and in audit, and the
    prior version stays addressable."""
    import services.optimizer as opt
    import stores
    from services.optimizer_candidates import template_store

    dag = _real_dag(admin_client, "Gate: improving candidate")
    dag_id = dag["id"]
    _seed_retry_signal(dag_id, dag["nodes"][1]["id"])
    workspace_id = _workspace(admin_client)
    _EvaluatorHarness(baseline_total=10, candidate_total=12, source=dag).install(monkeypatch)
    hash_before = _descriptor_hash(dag_id)

    response = _run(admin_client, dag_id, workspace_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_applied"] == 1
    retry = _retry_proposal(body)
    assert retry["applied"] is True
    assert retry["apply_outcome"] == "applied"
    assert retry["decision"] == "accepted"
    assert retry["resulting_version"] == 1
    assert retry["source_dag_hash"] == hash_before

    # Exactly one version, active, and the descriptor is its projection.
    assert asyncio.run(_versions(dag_id)) == [1]
    assert asyncio.run(template_store().lifecycle_of(dag_id, 1)) == "active"
    assert stores.dags[dag_id]["nodes"][1]["config"]["max_retries"] == 3
    audit = _promotion_audit(dag_id)
    assert [e["action"] for e in audit] == [
        "template_promotion_attempt",
        "template_promotion_committed",
        "optimizer_apply",
    ]

    # Lineage: the evidence that justified the promotion is on the record.
    validation = retry["validation"]
    assert validation["status"] == "improved"
    assert validation["baseline"]["evaluation_run_id"] == "eval-run-1"
    assert validation["baseline"]["run_id"] == "run-1"
    assert validation["candidate"]["evaluation_run_id"] == "eval-run-2"
    assert validation["candidate"]["run_id"] == "run-2"
    assert validation["candidate"]["invocation_id"] == "inv-2"
    assert validation["candidate"]["usage"]["cost_usd"] == 0.0001
    assert validation["evaluator_version"] == _EVALUATOR_VERSION
    apply_entry = next(e for e in audit if e["action"] == "optimizer_apply")
    assert apply_entry["detail"]["resulting_version"] == 1
    assert apply_entry["detail"]["policy_id"] == "optimizer-auto-promotion/strict-improvement"
    assert "eval-run-1" in apply_entry["detail"]["evidence"]["evaluation_run_ids"]
    assert "eval-run-2" in apply_entry["detail"]["evidence"]["evaluation_run_ids"]
    assert apply_entry["detail"]["evidence"]["evaluator_version"] == _EVALUATOR_VERSION

    # The canonical promotion contract recorded it, traceable by version.
    trace = asyncio.run(_trace(dag_id, 1))
    assert trace is not None
    assert trace.record.approval.policy_id == "optimizer-auto-promotion/strict-improvement"
    assert trace.record.prior_content_hash == hash_before
    assert set(trace.record.evidence.evaluation_run_ids) >= {"eval-run-1", "eval-run-2"}

    # A second, different improvement promotes v2; v1 stays addressable and
    # byte-identical (history does not change).
    v1 = asyncio.run(template_store().get(dag_id, version=1))
    assert v1 is not None
    _seed_retry_signal(dag_id, dag["nodes"][1]["id"])
    monkeypatch.setattr(
        opt,
        "_propose_for_snapshot",
        lambda snap: [
            {
                "class": opt.CLASS_AUTO_APPLY,
                "kind": opt.KIND_RETRY_COUNT,
                "field_path": f"nodes[{snap.target_node_id}].config.max_retries",
                "to_value": 5,
                "rationale": "a larger retry budget",
            }
        ],
    )
    # The incumbent is now the promoted content; the second candidate adds a
    # larger retry budget on top of it.
    harness = _EvaluatorHarness(
        baseline_total=10, candidate_total=14, source=dict(stores.dags[dag_id])
    )
    harness.install(monkeypatch)
    second = _run(admin_client, dag_id, workspace_id)
    assert second.status_code == 200, second.text
    assert second.json()["auto_applied"] == 1
    assert asyncio.run(_versions(dag_id)) == [1, 2]
    v1_after = asyncio.run(template_store().get(dag_id, version=1))
    assert v1_after is not None and v1_after.content_hash == v1.content_hash
    assert stores.dags[dag_id]["nodes"][1]["config"]["max_retries"] == 5
    second_audit = _promotion_audit(dag_id)
    assert [e["action"] for e in second_audit].count("template_promotion_committed") == 2


async def _trace(dag_id: str, version: int):
    from services.optimizer_candidates import promotion_contract

    from maistro.governance.promotion import PromotionScope

    return promotion_contract().ledger.trace(PromotionScope.TEMPLATE, dag_id, version)


# --- AC: concurrent calls with the same source version -------------------------


def test_concurrent_runs_share_one_paid_evaluation_and_yield_one_winner(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two optimizer runs over the same source version promote ONE winning
    version; the loser is explicit (`stale`, naming the competing version),
    the candidate is judged once, and exactly one promotion is audited."""
    import stores
    from services.optimizer_candidates import template_store

    dag = _real_dag(admin_client, "Gate: concurrent")
    dag_id = dag["id"]
    _seed_retry_signal(dag_id, dag["nodes"][1]["id"])
    workspace_id = _workspace(admin_client)
    harness = _EvaluatorHarness(
        baseline_total=10, candidate_total=12, yield_control=True, source=dag
    ).install(monkeypatch)

    async def _both() -> list[dict[str, Any]]:
        import httpx
        from main import app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/v1/auth/login", json={"username": "testadmin", "password": "adminpass"}
            )
            assert login.status_code == 200, login.text
            responses = await asyncio.gather(
                *[
                    client.post(
                        f"/v1/optimizer/{dag_id}/run?apply_auto=true&workspace_id={workspace_id}"
                    )
                    for _ in range(2)
                ]
            )
            assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
            return [r.json() for r in responses]

    bodies = asyncio.run(_both())

    retries = [_retry_proposal(b) for b in bodies]
    applied = [p for p in retries if p["applied"]]
    assert len(applied) == 1, retries
    assert applied[0]["resulting_version"] == 1
    loser = next(p for p in retries if not p["applied"])
    assert loser["apply_outcome"] == "stale"
    assert loser["decision"] == "pending"
    assert loser["competing_version"] == 1
    # One winning promotion: one version, one committed audit entry.
    assert asyncio.run(_versions(dag_id)) == [1]
    assert asyncio.run(template_store().lifecycle_of(dag_id, 1)) == "active"
    assert [e["action"] for e in _promotion_audit(dag_id)].count(
        "template_promotion_committed"
    ) == 1
    # The idempotent candidate was judged once, not once per caller.
    assert harness.candidate_evaluations == 1
    assert harness.baseline_evaluations == 1
    # The persisted rows agree with both responses.
    for p in retries:
        stored = stores.optimizer_proposals[p["id"]]
        assert stored["apply_outcome"] == p["apply_outcome"]
        assert stored["applied"] is p["applied"]
    assert sum(b["auto_applied"] for b in bodies) == 1


# --- AC: the order is evaluation BEFORE promotion ------------------------------


def test_route_orders_evaluation_before_promotion_in_source() -> None:
    """The route's phase calls appear in the order propose → evaluate → promote.
    Swapping evaluation and apply re-introduces the #2501 defect, so the order
    is pinned on the source, not only on behaviour."""
    route = _BACKEND / "routes" / "optimizer.py"
    tree = ast.parse(route.read_text())
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "trigger_optimizer"
    )
    # ``ast.walk`` is breadth-first; source order is what the test pins.
    calls = [
        node.func.id
        for node in sorted(
            ast.walk(handler), key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0))
        )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "run_optimizer" in calls
    assert "evaluate_staged_proposals" in calls
    assert "promote_evaluated" in calls
    assert (
        calls.index("run_optimizer")
        < calls.index("evaluate_staged_proposals")
        < calls.index("promote_evaluated")
    )
    # And the route never commits a candidate itself.
    assert "commit_candidate" not in calls
    assert "_apply_auto_proposal" not in calls


def test_route_never_scores_a_failed_baseline_as_zero() -> None:
    """The literal `baseline = 0.0` fallback is gone from the route source."""
    route = (_BACKEND / "routes" / "optimizer.py").read_text()
    assert "baseline = 0.0" not in route
    assert (
        "except Exception:" not in route.split("def trigger_optimizer")[1].split("@router.get")[0]
    )


# --- store seams: staging, evidence quality, and refusals ---------------------


async def test_run_optimizer_alone_stages_but_never_promotes() -> None:
    """Phase 1 only: `run_optimizer(apply_auto=True)` stages a concrete
    candidate and reports it `staged` — no version, no descriptor change, no
    promotion audit. Promotion belongs to phases 3 and 4."""
    from services.optimizer import run_optimizer

    snapshot = _seed_dag("d-stage")
    _seed_retry_signal("d-stage", "n1")
    out = await run_optimizer("d-stage", apply_auto=True, actor="optimizer-bot", workspace_id="ws")
    retry = _retry_proposal(out)
    assert out["auto_applied"] == 0
    assert retry["applied"] is False
    assert retry["apply_outcome"] == "staged"
    assert retry["decision"] == "pending"
    assert retry["staged_candidate_hash"]
    assert retry["staged_candidate_hash"] != retry["source_dag_hash"]
    import stores

    assert stores.dags["d-stage"] == snapshot
    assert await _versions("d-stage") == []
    assert _promotion_audit("d-stage") == []


@pytest.mark.parametrize(
    ("harness_kwargs", "fragment"),
    [
        pytest.param({"drop_lineage": True}, "lineage", id="no-evaluation-run-id"),
        pytest.param(
            {"candidate_error": "InvocationDenied: billing"}, "refused", id="candidate-refused"
        ),
        pytest.param(
            {"candidate_raises": RuntimeError("variant failed")}, "failed", id="candidate-failed"
        ),
    ],
)
async def test_candidate_without_completed_evaluation_is_unevaluated(
    monkeypatch: pytest.MonkeyPatch, harness_kwargs: dict[str, Any], fragment: str
) -> None:
    """A candidate whose evaluation did not complete — no judge Run id, a
    governed-egress refusal, a failed variant run — is `unevaluated`, never
    promoted, whatever its score would have been."""
    import services.optimizer as opt

    dag_id = "d-unevaluated"
    _seed_dag(dag_id)
    _seed_retry_signal(dag_id, "n1")
    _EvaluatorHarness(baseline_total=10, candidate_total=99, **harness_kwargs).install(monkeypatch)
    scope = _scope()
    out = await opt.run_optimizer(dag_id, apply_auto=True, actor="alice", workspace_id="ws")
    out.update(
        await opt.evaluate_staged_proposals(
            dag_id, dict(_dag(dag_id)), out["proposals"], scope=scope
        )
    )
    out["auto_applied"] = await opt.promote_evaluated(
        dag_id, out["proposals"], actor="alice", workspace_id="ws", evaluation_ran=True
    )
    retry = _retry_proposal(out)
    assert out["auto_applied"] == 0
    assert retry["apply_outcome"] == "unevaluated"
    assert fragment in retry["apply_detail"]
    assert await _versions(dag_id) == []
    assert _promotion_audit(dag_id) == []


async def test_self_approval_by_the_authoring_path_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optimizer authored the candidate; it cannot also be the authority
    that approves it. A run whose only approver is `optimizer` is refused by
    the canonical contract's self-approval fence."""
    import services.optimizer as opt

    dag_id = "d-self"
    _seed_dag(dag_id)
    _seed_retry_signal(dag_id, "n1")
    _EvaluatorHarness(baseline_total=10, candidate_total=20).install(monkeypatch)
    out = await opt.run_optimizer(dag_id, apply_auto=True, actor="optimizer", workspace_id="ws")
    out.update(
        await opt.evaluate_staged_proposals(
            dag_id, dict(_dag(dag_id)), out["proposals"], scope=_scope()
        )
    )
    out["auto_applied"] = await opt.promote_evaluated(
        dag_id, out["proposals"], actor="optimizer", workspace_id="ws", evaluation_ran=True
    )
    retry = _retry_proposal(out)
    assert out["auto_applied"] == 0
    assert retry["applied"] is False
    assert retry["apply_outcome"] == "failed"
    assert "self-approval" in retry["apply_detail"]
    assert await _versions(dag_id) == []


async def test_promotion_failure_leaves_incumbent_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy approved and the evidence was complete, but the promotion
    itself failed (the committed-audit sink was down): the incumbent is
    byte-identical, nothing is active, and the outcome is `failed`."""
    import routes.audit as audit_routes
    import services.optimizer as opt

    dag_id = "d-promote-fails"
    snapshot = _seed_dag(dag_id)
    _seed_retry_signal(dag_id, "n1")
    _EvaluatorHarness(baseline_total=10, candidate_total=20).install(monkeypatch)
    real_log_audit = audit_routes.log_audit

    def _failing_audit(action: str, *args: Any, **kw: Any) -> None:
        if action == "template_promotion_committed":
            raise RuntimeError("audit sink down")
        real_log_audit(action, *args, **kw)

    monkeypatch.setattr(audit_routes, "log_audit", _failing_audit)
    out = await opt.run_optimizer(dag_id, apply_auto=True, actor="alice", workspace_id="ws")
    out.update(
        await opt.evaluate_staged_proposals(
            dag_id, dict(_dag(dag_id)), out["proposals"], scope=_scope()
        )
    )
    out["auto_applied"] = await opt.promote_evaluated(
        dag_id, out["proposals"], actor="alice", workspace_id="ws", evaluation_ran=True
    )
    retry = _retry_proposal(out)
    assert out["auto_applied"] == 0
    assert retry["apply_outcome"] == "failed"
    assert retry["applied"] is False
    import stores

    assert stores.dags[dag_id] == snapshot
    assert await _versions(dag_id) == [1]  # registered, compensated back to candidate
    from services.optimizer_candidates import template_store

    assert await template_store().lifecycle_of(dag_id, 1) == "candidate"
    # The contract ledger holds no record for a version that never activated.
    assert await _trace(dag_id, 1) is None


def _scope():
    from services.dag_execution_scope import DagExecutionScope

    return DagExecutionScope(workspace_id="ws", project_id="proj", user_id="alice")


def _dag(dag_id: str) -> dict[str, Any]:
    import stores

    return stores.dags[dag_id]


def test_evaluator_reports_its_version() -> None:
    """The evaluator version the evidence fence requires is the evaluator's
    own, not a constant the gate invents."""
    import services.benchmark_eval as benchmark_eval

    assert benchmark_eval.BENCHMARK_EVAL_VERSION == _EVALUATOR_VERSION
    source = pathlib.Path(benchmark_eval.__file__).read_text()
    # Stamped on the success payload, beside the Run and Invocation lineage.
    assert 'score["evaluator_version"] = BENCHMARK_EVAL_VERSION' in source
