"""#1087: real Evolve execution composes declared model authority and Run evidence.

Only the gateway transport/corpus size are replaced. Graph execution, population,
IFEval scoring, Binding bootstrap/resolution, credential routing, Invocation and
quota recording are production implementations. Background actor/readiness
selection remains the #1867 owner decision; these are request-scoped Runs.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from services.evolution import _EvolutionService
from services.evolution_graph import (
    FinalizeReconciliationRequired,
    _evaluate_one,
    _finalize_cycle,
    run_canonical_evolution_cycle,
)

from maistro.capabilities.effect_context import binding_scope_policy, new_in_memory_effect_context
from maistro.capabilities.model_binding_bootstrap import bootstrap_model_bindings
from maistro.capabilities.model_chat import ModelChatEgress
from maistro.capabilities.providers import llm_gateway
from maistro.capabilities.providers.llm_gateway import (
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
)
from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
from maistro.graph.nodes.base import NodeContext
from maistro.policy.types import Decision, PolicyVerdict
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.types.config import ModelBindingConfig
from maistro_evolve.archive import CandidateArchive
from maistro_evolve.benchmarks import ifeval
from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.diversity import emergency_spawn
from maistro_evolve.harness import EvalHarness
from maistro_evolve.population import PopulationStore
from maistro_evolve.tournament import EloTournament

pytestmark = pytest.mark.contract("behavioral")


@pytest.fixture
async def composition(monkeypatch: pytest.MonkeyPatch):
    scope = InMemoryProjectScopeStore()
    root = await scope.create_root("ws-evolve")
    declaration = ModelBindingConfig(binding_id="evolve-model", project_id=root.project_id)
    config = SimpleNamespace(
        workspace_id="ws-evolve", model_bindings=[declaration], litellm_key="scoped-test-key"
    )
    tracker = InMemoryQuotaTracker()
    effects = new_in_memory_effect_context(
        policy_evaluator=binding_scope_policy,
        usage_log=InMemoryUsageLog(),
        quota_tracker=tracker,
    )
    await bootstrap_model_bindings(config, effects)
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="test-model",
                provider="test-provider",
                cost_per_1k_input=0.5,
                cost_per_1k_output=1.0,
                latency_p50_ms=1,
            )
        ]
    )
    egress = ModelChatEgress(
        effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gateway", api_key="unused-unscoped-key"),
    )
    runs = InMemoryRunStore(project_store=scope)
    owner = SimpleNamespace(
        config=config,
        capability_effects=effects,
        run_store=runs,
        project_scope_store=scope,
        graph_run_store=CanonicalDurableRunStore(runs, InMemoryGraphContinuationStore()),
    )
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(
            agent_port=SimpleNamespace(container=owner, governed_egress=egress)
        ),
    )
    monkeypatch.setattr("services.evolution._default_chat_model", lambda: "test-model")
    monkeypatch.setattr(
        ifeval,
        "IFEVAL_SAMPLES",
        [
            {
                "instruction": "Say accepted",
                "rules": [{"type": "exact_match", "value": "accepted"}],
            },
            {
                "instruction": "Say accepted again",
                "rules": [{"type": "exact_match", "value": "accepted"}],
            },
        ],
    )
    calls: list[dict[str, Any]] = []
    body: dict[str, Any] = {
        "model": "test-model-v2",
        "choices": [{"message": {"content": "accepted"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }

    class Response:
        status_code = 200

        def json(self):
            return body

    class Client:
        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return Response()

    @asynccontextmanager
    async def client(**kwargs):
        yield Client()

    monkeypatch.setattr(llm_gateway, "shared_client", client)
    population = PopulationStore()
    genome = emergency_spawn([], 1)[0]
    population.add(genome)
    tournament = EloTournament()
    archive = CandidateArchive()
    return SimpleNamespace(
        owner=owner,
        effects=effects,
        tracker=tracker,
        egress=egress,
        calls=calls,
        body=body,
        population=population,
        genome=genome,
        tournament=tournament,
        archive=archive,
        harness=EvalHarness(benchmark_fidelity="proxy"),
        config=EvolutionConfig(
            population_size=1,
            eval_batch_size=1,
            cull_pct=0,
            breed_pct=0,
            self_improve=False,
            target_benchmarks=["proxy_ifeval"],
        ),
    )


async def _run(comp, *, actor: str | None = "request-actor"):
    return await run_canonical_evolution_cycle(
        population=comp.population,
        tournament=comp.tournament,
        archive=comp.archive,
        config=comp.config,
        harness=comp.harness,
        llm_call=_EvolutionService().build_llm_call(),
        container=comp.owner,
        actor_principal_id=actor,
    )


async def _context(comp, record, node_id="evolve-evaluate-1"):
    nodes = await comp.owner.run_store.list_node_runs(record.run_id)
    node = next(item for item in nodes if item.node_id == node_id)
    attempts = await comp.owner.run_store.list_attempts(node.node_run_id)
    return NodeContext(
        run_id=record.run_id,
        dag_id=record.run.graph.graph_id,
        node_id=node.node_id,
        node_run_id=node.node_run_id,
        attempt_id=attempts[0].attempt_id,
        workspace_id=record.run.workspace_id,
        project_id=record.run.project_id,
        user_id=record.run.actor_principal_id,
    )


async def test_request_cycle_records_actual_identity_scope_usage_and_accepted_score(composition):
    comp = composition
    record = await _run(comp)
    assert record.run.status is RunStatus.COMPLETED
    ctx = await _context(comp, record)
    genome = comp.archive.get(comp.genome.id)
    assert comp.archive.latest_event(comp.genome.id) == "retired"
    assert genome.eval_scores == {"proxy_ifeval": 1.0}
    assert genome.harness_params["evaluation_runs"] == [
        {
            "run_id": ctx.run_id,
            "node_run_id": ctx.node_run_id,
            "attempt_id": ctx.attempt_id,
        }
    ]
    events = comp.effects.usage_log.events_for("test-model")
    assert len(events) == len(comp.calls) == 2
    invocations = [await comp.effects.invocation_store.get(event.invocation_id) for event in events]
    for invocation in invocations:
        assert invocation is not None
        assert invocation.run_id == ctx.run_id
        assert invocation.node_run_id == ctx.node_run_id
        assert invocation.attempt_id == ctx.attempt_id
        assert invocation.actor_id == "request-actor"
        assert invocation.workspace_id == ctx.workspace_id
        assert invocation.project_id == ctx.project_id != "agent-runtime"
        assert invocation.binding.binding_id == "evolve-model"
        assert invocation.usage.input_units == 12
        assert invocation.usage.output_units == 8
        assert invocation.usage.model_version == "test-model-v2"
        assert (
            await comp.owner.run_store.get_attempt(invocation.attempt_id)
        ).status is AttemptStatus.COMPLETED
    assert len({item.effect_key for item in invocations}) == 2
    assert (await comp.tracker.get_all_usage())[0]["total_tokens"] == 40
    assert comp.calls[0]["headers"]["Authorization"] == "Bearer scoped-test-key"
    assert comp.calls[0]["json"]["model"] == "test-model"


async def test_publication_replay_skips_paid_calls_and_retains_original_evidence(composition):
    comp = composition
    record = await _run(comp)
    ctx = await _context(comp, record)
    cycle = EvolutionCycle(harness=comp.harness, tournament=comp.tournament, archive=comp.archive)
    comp.population.add(comp.archive.get(comp.genome.id))
    output = await _evaluate_one(
        cycle,
        comp.population,
        comp.config,
        _EvolutionService().build_llm_call(),
        comp.genome.id,
        ctx,
    )
    assert output.evaluation_attempt_id == ctx.attempt_id
    assert output.benchmarks == {"proxy_ifeval": 1.0}
    assert len(comp.calls) == 2


async def test_context_sequence_replay_deduplicates_and_preserves_request_defaults(composition):
    comp = composition
    record = await _run(comp)
    ctx = await _context(comp, record)
    adapter = _EvolutionService().build_llm_call()
    for _ in range(2):
        with adapter.for_context(ctx) as llm:
            assert await llm("bare prompt") == "accepted"
            assert (
                await llm(
                    [{"role": "user", "content": "override"}],
                    model="test-model",
                    temperature=0.6,
                    max_tokens=99,
                )
                == "accepted"
            )
    assert len(comp.calls) == 4  # two benchmark samples + two distinct logical effects
    first, second = comp.calls[-2:]
    assert first["json"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "bare prompt"}],
        "temperature": 0.3,
        "max_tokens": 4096,
        "stream": False,
    }
    assert second["json"]["temperature"] == 0.6
    assert second["json"]["max_tokens"] == 99
    assert len(comp.effects.usage_log.events_for("test-model")) == 4


@pytest.mark.parametrize(
    "kind",
    ["missing", "wrong-project", "disabled", "revoked", "ambiguous", "denied", "no-credential"],
)
async def test_model_authority_failures_cannot_become_accepted_scores(composition, kind):
    comp = composition
    declarations = comp.owner.config.model_bindings
    if kind == "missing":
        declarations.clear()
    elif kind == "wrong-project":
        declarations[0] = declarations[0].model_copy(update={"project_id": "other-project"})
    elif kind == "ambiguous":
        declarations.append(declarations[0].model_copy(update={"binding_id": "other-binding"}))
    elif kind == "disabled":
        declaration = declarations[0].model_copy(
            update={"binding_id": "disabled", "disabled": True}
        )
        declarations[:] = [declaration]
        await bootstrap_model_bindings(comp.owner.config, comp.effects)
    elif kind == "revoked":
        await comp.effects.bindings.revoke("evolve-model")
    elif kind == "no-credential":
        pool = comp.effects.credentials.pool_for(
            workspace_id="ws-evolve",
            project_id=declarations[0].project_id,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
        )
        assert pool is not None
        assert pool.remove("litellm-gateway")
    else:

        async def deny(binding, request, context):
            return PolicyVerdict(Decision.DENY, reason="test denial")

        comp.effects.invocations._policy = deny
    record = await _run(comp)
    assert record.run.status is RunStatus.FAILED
    assert comp.calls == []
    assert comp.population.get(comp.genome.id).eval_scores == {}
    assert not comp.effects.usage_log.events_for("test-model")
    nodes = await comp.owner.run_store.list_node_runs(record.run_id)
    assert len(nodes) == 1
    assert nodes[0].result is None
    assert nodes[0].accepted_outcome.error == "RuntimeError: Evolve model effect failed"


@pytest.mark.parametrize(
    "body,diagnostic",
    [
        ({"choices": []}, "returned no choices"),
        ({"choices": [{"message": {"content": 42}}]}, "returned no content"),
    ],
)
async def test_malformed_completion_stops_dispatch_and_refuses_score(composition, body, diagnostic):
    comp = composition
    comp.body.clear()
    comp.body.update(body)
    record = await _run(comp)
    assert record.run.status is RunStatus.FAILED
    assert comp.population.get(comp.genome.id).eval_scores == {}
    assert len(comp.calls) == 1  # the second sample is fenced after the first failure
    ctx = await _context(comp, record)
    with (
        pytest.raises(RuntimeError, match=diagnostic),
        _EvolutionService().build_llm_call().for_context(ctx) as llm,
    ):
        await llm("direct malformed check")


@pytest.mark.parametrize(
    "field",
    ["run_id", "node_run_id", "attempt_id", "node_id", "workspace_id", "project_id", "user_id"],
)
async def test_incomplete_context_refuses_before_dispatch(composition, field):
    comp = composition
    record = await _run(comp)
    ctx = await _context(comp, record)
    invalid = ctx.model_copy(update={field: " "})
    with (
        pytest.raises(RunIntegrityError),
        _EvolutionService().build_llm_call().for_context(invalid),
    ):
        pytest.fail("an incomplete execution scope must not yield a model callable")
    assert len(comp.calls) == 2


async def test_missing_actor_cannot_enable_background_cycle(composition):
    """#1867 is retained: this repair must never mint or reuse a service actor."""
    with pytest.raises(ValueError, match="actor_principal_id is required"):
        await _run(composition, actor=None)
    assert composition.calls == []


