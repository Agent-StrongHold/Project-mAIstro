"""Optimizer candidate/promotion contract (#861, M4-A).

Proves the M4 improvement semantics on the Conductor optimizer:

- verdict/evaluator output cannot mutate the DAG directly — an accepted
  proposal becomes an immutable candidate GraphTemplate version promoted via
  the canonical audited contract (promote_audited / PromotionApproval);
- wrong-DAG verdict fallback is rejected (verdicts only bind the DAG they
  name);
- apply_auto and accept report truthful outcomes: `applied` only after a
  candidate version actually promoted; no-op / unsupported / stale / failed
  are distinct and never reported as success;
- a promotion failure leaves the prior active Graph unchanged;
- execution-tier proposals are requests only and never self-stamp approval;
- an unmeasured latency is absent, not a None-comparison crash.

These tests pin the *application* half of the optimizer contract;
`test_optimizer.py` pins the signal/proposal half.
"""

from __future__ import annotations

import copy
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
    """Wipe every store the optimizer touches; wire a fresh template store."""
    import stores
    from services import edit_lock
    from services.feedback_service import InMemoryOutcomeStore, get_outcome_store, set_outcome_store
    from services.node_metrics_store import NodeMetricsStore
    from services.node_metrics_store import get_store as _get_metrics_store
    from services.node_metrics_store import set_store as _set_metrics_store
    from services.optimizer_candidates import set_template_store

    from maistro.graph.templates import InMemoryGraphTemplateStore

    for s in (stores.audit_log, stores.eval_verdicts, stores.optimizer_proposals, stores.dags):
        _wipe(s)
    edit_lock.clear()
    prev_fb = get_outcome_store()
    set_outcome_store(InMemoryOutcomeStore())
    prev_m = _get_metrics_store()
    _set_metrics_store(NodeMetricsStore())
    store = InMemoryGraphTemplateStore()
    set_template_store(store)
    yield store
    set_template_store(None)
    for s in (stores.audit_log, stores.eval_verdicts, stores.optimizer_proposals, stores.dags):
        _wipe(s)
    edit_lock.clear()
    set_outcome_store(prev_fb)
    _set_metrics_store(prev_m)


def _seed_dag(dag_id: str) -> dict[str, Any]:
    """A realistic editable DAG record, the shape routes/dags.py persists."""
    import stores

    snapshot = {
        "id": dag_id,
        "name": f"DAG {dag_id}",
        "description": "candidate-contract fixture",
        "entry_node": "n1",
        "max_cycles": 5,
        "run_scout": False,
        "status": "draft",
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "nodes": [
            {"id": "n1", "role": "worker", "name": "Worker", "model": "m-a", "prompt": "p"},
            {"id": "n2", "role": "reviewer", "name": "Review", "model": "m-b", "prompt": "q"},
        ],
        "edges": [{"id": "e1", "from_node": "n1", "to_node": "n2"}],
    }
    stores.dags[dag_id] = snapshot
    return snapshot


def _seed_verdict(
    dag_id: str,
    run_id: str,
    proposal: dict[str, Any] | None,
    *,
    evaluator_version: str = "eval-judge/1",
) -> None:
    import stores

    stores.eval_verdicts[run_id] = {
        "run_id": run_id,
        "dag_id": dag_id,
        "score": 42,
        "rationale": "stub",
        "status": "ok",
        "evaluator_version": evaluator_version,
        "topology_proposal": proposal,
        "scored_at": "2026-09-01T12:00:00+00:00",
    }


def _topology_proposal(**overrides: Any) -> dict[str, Any]:
    tp = {
        "kind": "swap_model",
        "target_node_id": "n1",
        "from_value": "m-a",
        "to_value": "m-strong",
        "expected_improvement": "stronger model clears the failures",
    }
    tp.update(overrides)
    return tp


