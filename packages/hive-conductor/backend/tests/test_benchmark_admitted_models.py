"""Benchmark evaluator: SQLite admission and authority with final HTTP mocked."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from services import benchmark_eval
from services.engine import get_engine

from maistro.capabilities.invocation import InvocationStatus
from maistro.container import Container, create_container
from maistro.graph.definitions import Graph, Node
from maistro.http import set_test_transport
from maistro.quota.invocation_quota import QuotaBudget
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.types.config import AgentConfig

_WORKSPACE = "evaluation-workspace"
_ACTOR = "evaluation-actor"
_BINDING = "evaluation-binding"
_MODEL = "configured-model"


def _rubric(total: float = 42) -> dict[str, Any]:
    return {
        **{
            name: {"score": total / 5, "evidence": "specific evidence", "fix": "specific fix"}
            for name in ("correctness", "completeness", "test_coverage", "style", "security")
        },
        "total": total,
        "pass": total >= 35,
        "summary": "review summary",
        "suggested_prompt_improvement": "better prompt",
    }


@dataclass
class Setup:
    container: Container
    path: Path
    project_id: str
    requests: list[httpx.Request] = field(default_factory=list)
    body: dict[str, Any] = field(
        default_factory=lambda: {
            "model": "response-version",
            "choices": [{"message": {"content": json.dumps(_rubric())}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
    )
    fail_transport: bool = False

    def grants(self) -> list[tuple[Any, ...]]:
        with sqlite3.connect(self.path) as db:
            return db.execute(
                "SELECT binding_id, payload_json FROM capability_bindings ORDER BY binding_id"
            ).fetchall()


@pytest.fixture
async def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Setup]:
    options = getattr(request, "param", {})
    providers = tmp_path / "providers.yaml"
    providers.write_text(
        f"models:\n  - name: {_MODEL}\n    provider: openai\n"
        "    cost_input: 1.0\n    cost_output: 2.0\n    latency_p50_ms: 1\n"
    )
    path = tmp_path / "runtime.sqlite3"
    database_url = f"sqlite:///{path}"
    initial = await create_container(
        AgentConfig(database_url=database_url, router_api_key="test-router-key")
    )
    await initial.workspace_store.create(
        name="DAG models", creator_user_id=_ACTOR, workspace_id=_WORKSPACE
    )
    project = await initial.project_scope_store.root_for_workspace(_WORKSPACE)
    await initial.aclose()
    bindings = [
        {
            "binding_id": options.get("binding_id", _BINDING),
            "project_id": project.project_id,
            "node_id": "benchmark-evaluation",
            "provider_name": options.get("pin", _MODEL),
        },
        {"binding_id": "foreign-project", "project_id": "foreign", "provider_name": _MODEL},
        {"binding_id": "foreign-node", "project_id": project.project_id, "node_id": "other"},
    ]
    if options.get("ambiguous"):
        bindings.append(
            {
                "binding_id": "second",
                "project_id": project.project_id,
                "node_id": "benchmark-evaluation",
            }
        )
    if options.get("unconfigured"):
        bindings = []
    owner = await create_container(
        AgentConfig(
            router_api_key="test-router-key",
            database_url=database_url,
            workspace_id=_WORKSPACE,
            provider_config_path=str(providers),
            litellm_url="https://configured.gateway.test",
            litellm_key="" if options.get("missing_key") else "scoped-test-key",
            model_bindings=bindings,
        )
    )
    # Only install the selected Container, just as the embedded bridge does.
    monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=owner))
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://ambient.must-not-win.test")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "ambient-key-must-not-be-borrowed")
    monkeypatch.setenv("LITELLM_API_BASE", "https://raw.must-not-run.test")
    monkeypatch.setenv("LITELLM_API_KEY", "raw-key-must-not-be-borrowed")
    state = Setup(owner, path, project.project_id)

    def transport(http_request: httpx.Request) -> httpx.Response:
        state.requests.append(http_request)
        if state.fail_transport:
            raise httpx.ReadTimeout("provider completion unknown", request=http_request)
        return httpx.Response(200, json=state.body)

    published_effects = owner.capability_effects
    set_test_transport(httpx.MockTransport(transport))
    try:
        yield state
    finally:
        set_test_transport(None)
        # Policy-refusal cases temporarily narrow this field. Container close
        # must withdraw the exact context it published, not the test replacement.
        owner.capability_effects = published_effects
        await owner.aclose()


async def _parent(s: Setup, actor: str = _ACTOR) -> str:
    run = await s.container.run_store.create_run(
        Graph(
            workspace_id=_WORKSPACE,
            project_id=s.project_id,
            name="evaluated",
            nodes=[Node(node_id="worker", node_type="worker")],
        ),
        actor_principal_id=actor,
        initial_status=RunStatus.QUEUED,
    )
    await s.container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    await s.container.run_store.transition_run(run.run_id, RunStatus.COMPLETED)
    return run.run_id


async def _evaluate(s: Setup, **kwargs: Any) -> dict[str, Any]:
    run_id = kwargs.pop("run_id", None) or await _parent(s)
    return await benchmark_eval.evaluate_code_output(
        "task",
        "plan",
        "code",
        run_id=run_id,
        workspace_id=kwargs.pop("workspace_id", _WORKSPACE),
        project_id=kwargs.pop("project_id", s.project_id),
        model="request-alias",
        **kwargs,
    )


async def _evidence(s: Setup, run_id: str) -> tuple[Any, Any, list[Any]]:
    nodes = await s.container.run_store.list_node_runs(run_id)
    assert len(nodes) == 1
    attempts = await s.container.run_store.list_attempts(nodes[0].node_run_id)
    assert len(attempts) == 1
    invocations = await s.container.invocation_store.list_effect(
        run_id=run_id,
        node_run_id=nodes[0].node_run_id,
        binding_id=_BINDING,
        effect_key="benchmark.evaluation:judge",
    )
    return nodes[0], attempts[0], invocations


async def test_evaluation_uses_configured_binding_leased_execution_and_actor(setup: Setup) -> None:
    before = setup.grants()
    parent = await _parent(setup)
    result = await _evaluate(setup, run_id=parent)
    assert result["total"] == 42, result
    node, attempt, invocations = await _evidence(setup, result["evaluation_run_id"])
    run = await setup.container.run_store.get_run(result["evaluation_run_id"])
    assert run.status is node.status is RunStatus.COMPLETED
    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.execution_lease is not None
    assert node.accepted_outcome.attempt_result.attempt_id == attempt.attempt_id
    assert run.parent_run_id == parent
    assert run.actor_principal_id == invocations[0].actor_id == _ACTOR
    assert node.node_id == invocations[0].binding.node_id == "benchmark-evaluation"
    assert len(invocations) == len(setup.requests) == 1
    invocation = invocations[0]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.usage.model == _MODEL
    assert invocation.usage.cost_cents == 2.0
    events = [
        e
        for e in setup.container.usage_log.events_for(_MODEL)
        if e.invocation_id == invocation.invocation_id
    ]
    assert len(events) == 1
    request = setup.requests[0]
    assert str(request.url) == "https://configured.gateway.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer scoped-test-key"
    assert json.loads(request.content)["model"] == _MODEL
    assert setup.grants() == before


async def test_zero_actor_budget_refuses_without_grant_or_http(setup: Setup) -> None:
    await setup.container.capability_effects.quota.register_budget(
        QuotaBudget(
            budget_id="actor-budget",
            unit="requests",
            limit=0,
            period_start=0,
            period_end=2**62,
            coverage_ref="test-opening",
            opening_spend=0,
            workspace_id=_WORKSPACE,
            principal_id=_ACTOR,
            capability="model.chat",
        )
    )
    before = setup.grants()
    with pytest.raises(PermissionError):
        await _evaluate(setup)
    assert setup.requests == []
    assert setup.grants() == before
    failed = await setup.container.run_store.list_by_status(RunStatus.FAILED, limit=10)
    assert len(failed) == 1
    node, attempt, _invocations = await _evidence(setup, failed[0].run_id)
    assert node.status is RunStatus.FAILED
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.result["error_kind"] == "authorization"


@pytest.mark.parametrize(
    "setup", [{"ambiguous": True}, {"unconfigured": True}, {"missing_key": True}], indirect=True
)
async def test_unconfigured_authority_cannot_borrow_ambient_credentials(setup: Setup) -> None:
    before = setup.grants()
    credentials = setup.container.capability_effects.credentials
    stats = credentials.stats(
        workspace_id=_WORKSPACE, project_id=setup.project_id, provider="litellm"
    )
    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await _evaluate(setup)
    assert setup.requests == []
    assert setup.grants() == before
    assert (
        credentials.stats(workspace_id=_WORKSPACE, project_id=setup.project_id, provider="litellm")
        == stats
    )


@pytest.mark.parametrize(
    "refusal", ["revoked", "disabled", "node", "project", "policy", "approval"]
)
async def test_grant_and_policy_refusals_fail_closed(setup: Setup, refusal: str) -> None:
    from maistro.policy.types import Decision, PolicyVerdict

    effects = setup.container.capability_effects
    binding = await effects.bindings.get(_BINDING)
    if refusal == "revoked":
        await effects.bindings.revoke(_BINDING)
    elif refusal in ("policy", "approval"):

        async def deny(*args: Any) -> PolicyVerdict:
            return PolicyVerdict(
                Decision.DENY if refusal == "policy" else Decision.REQUIRE_APPROVAL,
                reason="test refusal",
                rule="test",
            )

        setup.container.capability_effects = effects.with_policy_evaluator(deny)
    else:
        updates = (
            {"disabled": True}
            if refusal == "disabled"
            else {"node_id" if refusal == "node" else "project_id": "foreign"}
        )
        # Exercise persisted operator configuration, not consumer grants.
        with sqlite3.connect(setup.path) as db:
            changed = binding.model_copy(update=updates)
            db.execute(
                "UPDATE capability_bindings SET payload_json=? WHERE binding_id=?",
                (changed.model_dump_json(), _BINDING),
            )
    before = setup.grants()
    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await _evaluate(setup)
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize(
    "invalid", ["missing-parent", "workspace", "project", "missing-actor", "missing-runtime"]
)
async def test_parent_scope_and_actor_refuse_without_children_or_http(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    parent = await _parent(setup)
    kwargs: dict[str, Any] = {"run_id": parent}
    if invalid == "missing-parent":
        kwargs["run_id"] = "missing"
    elif invalid == "workspace":
        kwargs["workspace_id"] = "foreign"
    elif invalid == "project":
        kwargs["project_id"] = "foreign"
    elif invalid == "missing-runtime":
        monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace())
    else:
        original = setup.container.run_store.get_run

        async def without_actor(run_id: str) -> Any:
            record = await original(run_id)
            return record.model_copy(update={"actor_principal_id": ""})

        monkeypatch.setattr(setup.container.run_store, "get_run", without_actor)
    before = setup.grants()
    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await _evaluate(setup, **kwargs)
    with sqlite3.connect(setup.path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM canonical_runs WHERE parent_run_id=?", (parent,)
            ).fetchone()[0]
            == 0
        )
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize(
    "rubric",
    [
        "not JSON",
        pytest.param("[" * 10000 + "0" + "]" * 10000, id="too-deep"),
        "[]",
        "{}",
        '{"total":true,"pass":false}',
        '{"total":51,"pass":true}',
        '{"total":-1,"pass":false}',
        '{"total":NaN,"pass":false}',
        '{"total":42,"pass":false}',
        '{"total":42,"pass":"true"}',
        '{"total":42,"pass":true,"error":"bad"}',
    ],
)
async def test_invalid_rubric_fails_operation_but_keeps_completed_usage(
    setup: Setup, rubric: str
) -> None:
    setup.body["choices"][0]["message"]["content"] = rubric
    with pytest.raises(benchmark_eval.BenchmarkEvaluationError) as caught:
        await _evaluate(setup)
    evidence = caught.value.attempt_evidence
    node, attempt, invocations = await _evidence(setup, evidence["evaluation_run_id"])
    run = await setup.container.run_store.get_run(node.run_id)
    assert run.status is node.status is RunStatus.FAILED
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.execution_lease is not None
    assert attempt.result == evidence
    assert node.accepted_outcome is None
    assert invocations[0].status is InvocationStatus.COMPLETED
    assert invocations[0].invocation_id == evidence["invocation_id"]
    assert len(setup.requests) == 1
    assert len(setup.container.usage_log.events_for(_MODEL)) == 1


@pytest.mark.parametrize("choices", [None, [], [None], [{"message": {}}]])
async def test_malformed_provider_response_is_not_a_zero_score(setup: Setup, choices: Any) -> None:
    setup.body["choices"] = choices
    with pytest.raises(benchmark_eval.BenchmarkEvaluationError):
        await _evaluate(setup)
    assert len(setup.requests) == 1


async def test_actor_one_request_quota_charges_once_then_refuses(setup: Setup) -> None:
    quota = setup.container.capability_effects.quota
    await quota.register_budget(
        QuotaBudget(
            budget_id="one-call",
            unit="requests",
            limit=1,
            period_start=0,
            period_end=2**62,
            coverage_ref="test",
            opening_spend=0,
            workspace_id=_WORKSPACE,
            principal_id=_ACTOR,
            capability="model.chat",
        )
    )
    result = await _evaluate(setup)
    assert result["total"] == 42
    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await _evaluate(setup)
    assert len(setup.requests) == 1
    balance = await quota.balance("one-call")
    assert balance.spent == 1
    assert balance.held == 0


@pytest.mark.parametrize("setup", [{"pin": "unknown"}, {}], indirect=True)
async def test_unavailable_pinned_model_cannot_fallback(setup: Setup) -> None:
    from maistro.providers.types import ModelMetadata

    setup.container.provider_registry.mark_unavailable(_MODEL)
    setup.container.provider_registry.register_model(
        ModelMetadata(
            name="alternative",
            provider="test",
            cost_per_1k_input=0,
            cost_per_1k_output=0,
            latency_p50_ms=1,
        )
    )
    with pytest.raises(benchmark_eval.BenchmarkEvaluationError, match="pinned model"):
        await _evaluate(setup)
    assert setup.requests == []


async def test_foreign_live_scope_refuses_before_http(setup: Setup) -> None:
    from maistro.observability.correlation import bind_execution_context

    with (
        bind_execution_context(workspace_id="foreign", project_id=setup.project_id),
        pytest.raises(benchmark_eval.BenchmarkAuthorizationError, match="scope"),
    ):
        await _evaluate(setup)
    assert setup.requests == []


@pytest.mark.parametrize("unknown", [False, True])
async def test_same_live_effect_replays_or_refuses_unknown_without_double_usage(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, unknown: bool
) -> None:
    from maistro.capabilities.invocation import UnsafeEffectRetry

    runtime = benchmark_eval._runtime()
    complete = runtime.calls.complete
    setup.fail_transport = unknown

    async def repeated(**kwargs: Any) -> Any:
        if unknown:
            with pytest.raises(httpx.ReadTimeout):
                await complete(**kwargs)
            with pytest.raises(UnsafeEffectRetry):
                await complete(**kwargs)
            raise RuntimeError("unknown effect refused")
        first = await complete(**kwargs)
        second = await complete(**kwargs)
        assert first.invocation_id == second.invocation_id
        return second

    monkeypatch.setattr(runtime.calls, "complete", repeated)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)
    if unknown:
        with pytest.raises(benchmark_eval.BenchmarkEvaluationError, match="unknown"):
            await _evaluate(setup)
    else:
        await _evaluate(setup)
    assert len(setup.requests) == 1
    assert len(setup.container.usage_log.events_for(_MODEL)) == (0 if unknown else 1)


async def test_cancellation_settles_leased_spine_without_fabricating_usage(setup: Setup) -> None:
    import asyncio

    started = asyncio.Event()

    async def blocked(request: httpx.Request) -> httpx.Response:
        setup.requests.append(request)
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled transport resumed")

    set_test_transport(httpx.MockTransport(blocked))
    parent = await _parent(setup)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(started.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cancelled = await setup.container.run_store.list_by_status(RunStatus.CANCELLED, limit=10)
    assert len(cancelled) == 1
    node, attempt, invocations = await _evidence(setup, cancelled[0].run_id)
    assert node.status is RunStatus.CANCELLED
    assert attempt.status is AttemptStatus.CANCELLED
    assert attempt.execution_lease is not None
    assert invocations[0].status is InvocationStatus.UNKNOWN
    assert len(setup.requests) == 1
    assert not setup.container.usage_log.events_for(_MODEL)


@pytest.mark.parametrize("invalid", ["unleased", "expired", "missing", "foreign", "terminal"])
async def test_live_admission_cannot_bypass_persisted_lease_or_ancestry(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    from datetime import UTC, datetime, timedelta

    from maistro.observability.correlation import current_execution_context

    runtime = benchmark_eval._runtime()
    complete = runtime.calls.complete
    get_attempt = runtime.runs.get_attempt

    async def corrupted_read(attempt_id: str) -> Any:
        attempt = await get_attempt(attempt_id)
        if invalid == "missing":
            return None
        if invalid == "unleased":
            return attempt.model_copy(update={"execution_lease": None})
        if invalid == "expired":
            lease = attempt.execution_lease.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
            return attempt.model_copy(update={"execution_lease": lease})
        if invalid == "foreign":
            return attempt.model_copy(update={"node_run_id": "other-node"})
        return attempt.model_copy(update={"status": AttemptStatus.COMPLETED})

    async def validate(**kwargs: Any) -> Any:
        context = current_execution_context()
        assert context.attempt_id
        with monkeypatch.context() as patch:
            patch.setattr(runtime.runs, "get_attempt", corrupted_read)
            return await complete(**kwargs)

    monkeypatch.setattr(runtime.calls, "complete", validate)
    monkeypatch.setattr(benchmark_eval, "_runtime", lambda: runtime)
    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await _evaluate(setup)
    assert setup.requests == []


async def test_parent_admission_race_remains_typed(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.runs.store import RunIntegrityError

    parent = await _parent(setup)

    async def refuse(*args: Any, **kwargs: Any) -> Any:
        raise RunIntegrityError("parent admission changed")

    monkeypatch.setattr(setup.container.run_store, "create_run", refuse)
    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError, match="admission changed"):
        await _evaluate(setup, run_id=parent)
    assert setup.requests == []


@pytest.mark.parametrize("total", [0, 34.5, 35, 50])
async def test_valid_score_boundaries_are_preserved(setup: Setup, total: float) -> None:
    setup.body["choices"][0]["message"]["content"] = json.dumps(_rubric(total))
    result = await _evaluate(setup)
    assert result["total"] == total
    assert result["pass"] == (total >= 35)


@pytest.mark.parametrize("outputs", [[], ["plan"], ["plan", "code"]])
async def test_dag_output_decomposition_preserves_available_text(
    setup: Setup, outputs: list[str]
) -> None:
    result = await benchmark_eval.evaluate_dag_run(
        {
            "run_id": await _parent(setup),
            "workspace_id": _WORKSPACE,
            "project_id": setup.project_id,
            "node_results": {
                str(i): {"success": True, "response": text} for i, text in enumerate(outputs)
            },
        },
        "task",
    )
    assert result["total"] == 42
    content = json.loads(setup.requests[0].content)["messages"][-1]["content"]
    assert (
        f"PLAN:\n{outputs[0] if outputs else ''}\n\nCODE:\n{outputs[1] if len(outputs) > 1 else ''}\n\nREVIEW:\n"
        in content
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-criterion",
        "criterion-type",
        "criterion-bool",
        "criterion-range",
        "criterion-nan",
        "evidence",
        "fix",
        "summary",
        "prompt",
        "total-bool",
        "total-range",
        "total-nan",
        "wrong-sum",
        "wrong-pass",
        "pass-type",
        "error",
    ],
)
async def test_complete_rubric_must_be_consistent_and_well_formed(
    setup: Setup, invalid: str
) -> None:
    rubric = _rubric()
    if invalid == "missing-criterion":
        del rubric["correctness"]
    elif invalid == "criterion-type":
        rubric["correctness"] = []
    elif invalid.startswith("criterion-"):
        rubric["correctness"]["score"] = {
            "criterion-bool": True,
            "criterion-range": 11,
            "criterion-nan": float("nan"),
        }[invalid]
    elif invalid in ("evidence", "fix"):
        rubric["security"][invalid] = " " if invalid == "fix" else None
    elif invalid in ("summary", "prompt"):
        rubric["summary" if invalid == "summary" else "suggested_prompt_improvement"] = ""
    elif invalid.startswith("total-"):
        rubric["total"] = {"total-bool": True, "total-range": 51, "total-nan": float("nan")}[
            invalid
        ]
    elif invalid == "wrong-sum":
        rubric["correctness"]["score"] = 0
    elif invalid in ("wrong-pass", "pass-type"):
        rubric["pass"] = False if invalid == "wrong-pass" else "true"
    else:
        rubric["error"] = "bad"
    setup.body["choices"][0]["message"]["content"] = json.dumps(rubric)
    with pytest.raises(benchmark_eval.BenchmarkEvaluationError, match="rubric"):
        await _evaluate(setup)
    assert len(setup.requests) == 1
    assert len(setup.container.usage_log.events_for(_MODEL)) == 1


@pytest.mark.parametrize("phase", ["before-attempt", "after-attempt", "node", "run"])
async def test_cancellation_drains_terminal_persistence_even_when_repeated(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    import asyncio

    reached = asyncio.Event()
    release = asyncio.Event()
    store = setup.container.run_store
    parent = await _parent(setup)
    transition_name = (
        "transition_attempt"
        if "attempt" in phase
        else f"transition_{phase}_run"
        if phase == "node"
        else "transition_run"
    )
    original = getattr(store, transition_name)

    async def delayed(identity: str, status: Any, **kwargs: Any) -> Any:
        completed = status in (AttemptStatus.COMPLETED, RunStatus.COMPLETED)
        if not completed:
            return await original(identity, status, **kwargs)
        result = None
        if phase == "after-attempt":
            result = await original(identity, status, **kwargs)
        reached.set()
        await release.wait()
        return result if result is not None else await original(identity, status, **kwargs)

    monkeypatch.setattr(store, transition_name, delayed)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(reached.wait(), timeout=10)
    task.cancel()
    # Wait for the canonical durable cancellation fence, not a timing estimate.
    for _ in range(1000):
        children = await store.list_by_status(RunStatus.CANCELLED, limit=10)
        if children:
            break
        await asyncio.sleep(0)
    assert len(children) == 1
    task.cancel()  # A repeated disconnect cannot abandon the terminal writer.
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    node, attempt, invocations = await _evidence(setup, children[0].run_id)
    assert node.status in (RunStatus.CANCELLED, RunStatus.COMPLETED)
    assert attempt.status is AttemptStatus.COMPLETED
    assert invocations[0].status is InvocationStatus.COMPLETED
    assert len(setup.requests) == 1
    assert len(setup.container.usage_log.events_for(_MODEL)) == 1


async def test_cancellation_wins_logical_failure_without_masking_typed_error(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = setup.container.run_store
    original = store.transition_node_run
    won = False

    async def raced(node_id: str, status: RunStatus, **kwargs: Any) -> Any:
        nonlocal won
        if status is RunStatus.RUNNING and not won:
            node = await store.get_node_run(node_id)
            if node.status is RunStatus.WAITING:
                won = True
                await store.transition_run(node.run_id, RunStatus.CANCELLED)
        return await original(node_id, status, **kwargs)

    monkeypatch.setattr(store, "transition_node_run", raced)
    setup.body["choices"][0]["message"]["content"] = "not JSON"
    with pytest.raises(benchmark_eval.BenchmarkEvaluationError) as caught:
        await _evaluate(setup)
    assert won
    node, attempt, invocations = await _evidence(
        setup, caught.value.attempt_evidence["evaluation_run_id"]
    )
    assert node.status is RunStatus.CANCELLED
    assert (await store.get_run(node.run_id)).status is RunStatus.CANCELLED
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.result["error_kind"] == "evaluation"
    assert invocations[0].status is InvocationStatus.COMPLETED


async def test_unstarted_engine_is_typed_authority_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import engine

    def unavailable() -> Any:
        raise RuntimeError("engine not initialized")

    monkeypatch.setattr(engine, "get_engine", unavailable)
    with pytest.raises(benchmark_eval.BenchmarkAuthorizationError):
        await benchmark_eval.evaluate_code_output(
            "task", "plan", "code", run_id="run", workspace_id="ws", project_id="project"
        )


async def test_cancellation_drains_admission_and_closes_child_without_dispatch(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    parent = await _parent(setup)
    reached = asyncio.Event()
    release = asyncio.Event()
    original = setup.container.run_store.create_run
    created = []

    async def delayed(*args: Any, **kwargs: Any) -> Any:
        run = await original(*args, **kwargs)
        created.append(run)
        reached.set()
        await release.wait()
        return run

    monkeypatch.setattr(setup.container.run_store, "create_run", delayed)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(reached.wait(), timeout=10)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    child = await setup.container.run_store.get_run(created[0].run_id)
    assert child.status is RunStatus.CANCELLED
    assert await setup.container.run_store.list_node_runs(child.run_id) == []
    assert setup.requests == []


async def test_failed_cancellation_fence_still_stops_live_provider_and_preserves_cancellation(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio

    started = asyncio.Event()
    stopped = asyncio.Event()

    async def blocked(request: httpx.Request) -> httpx.Response:
        setup.requests.append(request)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        raise AssertionError("cancelled Provider resumed")

    set_test_transport(httpx.MockTransport(blocked))
    parent = await _parent(setup)
    original = setup.container.run_store.transition_run

    async def unavailable(run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        if target is RunStatus.CANCELLED:
            raise OSError("cancellation store unavailable")
        return await original(run_id, target, **kwargs)

    monkeypatch.setattr(setup.container.run_store, "transition_run", unavailable)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(started.wait(), timeout=10)
    task.cancel()
    await asyncio.wait_for(stopped.wait(), timeout=10)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    running = await setup.container.run_store.list_by_status(RunStatus.RUNNING, limit=10)
    assert len(running) == 1  # Never invent durable cancellation during storage failure.
    node, attempt, invocations = await _evidence(setup, running[0].run_id)
    assert node.status is RunStatus.CANCELLED
    assert attempt.status is AttemptStatus.CANCELLED
    assert invocations[0].status is InvocationStatus.UNKNOWN
    assert "cancellation fence could not be persisted" in caplog.text
    assert "cancellation settlement refused" in caplog.text
    assert len(setup.requests) == 1


async def test_failed_admission_cleanup_preserves_cancellation_and_reports_unresolved_write(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio

    parent = await _parent(setup)
    reached = asyncio.Event()
    release = asyncio.Event()
    original_create = setup.container.run_store.create_run
    original_transition = setup.container.run_store.transition_run
    children = []

    async def delayed(*args: Any, **kwargs: Any) -> Any:
        child = await original_create(*args, **kwargs)
        children.append(child)
        reached.set()
        await release.wait()
        return child

    async def unavailable(run_id: str, target: RunStatus, **kwargs: Any) -> Any:
        if target is RunStatus.CANCELLED:
            raise OSError("admission cancellation unavailable")
        return await original_transition(run_id, target, **kwargs)

    monkeypatch.setattr(setup.container.run_store, "create_run", delayed)
    monkeypatch.setattr(setup.container.run_store, "transition_run", unavailable)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(reached.wait(), timeout=10)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    child = await setup.container.run_store.get_run(children[0].run_id)
    assert child.status is RunStatus.QUEUED
    assert child.run_id in caplog.text
    assert "cancellation cleanup remains unresolved" in caplog.text
    assert setup.requests == []


async def test_failed_prelaunch_fence_cannot_dispatch_after_cancellation(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import asyncio

    parent = await _parent(setup)
    reached = asyncio.Event()
    release = asyncio.Event()
    fence_failed = asyncio.Event()
    original_create = setup.container.run_store.create_attempt
    original_transition = setup.container.run_store.transition_run
    created = []

    async def delayed(*args: Any, **kwargs: Any) -> Any:
        attempt = await original_create(*args, **kwargs)
        created.append(attempt)
        reached.set()
        await release.wait()
        return attempt

    async def unavailable(run_id: str, status: RunStatus, **kwargs: Any) -> Any:
        if status is RunStatus.CANCELLED:
            fence_failed.set()
            raise OSError("private-store-secret-detail")
        return await original_transition(run_id, status, **kwargs)

    monkeypatch.setattr(setup.container.run_store, "create_attempt", delayed)
    monkeypatch.setattr(setup.container.run_store, "transition_run", unavailable)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(reached.wait(), timeout=10)
    task.cancel()
    await asyncio.wait_for(fence_failed.wait(), timeout=10)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    attempt = await setup.container.run_store.get_attempt(created[0].attempt_id)
    assert attempt.status is AttemptStatus.CANCELLED
    assert setup.requests == []
    assert "private-store-secret-detail" not in caplog.text
    assert "error_type=OSError" in caplog.text


async def test_cancellation_closes_persisted_attempt_before_owner_registration(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    parent = await _parent(setup)
    reached = asyncio.Event()
    release = asyncio.Event()
    original = setup.container.run_store.create_attempt
    admitted = []

    async def delayed(*args: Any, **kwargs: Any) -> Any:
        attempt = await original(*args, **kwargs)
        admitted.append(attempt)
        reached.set()
        await release.wait()
        return attempt

    monkeypatch.setattr(setup.container.run_store, "create_attempt", delayed)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(reached.wait(), timeout=10)
    task.cancel()
    for _ in range(1000):
        cancelled = await setup.container.run_store.list_by_status(RunStatus.CANCELLED, limit=10)
        if cancelled:
            break
        await asyncio.sleep(0)
    assert len(cancelled) == 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    attempt = await setup.container.run_store.get_attempt(admitted[0].attempt_id)
    assert attempt.status is AttemptStatus.CANCELLED
    node, stored, invocations = await _evidence(setup, cancelled[0].run_id)
    assert node.status is RunStatus.CANCELLED
    assert stored.attempt_id == attempt.attempt_id
    assert invocations == []
    assert setup.requests == []


async def test_failed_fence_before_runtime_registration_cannot_dispatch(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    parent = await _parent(setup)
    reached = asyncio.Event()
    release = asyncio.Event()
    fence_failed = asyncio.Event()
    original_execute = benchmark_eval.PythonExecutionRuntime.execute
    original_transition = setup.container.run_store.transition_run

    async def delayed(self: Any, *args: Any, **kwargs: Any) -> Any:
        reached.set()
        await release.wait()
        return await original_execute(self, *args, **kwargs)

    async def unavailable(run_id: str, status: RunStatus, **kwargs: Any) -> Any:
        if status is RunStatus.CANCELLED:
            fence_failed.set()
            raise OSError("unavailable")
        return await original_transition(run_id, status, **kwargs)

    monkeypatch.setattr(benchmark_eval.PythonExecutionRuntime, "execute", delayed)
    monkeypatch.setattr(setup.container.run_store, "transition_run", unavailable)
    task = asyncio.create_task(_evaluate(setup, run_id=parent))
    await asyncio.wait_for(reached.wait(), timeout=10)
    task.cancel()
    await asyncio.wait_for(fence_failed.wait(), timeout=10)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)
    assert setup.requests == []


@pytest.mark.parametrize("outcome", ["success", "malformed", "timeout"])
@pytest.mark.parametrize("cancel_closeout", [False, True])
async def test_reclaimed_execution_cannot_accept_or_retry_a_late_model_outcome(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, outcome: str, cancel_closeout: bool
) -> None:
    import asyncio
    from datetime import UTC, datetime, timedelta

    from maistro.capabilities.providers.llm_gateway import ModelChatRequest
    from maistro.runs.reconciliation import AttemptLifecycleReconciler
    from maistro.runs.store import RunIntegrityError

    store = setup.container.run_store
    original = store.create_attempt
    reclaimed = []
    reached = asyncio.Event()
    release = asyncio.Event()
    original_transition = store.transition_node_run

    async def delayed_closeout(node_id: str, status: RunStatus, **kwargs: Any) -> Any:
        node = await store.get_node_run(node_id)
        if cancel_closeout and status is RunStatus.RUNNING and node.status is RunStatus.WAITING:
            reached.set()
            await release.wait()
        return await original_transition(node_id, status, **kwargs)

    monkeypatch.setattr(store, "transition_node_run", delayed_closeout)

    async def leased(*args: Any, **kwargs: Any) -> Any:
        kwargs["lease_ttl"] = timedelta(seconds=60)
        return await original(*args, **kwargs)

    async def late(request: httpx.Request) -> httpx.Response:
        setup.requests.append(request)
        reclaimed.extend(
            await store.reclaim_expired_attempts(now=datetime.now(UTC) + timedelta(seconds=61))
        )
        assert len(reclaimed) == 1
        await AttemptLifecycleReconciler(store).reconcile(reclaimed[0])
        if outcome == "timeout":
            raise httpx.ReadTimeout("late response unknown", request=request)
        if outcome == "malformed":
            setup.body["choices"][0]["message"]["content"] = "not JSON"
        return httpx.Response(200, json=setup.body)

    monkeypatch.setattr(store, "create_attempt", leased)
    set_test_transport(httpx.MockTransport(late))
    task = asyncio.create_task(_evaluate(setup))
    if cancel_closeout:
        await asyncio.wait_for(reached.wait(), timeout=10)
        task.cancel()
        for _ in range(1000):
            cancelled = await store.list_by_status(RunStatus.CANCELLED, limit=10)
            if cancelled:
                break
            await asyncio.sleep(0)
        assert len(cancelled) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10)
    else:
        with pytest.raises(benchmark_eval.BenchmarkEvaluationError):
            await task
    node = await store.get_node_run(reclaimed[0].node_run_id)
    run = await store.get_run(node.run_id)
    _, physical, invocations = await _evidence(setup, run.run_id)
    assert physical.model_dump() == reclaimed[0].model_dump()
    assert physical.status is AttemptStatus.CANCELLED
    assert (
        node.status is run.status is (RunStatus.CANCELLED if cancel_closeout else RunStatus.FAILED)
    )
    assert invocations[0].status is (
        InvocationStatus.UNKNOWN if outcome == "timeout" else InvocationStatus.COMPLETED
    )
    assert len(setup.container.usage_log.events_for(_MODEL)) == (0 if outcome == "timeout" else 1)
    with pytest.raises(RunIntegrityError):
        await benchmark_eval._runtime().calls.complete(
            identity=(run.run_id, node.node_run_id, physical.attempt_id),
            request=ModelChatRequest(model=_MODEL, messages=[]),
            effect_key="benchmark.evaluation:judge",
        )
    assert len(setup.requests) == 1