async def test_finalize_uses_own_identity_and_committed_marker(composition):
    comp = composition
    record = await _run(comp)
    ctx = await _context(comp, record, "evolve-finalize")
    # An already committed finalize must return before evaluating or dispatching.
    cycle = EvolutionCycle(harness=comp.harness, tournament=comp.tournament, archive=comp.archive)
    output = await _finalize_cycle(
        cycle, comp.population, comp.config, _EvolutionService().build_llm_call(), ctx
    )
    assert output.population_size == 0
    assert len(comp.calls) == 2


@pytest.mark.parametrize("fail", [False, True])
async def test_finalize_paid_work_and_swallowed_failure_keep_publication_fence(composition, fail):
    comp = composition
    comp.config = comp.config.model_copy(
        update={
            "population_size": 2,
            "eval_batch_size": 0,
            "self_improve": True,
            "hyper_mutate": False,
            "node_attribution": False,
            "self_improve_candidates": 1,
            "retrodiction": "off",
        }
    )
    for index in range(2):
        genome = comp.genome.model_copy(deep=True)
        genome.id = f"scored-{index}"
        genome.fitness_score = 0.5
        genome.eval_scores = {"proxy_ifeval": 0.5}
        comp.population.add(genome)
    comp.population.remove(comp.genome.id)
    if fail:
        comp.owner.config.model_bindings.clear()
    record = await _run(comp)
    ctx = await _context(comp, record, "evolve-finalize")
    marker = comp.population.get_cycle_marker(f"finalize:{ctx.node_run_id}")
    if fail:
        assert record.run.status is RunStatus.FAILED
        assert marker == {"status": "faulted"}
        assert comp.calls == []
        with pytest.raises(FinalizeReconciliationRequired):
            await _finalize_cycle(
                EvolutionCycle(harness=comp.harness, tournament=comp.tournament),
                comp.population,
                comp.config,
                _EvolutionService().build_llm_call(),
                ctx,
            )
        assert comp.calls == []
    else:
        assert record.run.status is RunStatus.COMPLETED
        assert marker["status"] == "committed"
        events = comp.effects.usage_log.events_for("test-model")
        assert len(events) == len(comp.calls) >= 3
        for event in events:
            invocation = await comp.effects.invocation_store.get(event.invocation_id)
            assert invocation.run_id == ctx.run_id
            assert invocation.node_run_id == ctx.node_run_id
            assert invocation.attempt_id == ctx.attempt_id
            assert invocation.actor_id == "request-actor"