async def _propose_topology(dag_id: str, tp: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one optimizer pass over a verdict carrying `tp`; return the proposal."""
    from services.optimizer import run_optimizer

    _seed_verdict(dag_id, f"run-{dag_id}", tp if tp is not None else _topology_proposal())
    out = await run_optimizer(dag_id)
    proposals = [p for p in out["proposals"] if p["kind"] == "topology_mutation"]
    assert proposals, f"expected a topology proposal for {dag_id}, got {out['proposals']}"
    return proposals[0]


# --- AC: accepted candidate creates one new active version, full provenance


async def test_accepted_candidate_promotes_one_new_active_version_with_provenance(
    _isolated: Any,
) -> None:
    from services.eval_judge import EVAL_JUDGE_VERSION
    from services.optimizer import record_decision
    from services.optimizer_candidates import snapshot_hash, template_store

    snapshot = _seed_dag("d-ok")
    proposal = await _propose_topology("d-ok")

    # Provenance bound at proposal time: exact source content hash + evaluator.
    assert proposal["source_dag_hash"] == snapshot_hash(snapshot)
    assert proposal["evaluator_version"] == EVAL_JUDGE_VERSION
    assert proposal["source_template_version"] is None  # nothing active yet
    assert proposal["applied"] is False  # a proposal never starts applied

    before = copy.deepcopy(snapshot)
    decision = await record_decision(proposal["id"], "accepted", actor="alice")

    assert decision["decision"] == "accepted"
    assert decision["apply_outcome"] == "applied"
    assert decision["applied"] is True
    assert decision["resulting_version"] == 1

    # Canonical authority: exactly one version, and it is active.
    store = template_store()
    assert await store.versions("d-ok") == [1]
    assert await store.lifecycle_of("d-ok", 1) == "active"
    template = await store.get("d-ok", version=1)
    assert template is not None
    assert template.content_hash == decision["candidate_hash"]
    assert template.lifecycle == "active"

    # The verdict-authored change is real, via the promoted content only.
    dag_after = stores_dag("d-ok")
    assert dag_after["nodes"][0]["model"] == "m-strong"
    assert dag_after != before

    # Audit says what actually happened, in the canonical order, and the
    # approver of record is the human who accepted.
    entries = list_entries()
    actions = [e["action"] for e in entries]
    assert "template_promotion_attempt" in actions
    assert "template_promotion_committed" in actions
    attempt = next(e for e in entries if e["action"] == "template_promotion_attempt")
    assert attempt["actor"] == "alice"
    assert attempt["detail"]["template_version"] == 1
    apply_entry = next(e for e in entries if e["action"] == "optimizer_apply")
    assert apply_entry["detail"]["outcome"] == "applied"
    assert apply_entry["detail"]["resulting_version"] == 1


def stores_dag(dag_id: str) -> dict[str, Any]:
    import stores

    return stores.dags[dag_id]


def list_entries() -> list[dict[str, Any]]:
    import stores

    return list(stores.audit_log.values())


async def test_historical_versions_preserved_across_successive_promotions(
    _isolated: Any,
) -> None:
    """A second accepted proposal adds a version; version 1 stays addressable
    and byte-identical (promotion preserves history, ADR-082926-65bf)."""
    from services.optimizer import record_decision
    from services.optimizer_candidates import template_store

    _seed_dag("d-hist")
    first = await _propose_topology("d-hist", _topology_proposal(to_value="m-strong"))
    d1 = await record_decision(first["id"], "accepted", actor="alice")
    assert d1["apply_outcome"] == "applied"

    # Second proposal against the *new* current state (fresh source hash).
    second = await _propose_topology("d-hist", _topology_proposal(to_value="m-stronger"))
    d2 = await record_decision(second["id"], "accepted", actor="bob")
    assert d2["apply_outcome"] == "applied"
    assert d2["resulting_version"] == 2
    # The second proposal bound the version the first promotion produced.
    assert second["source_template_version"] == 1

    store = template_store()
    assert await store.versions("d-hist") == [1, 2]
    v1 = await store.get("d-hist", version=1)
    assert v1 is not None and v1.lifecycle == "active"
    assert stores_dag("d-hist")["nodes"][0]["model"] == "m-stronger"
    # Unversioned resolution returns the latest active version (v2 content).
    latest = await store.get("d-hist")
    assert latest is not None
    assert latest.version == 2


# --- AC: verdict output cannot mutate production state directly


async def test_verdict_output_never_mutates_the_dag_without_promotion(_isolated: Any) -> None:
    """Scoring a verdict proposes; it never writes. Even an accepted proposal
    lands only through the promoted candidate — no direct verdict write."""
    from services.optimizer import record_decision, run_optimizer
    from services.optimizer_candidates import snapshot_hash, template_store

    _seed_dag("d-ev")
    hash_before = snapshot_hash(stores_dag("d-ev"))

    # A verdict whose proposal carries LLM-authored content still only proposes.
    hostile = _topology_proposal(to_value="m-pwnd")
    _seed_verdict("d-ev", "run-hostile", hostile)
    out = await run_optimizer("d-ev")
    # Scoring alone mutated nothing.
    assert snapshot_hash(stores_dag("d-ev")) == hash_before

    proposal = next(p for p in out["proposals"] if p["kind"] == "topology_mutation")
    assert proposal["topology_proposal"] == hostile
    # Still nothing written by the proposal record itself.
    assert snapshot_hash(stores_dag("d-ev")) == hash_before

    decision = await record_decision(proposal["id"], "accepted", actor="alice")
    assert decision["apply_outcome"] == "applied"
    # The only write is the promoted candidate content — bound and audited.
    store = template_store()
    assert await store.versions("d-ev") == [1]
    assert await store.lifecycle_of("d-ev", 1) == "active"


async def test_wrong_dag_verdict_fallback_is_rejected(_isolated: Any) -> None:
    """Verdicts for DAG A must never surface as proposals for DAG B — the old
    'use all verdicts' fallback is how one DAG's mutation landed on another
    (#861)."""
    from services.optimizer import _collect_eval_verdicts, run_optimizer

    _seed_dag("d-mine")
    _seed_dag("d-other")
    _seed_verdict("d-other", "run-other", _topology_proposal(target_node_id="n1"))

    assert _collect_eval_verdicts("d-mine") == []
    out = await run_optimizer("d-mine")
    assert out["proposals"] == []
    # And the other DAG's node value is untouched by this pass.
    assert stores_dag("d-other")["nodes"][0]["model"] == "m-a"


async def test_stale_proposal_refused_not_retargeted(_isolated: Any) -> None:
    """A proposal whose source hash no longer matches the current DAG content
    is refused (`stale`) — never re-targeted at whatever the DAG now holds."""
    from services.optimizer import record_decision
    from services.optimizer_candidates import snapshot_hash, template_store

    _seed_dag("d-stale")
    proposal = await _propose_topology("d-stale")

    # The user edits the DAG after the proposal was created.
    stores_dag("d-stale")["nodes"][1]["prompt"] = "human rewrite"
    hash_after_edit = snapshot_hash(stores_dag("d-stale"))

    decision = await record_decision(proposal["id"], "accepted", actor="alice")
    assert decision["decision"] == "accepted"
    assert decision["apply_outcome"] == "stale"
    assert decision["applied"] is False
    # The human edit survives verbatim; no candidate was registered.
    assert stores_dag("d-stale")["nodes"][1]["prompt"] == "human rewrite"
    assert snapshot_hash(stores_dag("d-stale")) == hash_after_edit
    assert await template_store().versions("d-stale") == []


# --- AC: fake / no-op apply is not success


async def test_no_op_apply_is_distinct_and_not_reported_as_applied(_isolated: Any) -> None:
    """A mutation that produces identical content changes nothing — it must be
    reported `no_op`, not `applied` (#861's fake-success finding)."""
    from services.optimizer import record_decision
    from services.optimizer_candidates import template_store

    _seed_dag("d-noop")
    # swap_model whose target value equals the current model → byte-identical.
    proposal = await _propose_topology("d-noop", _topology_proposal(to_value="m-a"))
    decision = await record_decision(proposal["id"], "accepted", actor="alice")
    assert decision["apply_outcome"] == "no_op"
    assert decision["applied"] is False
    assert decision["resulting_version"] is None
    assert await template_store().versions("d-noop") == []
    apply_entry = next(e for e in list_entries() if e["action"] == "optimizer_apply")
    assert apply_entry["detail"]["outcome"] == "no_op"


async def test_retry_count_auto_apply_commits_and_reports_applied(_isolated: Any) -> None:
    """The one auto-apply kind with a concrete value commits through the same
    candidate/promotion path and only then reports `applied`."""
    from services.node_metrics_store import NodeObservation, get_store
    from services.optimizer import run_optimizer
    from services.optimizer_candidates import template_store

    _seed_dag("d-auto")
    store = get_store()
    for i in range(10):
        store.append(
            NodeObservation(
                run_id=f"r-{i}",
                node_id="n1",
                node_kind="worker",
                project_id="p",
                dag_id="d-auto",
                phase="FAILED" if i < 2 else "COMPLETED",
                latency_ms=None,  # unmeasured — must not crash or fabricate
            )
        )
    out = await run_optimizer("d-auto", apply_auto=True, actor="optimizer-bot")
    retry = [p for p in out["proposals"] if p["kind"] == "retry_count_tune"]
    assert len(retry) == 1
    payload = retry[0]
    assert payload["applied"] is True
    assert payload["apply_outcome"] == "applied"
    assert out["auto_applied"] == 1
    assert payload["resulting_version"] == 1
    assert stores_dag("d-auto")["nodes"][0]["config"]["max_retries"] == 3
    assert await template_store().lifecycle_of("d-auto", 1) == "active"


async def test_human_accepted_retry_proposal_applies_via_promotion(_isolated: Any) -> None:
    """A human accepting the retry-count proposal commits the same concrete
    value through the same candidate/promotion path — the accepter is the
    approver of record."""
    from services.node_metrics_store import NodeObservation, get_store
    from services.optimizer import record_decision, run_optimizer
    from services.optimizer_candidates import template_store

    _seed_dag("d-human")
    store = get_store()
    for i in range(10):
        store.append(
            NodeObservation(
                run_id=f"r-{i}",
                node_id="n1",
                node_kind="worker",
                project_id="p",
                dag_id="d-human",
                phase="FAILED" if i < 2 else "COMPLETED",
                latency_ms=None,
            )
        )
    out = await run_optimizer("d-human")
    retry = [p for p in out["proposals"] if p["kind"] == "retry_count_tune"]
    assert len(retry) == 1
    assert retry[0]["decision"] == "pending"
    decision = await record_decision(retry[0]["id"], "accepted", actor="carol")
    assert decision["apply_outcome"] == "applied"
    assert decision["resulting_version"] == 1
    assert stores_dag("d-human")["nodes"][0]["config"]["max_retries"] == 3
    assert await template_store().lifecycle_of("d-human", 1) == "active"
    # The approver of record is the human, not the optimizer.
    attempt = next(e for e in list_entries() if e["action"] == "template_promotion_attempt")
    assert attempt["actor"] == "carol"


async def test_accepted_prompt_rewrite_is_manual_not_applied(_isolated: Any) -> None:
    """A prompt rewrite needs the human's words: the decision is recorded,
    the outcome is `manual`, and the optimizer claims no application."""
    from services.feedback_service import record_thumb
    from services.optimizer import record_decision, run_optimizer
    from services.optimizer_candidates import snapshot_hash, template_store

    _seed_dag("d-prompt")
    hash_before = snapshot_hash(stores_dag("d-prompt"))
    await record_thumb(
        user_id="u1",
        project_id="p",
        run_id="r1",
        thumb="down",
        comment="ignores the schema",
        node_id="n1",
        dag_id="d-prompt",
    )
    await record_thumb(
        user_id="u2",
        project_id="p",
        run_id="r2",
        thumb="down",
        comment="truncates output",
        node_id="n1",
        dag_id="d-prompt",
    )
    out = await run_optimizer("d-prompt")
    prompt = [p for p in out["proposals"] if p["kind"] == "prompt_rewrite"]
    assert len(prompt) == 1
    decision = await record_decision(prompt[0]["id"], "accepted", actor="dave")
    assert decision["decision"] == "accepted"
    assert decision["apply_outcome"] == "manual"
    assert decision["applied"] is False
    assert snapshot_hash(stores_dag("d-prompt")) == hash_before
    assert await template_store().versions("d-prompt") == []


# --- AC: promotion failure leaves prior active Graph unchanged


async def test_promotion_failure_rolls_back_and_reports_failed(
    _isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the committed-audit write fails, promote_audited compensates back to
    candidate, the DAG record is unchanged, and the outcome is `failed` — the
    prior active state is never disturbed and nothing claims success."""
    import routes.audit as audit_routes
    from services.optimizer import record_decision
    from services.optimizer_candidates import snapshot_hash, template_store

    from maistro.graph.templates import promote_audited  # noqa: F401  (import sanity)

    _seed_dag("d-fail")
    hash_before = snapshot_hash(stores_dag("d-fail"))
    proposal = await _propose_topology("d-fail")

    real_log_audit = audit_routes.log_audit

    def _failing_audit(action: str, *args: Any, **kw: Any) -> None:
        if action == "template_promotion_committed":
            raise RuntimeError("audit sink down")
        real_log_audit(action, *args, **kw)

    monkeypatch.setattr(audit_routes, "log_audit", _failing_audit)

    decision = await record_decision(proposal["id"], "accepted", actor="alice")
    assert decision["decision"] == "accepted"
    assert decision["apply_outcome"] == "failed"
    assert decision["applied"] is False
    assert decision["resulting_version"] is None

    # Compensated: the version exists but is a candidate again — not active,
    # not served, and the descriptor is byte-identical to before.
    store = template_store()
    assert await store.versions("d-fail") == [1]
    assert await store.lifecycle_of("d-fail", 1) == "candidate"
    assert snapshot_hash(stores_dag("d-fail")) == hash_before
    assert stores_dag("d-fail")["nodes"][0]["model"] == "m-a"
    # The attempt was recorded; no committed entry exists; no applied claim.
    entries = list_entries()
    assert any(e["action"] == "template_promotion_attempt" for e in entries)
    assert not any(e["action"] == "template_promotion_committed" for e in entries)
    apply_entry = next(e for e in entries if e["action"] == "optimizer_apply")
    assert apply_entry["detail"]["outcome"] == "failed"


# --- AC: execution-tier proposals are requests only


async def test_execution_tier_proposal_is_request_only_never_self_stamped(
    _isolated: Any,
) -> None:
    """Accepting an upgrade_execution_tier proposal records an escalation
    request for the delegated authority; it never mutates the DAG and never
    writes an approval stamp (the old code wrote tier_approved_by='admin')."""
    from services.optimizer import record_decision
    from services.optimizer_candidates import snapshot_hash, template_store

    _seed_dag("d-tier")
    hash_before = snapshot_hash(stores_dag("d-tier"))
    proposal = await _propose_topology(
        "d-tier",
        _topology_proposal(kind="upgrade_execution_tier", to_value="container"),
    )

    decision = await record_decision(proposal["id"], "accepted", actor="alice")
    assert decision["decision"] == "accepted"
    assert decision["apply_outcome"] == "escalated"
    assert decision["applied"] is False

    # Nothing applied, nothing stamped, nothing registered.
    dag = stores_dag("d-tier")
    assert snapshot_hash(dag) == hash_before
    assert await template_store().versions("d-tier") == []
    dumped = repr(dag)
    assert "tier_approved_by" not in dumped
    assert "execution_tier" not in dumped

    # The request record exists for the authority to decide on.
    escalation = [e for e in list_entries() if e["action"] == "optimizer_escalation_request"]
    assert len(escalation) == 1
    assert escalation[0]["detail"]["requested_value"] == "container"
    assert escalation[0]["detail"]["requested_by"] == "alice"


def test_no_code_path_writes_tier_approval_stamp() -> None:
    """The self-stamp write is gone from the source, not just from one branch:
    no assignment of a tier approval value may exist (mentions in prose
    documenting the removed behavior are fine)."""
    import pathlib
    import re

    backend = pathlib.Path(__file__).resolve().parents[1]
    assignment = re.compile(r"tier_approved_by\"?\]?\s*=")
    dict_key = re.compile(r"\"tier_approved_by\"\s*:")
    # The guard must be able to catch the historical write, else it proves
    # nothing (a vacuous regex would pass forever).
    assert assignment.search('node["config"]["tier_approved_by"] = "admin"')
    assert dict_key.search('{"tier_approved_by": actor}')
    for name in ("services/optimizer.py", "services/optimizer_candidates.py"):
        source = (backend / name).read_text()
        assert not assignment.search(source), f"{name} assigns a tier approval stamp"
        assert not dict_key.search(source), f"{name} writes a tier approval stamp key"


# --- AC: missing latency is absent, not a crash or an ideal score


async def test_unmeasured_latency_contributes_nothing_without_crashing(
    _isolated: Any,
) -> None:
    """p95 of `None` (nothing measured) must not raise a None comparison and
    must not rank as fast/ideal: it contributes zero, with the measured count
    surfaced beside it (ADR-083026-a91e)."""
    from services.node_metrics_store import NodeObservation, get_store
    from services.optimizer import LATENCY_P95_THRESHOLD_MS, _build_snapshot_for_dag

    _seed_dag("d-lat")
    store = get_store()
    for i in range(3):
        store.append(
            NodeObservation(
                run_id=f"r-{i}",
                node_id="n1",
                node_kind="worker",
                project_id="p",
                dag_id="d-lat",
                phase="COMPLETED",
                latency_ms=None,  # the unmeasured case the old code crashed on
            )
        )
    snapshots = await _build_snapshot_for_dag("d-lat")
    snap = snapshots["n1"]
    assert snap.latency_score == 0.0
    assert snap.context["metrics"]["latency_ms_p95"] is None
    assert snap.context["latency_ms_measured"] == 0
    # And the threshold is genuinely above zero, so this is not vacuous.
    assert LATENCY_P95_THRESHOLD_MS > 0


async def test_measured_latency_above_threshold_still_scores(_isolated: Any) -> None:
    """The policy fix did not mute real measurements: a measured slow p95
    still contributes the latency weight."""
    from services.node_metrics_store import NodeObservation, get_store
    from services.optimizer import _build_snapshot_for_dag

    _seed_dag("d-slow")
    store = get_store()
    for i in range(2):
        store.append(
            NodeObservation(
                run_id=f"r-{i}",
                node_id="n1",
                node_kind="worker",
                project_id="p",
                dag_id="d-slow",
                phase="COMPLETED",
                latency_ms=10_000,
            )
        )
    snapshots = await _build_snapshot_for_dag("d-slow")
    assert snapshots["n1"].latency_score > 0.0
    assert snapshots["n1"].context["latency_ms_measured"] == 2


# --- #861 repair: store resolution, workspace binding, and the failure
# --- vocabulary of commit_candidate (every distinct outcome is pinned)


def test_template_store_resolves_the_engine_container_bridge(
    _isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the canonical engine bridge is wired, the optimizer promotes
    through the Container's template store — not a private lifecycle."""
    from types import SimpleNamespace

    import services.engine as engine_mod
    from services import optimizer_candidates as oc

    wired = SimpleNamespace(name="engine-store")
    fake_engine = SimpleNamespace(
        _agent_port=SimpleNamespace(container=SimpleNamespace(template_store=wired))
    )
    monkeypatch.setattr(engine_mod, "get_engine", lambda: fake_engine)
    # No explicit override: the engine resolution wins.
    oc.set_template_store(None)
    try:
        assert oc.template_store() is wired
    finally:
        oc.set_template_store(None)


async def test_active_template_version_none_when_only_candidates_exist(
    _isolated: Any,
) -> None:
    """A registered-but-never-promoted version is not the active version:
    candidates never masquerade as the DAG's live template."""
    from services.optimizer_candidates import active_template_version, template_store

    from maistro.graph.template_adapter import snapshot_to_template

    snapshot = _seed_dag("d-cand")
    template = snapshot_to_template(
        copy.deepcopy(snapshot), workspace_id="ws-t", template_id="d-cand", version=1
    ).model_copy(update={"lifecycle": "candidate"})
    await template_store().put(template)
    assert await template_store().versions("d-cand") == [1]
    assert await active_template_version("d-cand") is None


def test_authorized_workspace_wins_over_the_configured_default() -> None:
    """The candidate registers in the Workspace the request was authorized
    against — the configured default never overrides the authorizing tenant
    (#861 review)."""
    from services.optimizer_candidates import _workspace_id_for

    assert _workspace_id_for("d", {}, authorized_workspace_id="ws-auth") == "ws-auth"
    # Without an authorizing scope the legacy chain still resolves.
    assert _workspace_id_for("d-ws", {"workspace_id": "ws-snap"}) in {"ws-snap", "default"}


async def test_candidate_registers_in_the_authorizing_workspace(_isolated: Any) -> None:
    """End to end: commit_candidate lands the version under the authorized
    Workspace even though settings default to another."""
    from services.optimizer_candidates import commit_candidate, snapshot_hash, template_store

    snapshot = _seed_dag("d-ws2")
    committed = await commit_candidate(
        "d-ws2",
        {**copy.deepcopy(snapshot), "entry_node": "n2"},
        actor="alice",
        proposal_id="p-ws",
        source_hash=snapshot_hash(snapshot),
        reason="swap entry",
        workspace_id="ws-authorizing",
    )
    assert committed["outcome"] == "applied"
    template = await template_store().get("d-ws2", version=1)
    assert template is not None
    assert template.workspace_id == "ws-authorizing"


async def test_concurrent_edit_during_promotion_is_compensated(
    _isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CAS-2: a human edit landing between the promotion commit and the
    descriptor sync is never overwritten — the just-promoted version is
    demoted, the prior active version restored, the outcome `stale`."""
    import stores
    from services.optimizer import record_decision
    from services.optimizer_candidates import template_store

    import maistro.graph.templates as templates_mod

    _seed_dag("d-race")
    first = await _propose_topology("d-race", _topology_proposal(to_value="m-strong"))
    d1 = await record_decision(first["id"], "accepted", actor="alice")
    assert d1["apply_outcome"] == "applied"
    assert await template_store().lifecycle_of("d-race", 1) == "active"

    second = await _propose_topology("d-race", _topology_proposal(to_value="m-stronger"))
    real_promote = templates_mod.promote_audited

    async def _racing_promote(store: Any, template_id: str, version: int, **kw: Any) -> None:
        # The human edit lands after the promotion committed but before the
        # descriptor sync sees the DAG again.
        stores.dags["d-race"]["nodes"][1]["prompt"] = "concurrent human edit"
        await real_promote(store, template_id, version, **kw)

    monkeypatch.setattr(templates_mod, "promote_audited", _racing_promote)

    d2 = await record_decision(second["id"], "accepted", actor="bob")
    assert d2["apply_outcome"] == "stale"
    assert d2["applied"] is False
    # The racing version was demoted; the prior active version was restored.
    assert await template_store().lifecycle_of("d-race", 2) == "candidate"
    assert await template_store().lifecycle_of("d-race", 1) == "active"
    # The concurrent edit survives verbatim — never overwritten.
    assert stores.dags["d-race"]["nodes"][1]["prompt"] == "concurrent human edit"
    assert stores.dags["d-race"]["nodes"][0]["model"] == "m-strong"  # v1 content


async def test_failed_rollback_after_moved_base_reports_the_failed_compensation(
    _isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the descriptor moved AND the compensating demote fails, the record
    says exactly that — no silent success, no silent half-state."""
    import stores
    from services.optimizer import record_decision
    from services.optimizer_candidates import template_store

    import maistro.graph.templates as templates_mod

    _seed_dag("d-rbf")
    first = await _propose_topology("d-rbf", _topology_proposal(to_value="m-strong"))
    await record_decision(first["id"], "accepted", actor="alice")

    second = await _propose_topology("d-rbf", _topology_proposal(to_value="m-stronger"))
    real_promote = templates_mod.promote_audited

    async def _racing_promote(store: Any, template_id: str, version: int, **kw: Any) -> None:
        stores.dags["d-rbf"]["nodes"][1]["prompt"] = "moved during apply"
        await real_promote(store, template_id, version, **kw)

    monkeypatch.setattr(templates_mod, "promote_audited", _racing_promote)
    store = template_store()
    real_set_lifecycle = store.set_lifecycle

    async def _failing_demote(template_id: str, version: int, lifecycle: str) -> None:
        if lifecycle == "candidate" and version == 2:  # the compensation demote
            raise RuntimeError("lifecycle sink down")
        return await real_set_lifecycle(template_id, version, lifecycle)

    monkeypatch.setattr(store, "set_lifecycle", _failing_demote)

    d2 = await record_decision(second["id"], "accepted", actor="bob")
    assert d2["apply_outcome"] == "stale"
    assert "rollback of version 2 failed" in d2["apply_detail"]
    assert "descriptor left untouched" in d2["apply_detail"]
    # The descriptor still holds the concurrent edit, untouched.
    assert stores.dags["d-rbf"]["nodes"][1]["prompt"] == "moved during apply"
    applies = [e for e in list_entries() if e["action"] == "optimizer_apply"]
    assert applies[-1]["detail"]["outcome"] == "stale"


async def test_unreadable_template_store_reports_failed(_isolated: Any) -> None:
    """A template store that cannot even be listed is a `failed` apply with
    the failure named — never a fabricated success."""
    from services.optimizer_candidates import commit_candidate, set_template_store, snapshot_hash

    class _Unreadable:
        async def versions(self, template_id: str) -> list[int]:
            raise RuntimeError("store down")

    snapshot = _seed_dag("d-uns")
    set_template_store(_Unreadable())
    committed = await commit_candidate(
        "d-uns",
        {**copy.deepcopy(snapshot), "entry_node": "n2"},
        actor="alice",
        proposal_id="p-uns",
        source_hash=snapshot_hash(snapshot),
    )
    assert committed["outcome"] == "failed"
    assert "template store unreadable" in committed["detail"]


async def test_source_hash_moving_before_commit_is_refused(_isolated: Any) -> None:
    """CAS-1: the descriptor moved after the synchronous binding check but
    before commit_candidate ran — refuse, never re-target."""
    from services.optimizer_candidates import commit_candidate, snapshot_hash, template_store

    snapshot = _seed_dag("d-cas1")
    source = snapshot_hash(snapshot)
    # The DAG changes between proposal time and apply time.
    stores_dag("d-cas1")["nodes"][0]["prompt"] = "edited later"
    committed = await commit_candidate(
        "d-cas1",
        {**copy.deepcopy(snapshot), "entry_node": "n2"},
        actor="alice",
        proposal_id="p-cas1",
        source_hash=source,
    )
    assert committed["outcome"] == "stale"
    assert "DAG changed while the proposal was being applied" in committed["detail"]
    assert await template_store().versions("d-cas1") == []


async def test_refused_projection_reports_failed(
    _isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A projection refusal (the reviewed adapter rejects the snapshot) is
    `failed` with the refusal named — no partial registration."""
    from services.optimizer_candidates import commit_candidate, snapshot_hash, template_store

    import maistro.graph.template_adapter as adapter_mod

    snapshot = _seed_dag("d-proj")

    def _refusing(*args: Any, **kw: Any) -> Any:
        raise ValueError("adapter refuses this snapshot")

    monkeypatch.setattr(adapter_mod, "snapshot_to_template", _refusing)
    committed = await commit_candidate(
        "d-proj",
        {**copy.deepcopy(snapshot), "entry_node": "n2"},
        actor="alice",
        proposal_id="p-proj",
        source_hash=snapshot_hash(snapshot),
    )
    assert committed["outcome"] == "failed"
    assert "candidate projection refused" in committed["detail"]
    assert await template_store().versions("d-proj") == []


async def test_registration_failure_reports_failed(_isolated: Any) -> None:
    """A store that refuses the candidate put is `failed` — nothing is
    claimed and nothing was promoted."""
    from services.optimizer_candidates import commit_candidate, set_template_store, snapshot_hash

    from maistro.graph.templates import InMemoryGraphTemplateStore

    class _RefusingPut(InMemoryGraphTemplateStore):
        async def put(self, template: Any) -> Any:
            raise RuntimeError("registration refused")

    snapshot = _seed_dag("d-put")
    set_template_store(_RefusingPut())
    committed = await commit_candidate(
        "d-put",
        {**copy.deepcopy(snapshot), "entry_node": "n2"},
        actor="alice",
        proposal_id="p-put",
        source_hash=snapshot_hash(snapshot),
    )
    assert committed["outcome"] == "failed"
    assert "candidate registration failed" in committed["detail"]


async def test_descriptor_sync_failure_reports_failed_not_applied(
    _isolated: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The version promoted but the editable descriptor sync raised: the
    record says the version is active yet the apply `failed` — no `applied`
    claim over a surface that was never updated."""
    import stores
    from services.optimizer_candidates import commit_candidate, snapshot_hash, template_store

    snapshot = _seed_dag("d-sync")

    class _Unwritable(dict):  # type: ignore[type-arg]
        def __setitem__(self, key: str, value: Any) -> None:
            if key == "d-sync":
                raise RuntimeError("descriptor sink down")
            super().__setitem__(key, value)

    monkeypatch.setattr(stores, "dags", _Unwritable(dict(stores.dags)))
    committed = await commit_candidate(
        "d-sync",
        {**copy.deepcopy(snapshot), "entry_node": "n2"},
        actor="alice",
        proposal_id="p-sync",
        source_hash=snapshot_hash(snapshot),
    )
    assert committed["outcome"] == "failed"
    assert "descriptor sync failed" in committed["detail"]
    assert committed["resulting_version"] is None
    # The canonical authority DID commit the promoted version — the record's
    # detail names that divergence rather than hiding it.
    assert "version 1 is active" in committed["detail"]
    assert await template_store().lifecycle_of("d-sync", 1) == "active"