async def test_scoped_callable_expires_and_swallowed_cancellation_is_fenced(
    composition, monkeypatch
):
    from services.evolution_graph import _model_call_context

    comp = composition
    record = await _run(comp)
    ctx = await _context(comp, record)
    adapter = _EvolutionService().build_llm_call()
    with (
        pytest.raises(ValueError, match="requires a canonical NodeContext"),
        _model_call_context(adapter, None),
    ):
        pytest.fail("a governed adapter must never bind without a NodeContext")
    with adapter.for_context(ctx) as llm:
        pass
    with pytest.raises(RunIntegrityError, match="outlived"):
        await llm("too late")

    async def cancel(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(comp.egress, "complete", cancel)
    with (
        pytest.raises(RuntimeError, match="Evolve model effect failed"),
        adapter.for_context(ctx) as llm,
        pytest.raises(asyncio.CancelledError),
    ):
        await llm("cancelled call")
    assert len(comp.calls) == 2


async def test_exact_node_binding_wins_without_widening_generic_authority(composition):
    comp = composition
    generic = comp.owner.config.model_bindings[0]
    comp.owner.config.model_bindings.append(
        generic.model_copy(
            update={
                "binding_id": "exact-evaluation",
                "node_id": "evolve-evaluate-1",
                "provider_name": "test-model",
            }
        )
    )
    await bootstrap_model_bindings(comp.owner.config, comp.effects)
    record = await _run(comp)
    assert record.run.status is RunStatus.COMPLETED
    for event in comp.effects.usage_log.events_for("test-model"):
        invocation = await comp.effects.invocation_store.get(event.invocation_id)
        assert invocation.binding.binding_id == "exact-evaluation"
        assert invocation.binding.node_id == "evolve-evaluate-1"


async def _admit_evaluation_attempt(comp):
    """Allocate real execution identities before simulating a lost worker."""
    from datetime import timedelta

    from services.evolution_graph import _build_graph

    project = await comp.owner.project_scope_store.root_for_workspace("ws-evolve")
    graph = _build_graph(
        workspace_id="ws-evolve",
        project_id=project.project_id,
        population=comp.population,
        config=comp.config,
    )
    store = comp.owner.run_store
    run = await store.create_run(
        graph, actor_principal_id="request-actor", initial_status=RunStatus.QUEUED
    )
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node = await store.create_node_run(run.run_id, node_id="evolve-evaluate-1")
    await store.transition_node_run(node.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(
        node.node_run_id, lease_holder="first-worker", lease_ttl=timedelta(minutes=1)
    )
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    ctx = NodeContext(
        run_id=run.run_id,
        dag_id=graph.graph_id,
        node_id=node.node_id,
        node_run_id=node.node_run_id,
        attempt_id=attempt.attempt_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.actor_principal_id,
    )
    return ctx, attempt


async def _reclaim_evaluation_attempt(comp, ctx, attempt):
    """Canonical lease recovery keeps the NodeRun and allocates a new Attempt."""
    from datetime import timedelta

    store = comp.owner.run_store
    reclaimed = await store.reclaim_expired_attempts(
        now=attempt.execution_lease.expires_at + timedelta(seconds=1)
    )
    assert [item.attempt_id for item in reclaimed] == [attempt.attempt_id]
    recovered = await store.create_attempt(ctx.node_run_id, lease_holder="recovery-worker")
    await store.transition_attempt(
        recovered.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=recovered.execution_lease.fencing_token,
    )
    assert recovered.attempt_id != ctx.attempt_id
    assert recovered.ordinal == attempt.ordinal + 1
    return ctx.model_copy(update={"attempt_id": recovered.attempt_id}), recovered


async def test_recovery_attempt_replays_paid_evaluation_before_domain_publication(
    composition, monkeypatch
):
    from maistro.runs.model import AcceptedNodeOutcome, AttemptResult

    comp = composition
    ctx, first = await _admit_evaluation_attempt(comp)
    cycle = EvolutionCycle(harness=comp.harness, tournament=comp.tournament, archive=comp.archive)

    class ProcessLostBeforePublication(BaseException):
        pass

    def lose_process(genome):
        raise ProcessLostBeforePublication()

    # Complete and account for both real benchmark calls, then lose the worker
    # before its staged score/evidence enters the population.
    with monkeypatch.context() as patch:
        patch.setattr(comp.population, "add", lose_process)
        with pytest.raises(ProcessLostBeforePublication):
            await _evaluate_one(
                cycle,
                comp.population,
                comp.config,
                _EvolutionService().build_llm_call(),
                comp.genome.id,
                ctx,
            )
    assert len(comp.calls) == 2
    assert comp.population.get(comp.genome.id).eval_scores == {}
    assert not comp.population.get(comp.genome.id).harness_params.get("evaluation_runs")

    recovered_ctx, recovered = await _reclaim_evaluation_attempt(comp, ctx, first)
    output = await _evaluate_one(
        cycle,
        comp.population,
        comp.config,
        _EvolutionService().build_llm_call(),
        comp.genome.id,
        recovered_ctx,
    )
    assert output.benchmarks == {"proxy_ifeval": 1.0}
    assert output.evaluation_attempt_id == recovered.attempt_id
    assert len(comp.calls) == 2
    events = comp.effects.usage_log.events_for("test-model")
    assert len(events) == 2
    assert (await comp.tracker.get_all_usage())[0]["total_tokens"] == 40
    for event in events:
        invocation = await comp.effects.invocation_store.get(event.invocation_id)
        assert invocation.run_id == ctx.run_id
        assert invocation.node_run_id == ctx.node_run_id
        assert invocation.attempt_id == first.attempt_id
    assert comp.population.get(comp.genome.id).harness_params["evaluation_runs"] == [
        {
            "run_id": recovered_ctx.run_id,
            "node_run_id": recovered_ctx.node_run_id,
            "attempt_id": recovered_ctx.attempt_id,
        }
    ]
    completed = await comp.owner.run_store.transition_attempt(
        recovered.attempt_id,
        AttemptStatus.COMPLETED,
        result=output.model_dump(),
        fencing_token=recovered.execution_lease.fencing_token,
    )
    accepted = await comp.owner.run_store.transition_node_run(
        ctx.node_run_id,
        RunStatus.COMPLETED,
        result=output.model_dump(),
        accepted_outcome=AcceptedNodeOutcome(
            node_run_id=ctx.node_run_id,
            attempt_result=AttemptResult.from_attempt(completed),
        ),
    )
    assert accepted.accepted_outcome.attempt_result.attempt_id == recovered.attempt_id


async def test_recovery_attempt_refuses_unknown_effect_without_redispatch_or_score(
    composition, monkeypatch
):
    from datetime import UTC, datetime

    from maistro.capabilities.invocation import InvocationStatus

    comp = composition
    ctx, first = await _admit_evaluation_attempt(comp)
    cycle = EvolutionCycle(harness=comp.harness, tournament=comp.tournament, archive=comp.archive)

    class AmbiguousClient:
        async def post(self, url, **kwargs):
            comp.calls.append({"url": url, **kwargs})
            raise TimeoutError("gateway response lost after dispatch")

    @asynccontextmanager
    async def ambiguous_client(**kwargs):
        yield AmbiguousClient()

    monkeypatch.setattr(llm_gateway, "shared_client", ambiguous_client)
    with pytest.raises(RuntimeError, match="Evolve model effect failed"):
        await _evaluate_one(
            cycle,
            comp.population,
            comp.config,
            _EvolutionService().build_llm_call(),
            comp.genome.id,
            ctx,
        )
    assert len(comp.calls) == 1
    first_effects = await comp.effects.invocation_store.list_ambiguous(
        stale_before=datetime.now(UTC)
    )
    assert len(first_effects) == 1
    assert first_effects[0].status is InvocationStatus.UNKNOWN

    recovered_ctx, recovered = await _reclaim_evaluation_attempt(comp, ctx, first)
    with pytest.raises(RuntimeError, match="Evolve model effect failed"):
        await _evaluate_one(
            cycle,
            comp.population,
            comp.config,
            _EvolutionService().build_llm_call(),
            comp.genome.id,
            recovered_ctx,
        )
    assert len(comp.calls) == 1
    history = await comp.effects.invocation_store.list_effect(
        run_id=ctx.run_id,
        node_run_id=ctx.node_run_id,
        binding_id=first_effects[0].binding.binding_id,
        effect_key=first_effects[0].effect_key,
    )
    assert len(history) == 1
    assert history[0].attempt_id == first.attempt_id != recovered.attempt_id
    persisted = await comp.effects.invocation_store.get(first_effects[0].invocation_id)
    assert persisted.status is InvocationStatus.UNKNOWN
    assert comp.population.get(comp.genome.id).eval_scores == {}
    assert not comp.population.get(comp.genome.id).harness_params.get("evaluation_runs")
    assert not comp.effects.usage_log.events_for("test-model")
    node = await comp.owner.run_store.get_node_run(ctx.node_run_id)
    assert node.result is None
    assert node.accepted_outcome is None


async def test_manual_trigger_route_uses_request_actor_and_real_governed_dispatch(
    composition, monkeypatch
):
    from routes.evolution import trigger_cycle

    comp = composition
    monkeypatch.setattr("maistro_evolve.cycle.EvolutionConfig", lambda **kwargs: comp.config)
    service = _EvolutionService()
    service._population = comp.population
    service._tournament = comp.tournament
    service._archive = comp.archive
    monkeypatch.setattr("services.evolution.get_evolution_service", lambda: service)
    response = await trigger_cycle(SimpleNamespace(state=SimpleNamespace(user_id="route-actor")))
    assert response["status"] == "completed"
    assert response["run_id"] == service.last_run_id
    run = await comp.owner.run_store.get_run(service.last_run_id)
    assert run.actor_principal_id == "route-actor"
    for event in comp.effects.usage_log.events_for("test-model"):
        invocation = await comp.effects.invocation_store.get(event.invocation_id)
        assert invocation.actor_id == "route-actor"
        assert invocation.run_id == run.run_id
    assert len(comp.calls) == 2


async def test_canonical_quota_denial_stops_gateway_and_score(composition, tmp_path):
    from maistro.quota.invocation_quota import QuotaBudget, QuotaEstimate
    from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota

    comp = composition
    estimated_actors = []

    async def estimate(invocation, binding):
        estimated_actors.append(invocation.actor_id)
        return QuotaEstimate(principal_id=invocation.actor_id, tokens=4096)

    quota = SqliteInvocationQuota(tmp_path / "budget.sqlite", estimate=estimate, clock=lambda: 100)
    await quota.ensure_schema()
    await quota.register_budget(
        QuotaBudget(
            budget_id="exhausted",
            unit="requests",
            limit=0,
            period_start=0,
            period_end=1000,
            coverage_ref="test-known-zero",
            opening_spend=0,
            provider_name="test-model",
            workspace_id="ws-evolve",
            principal_id="request-actor",
        )
    )
    # The same InvocationExecutionService constructor dependency the container
    # supplies, using a real durable quota door rather than a denying stub.
    comp.effects.invocations._invocations._quota = quota
    record = await _run(comp)
    assert record.run.status is RunStatus.FAILED
    assert estimated_actors == ["request-actor"]
    assert comp.calls == []
    assert comp.population.get(comp.genome.id).eval_scores == {}
    assert not comp.effects.usage_log.events_for("test-model")
    balance = await quota.balance("exhausted")
    assert balance.spent == balance.held == 0
