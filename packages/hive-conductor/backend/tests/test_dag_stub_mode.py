"""Explicit zero-effect dry-run mode must never replace configured model refusal."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from services import legacy_dag_node as adapter
from services.governed_model import dag_node_unconfigured

from maistro.capabilities.invocation import InvocationStatus
from maistro.graph.nodes.base import NodeContext
from maistro.observability.correlation import bind_execution_context
from maistro.policy.types import Decision, PolicyVerdict
from maistro.quota.invocation_quota import QuotaBudget
from maistro.runs.model import RunStatus

from .test_dag_admitted_models import (
    _ACTOR,
    _BINDING,
    _MODEL,
    _WORKSPACE,
    Setup,
    _call,
    _dag,
    _execute,
    _running_context,
)
from .test_dag_admitted_models import setup as setup

_GATEWAY_ALIASES = (
    "LITELLM_API_BASE",
    "LITELLM_PROXY_URL",
    "LITELLM_BASE_URL",
    "LITELLM_URL",
    "MAISTRO_LLM_BASE_URL",
    "litellm_api_base",
    "maistro_llm_base_url",
)


def _stub_settings(monkeypatch: pytest.MonkeyPatch, *, allowed: bool = True) -> Any:
    import config

    for name in _GATEWAY_ALIASES:
        monkeypatch.delenv(name, raising=False)
    settings = SimpleNamespace(
        allow_stub_llm=allowed,
        litellm_api_base=None,
        litellm_api_key=None,
        maistro_model_bindings=[],
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    assert adapter.stub_llm_allowed() is allowed
    return settings


def _no_invocations(s: Setup, run_id: str) -> None:
    with sqlite3.connect(s.path) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM capability_invocations WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("setup", [{"unconfigured": True}], indirect=True)
@pytest.mark.parametrize("allowed", [False, True])
async def test_no_gateway_requires_explicit_opt_in_and_records_no_model_effect(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    _stub_settings(monkeypatch, allowed=allowed)
    setup.container.config.litellm_url = ""
    assert dag_node_unconfigured(setup.container)
    before = setup.grants()
    dag = _dag("")
    dag["provenance"] = {"ordinary_model_dry_run": not allowed}
    result = await _execute(setup, dag)
    assert result["status"] == ("completed" if allowed else "failed"), result
    run = await setup.container.run_store.get_run(result["run_id"])
    assert run.provenance["ordinary_model_dry_run"] is allowed
    if allowed:
        payload = json.loads(result["node_results"]["model-node"]["response"])
        assert payload == {"response": "stub: no LLM configured", "done": True, "stub": True}
    else:
        assert "ALLOW_STUB_LLM" in result["error"]
    assert setup.requests == []
    assert setup.grants() == before
    _no_invocations(setup, result["run_id"])
    assert not setup.container.usage_log.events_for(_MODEL)


@pytest.mark.parametrize(
    "refusal", ["missing-binding", "revoked", "missing-runtime", "policy", "quota", "endpoint"]
)
async def test_stub_flag_cannot_replace_configured_real_authority_refusal(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    _stub_settings(monkeypatch)
    dag = _dag()
    dag["provenance"] = {"ordinary_model_dry_run": True}
    if refusal == "missing-binding":
        dag["nodes"][0]["model_binding_id"] = "missing"
    elif refusal == "revoked":
        await setup.container.capability_effects.bindings.revoke(_BINDING)
    elif refusal == "missing-runtime":
        monkeypatch.setattr(setup.container, "provider_registry", None)
    elif refusal == "policy":

        async def deny(*args: Any) -> PolicyVerdict:
            return PolicyVerdict(Decision.DENY, reason="test policy", rule="test")

        setup.container.capability_effects = (
            setup.container.capability_effects.with_policy_evaluator(deny)
        )
    elif refusal == "quota":
        await setup.container.capability_effects.quota.register_budget(
            QuotaBudget(
                budget_id="no-dry-run-escape",
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
    else:
        setup.container.config.litellm_url = ""
    before = setup.grants()
    assert not dag_node_unconfigured(setup.container)
    result = await _execute(setup, dag)
    assert result["status"] == "failed", result
    run = await setup.container.run_store.get_run(result["run_id"])
    assert run.provenance["ordinary_model_dry_run"] is False
    assert '"stub": true' not in result["error"]
    assert setup.requests == []
    assert setup.grants() == before
    assert not setup.container.usage_log.events_for(_MODEL)


@pytest.mark.parametrize(
    "setup", [{"missing_key": True}, {"unconfigured": True}, {"ambiguous": True}], indirect=True
)
async def test_stub_flag_cannot_replace_missing_scoped_credentials_or_grants(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_settings(monkeypatch)
    before = setup.grants()
    result = await _execute(setup, _dag(""))
    assert result["status"] == "failed", result
    assert setup.requests == []
    assert setup.grants() == before


@pytest.mark.parametrize("refusal", ["expired", "terminal", "missing", "foreign"])
async def test_stub_flag_cannot_replace_real_execution_identity_validation(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    _stub_settings(monkeypatch)
    ctx = await _running_context(setup)
    if refusal == "expired":
        import maistro.capabilities.admitted_model as admitted

        future = datetime.now(UTC) + timedelta(hours=1)

        class Clock:
            @staticmethod
            def now(tz: Any) -> datetime:
                return future

        monkeypatch.setattr(admitted, "datetime", Clock)
    elif refusal == "terminal":
        await setup.container.run_store.transition_run(ctx.run_id, RunStatus.CANCELLED)
    elif refusal == "missing":
        ctx = ctx.model_copy(update={"attempt_id": ""})
    else:
        other = await _running_context(setup)
        ctx = ctx.model_copy(update={"attempt_id": other.attempt_id})
    result = await _call(setup, ctx)
    assert result["success"] is False
    assert setup.requests == []
    _no_invocations(setup, ctx.run_id)


@pytest.mark.parametrize("setup", [{"unconfigured": True}], indirect=True)
@pytest.mark.parametrize("selector", ["requested-but-missing", False, 0, None, [], {}])
async def test_no_gateway_stub_cannot_hide_requested_or_malformed_binding(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, selector: Any
) -> None:
    _stub_settings(monkeypatch)
    setup.container.config.litellm_url = ""
    dag = _dag()
    dag["nodes"][0]["model_binding_id"] = selector
    before = setup.grants()
    result = await _execute(setup, dag)
    assert result["status"] == "failed", result
    assert setup.requests == []
    assert setup.grants() == before
    _no_invocations(setup, result["run_id"])


@pytest.mark.parametrize("setup", [{"unconfigured": True}], indirect=True)
@pytest.mark.parametrize("source", ["settings-endpoint", "settings-grant", "unavailable-settings"])
async def test_incomplete_composition_cannot_be_mistaken_for_no_gateway(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    import config

    settings = _stub_settings(monkeypatch)
    setup.container.config.litellm_url = ""
    if source == "settings-endpoint":
        settings.litellm_api_base = "http://configured.test"
    elif source == "settings-grant":
        settings.maistro_model_bindings = [{"binding_id": "configured"}]
    else:

        def unavailable() -> Any:
            raise RuntimeError("settings unavailable")

        monkeypatch.setattr(config, "get_settings", unavailable)
        # The compatibility tool runtime is separate; keep this assertion on
        # the ordinary no-configuration predicate before any caller executes.
        assert not dag_node_unconfigured(setup.container)
        return
    assert not dag_node_unconfigured(setup.container)
    result = await _execute(setup, _dag(""))
    assert result["status"] == "failed", result
    assert setup.requests == []
    _no_invocations(setup, result["run_id"])


@pytest.mark.parametrize("alias", _GATEWAY_ALIASES)
def test_settings_gateway_aliases_disable_dry_run(
    monkeypatch: pytest.MonkeyPatch, alias: str
) -> None:
    import config

    _stub_settings(monkeypatch)
    monkeypatch.setenv(alias, "http://configured.test")
    settings = config.Settings(_env_file=None, allow_stub_llm=True)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    assert not dag_node_unconfigured(None)


@pytest.mark.parametrize("identity", [("", "", ""), ("run", "node", "stale")])
async def test_labelled_stub_requires_matching_live_execution_context(
    monkeypatch: pytest.MonkeyPatch, identity: tuple[str, str, str]
) -> None:
    _stub_settings(monkeypatch)
    ctx = NodeContext(
        run_id=identity[0], dag_id="g", node_id="n", node_run_id=identity[1], attempt_id=identity[2]
    )
    results: dict[str, dict[str, Any]] = {}
    with bind_execution_context(run_id="run", node_run_id="node", attempt_id="current"):
        await adapter._run_llm_node(
            {"id": "n"},
            "n",
            {},
            results,
            "work",
            ctx=ctx,
            no_model_configuration=True,
        )
    assert results["n"]["success"] is False
    assert "live canonical execution context" in results["n"]["response"]


async def test_stub_flag_does_not_hide_transport_unknown(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_settings(monkeypatch)
    setup.fail_transport = True
    result = await _execute(setup)
    assert result["status"] == "failed", result
    assert len(setup.requests) == 1
    nodes = await setup.container.run_store.list_node_runs(result["run_id"])
    invocations = await setup.container.invocation_store.list_effect(
        run_id=result["run_id"],
        node_run_id=nodes[0].node_run_id,
        binding_id=_BINDING,
        effect_key="dag:model",
    )
    assert len(invocations) == 1
    assert invocations[0].status is InvocationStatus.UNKNOWN
    run = await setup.container.run_store.get_run(result["run_id"])
    assert run.provenance["ordinary_model_dry_run"] is False


async def test_recovery_cannot_turn_an_unknown_real_effect_into_stub_success(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services import canonical_dag_runner as runner

    _stub_settings(monkeypatch)
    dag = _dag("")  # The original real call may use unambiguous implicit selection.
    ctx = await _running_context(setup, dag=dag)
    setup.fail_transport = True
    first = await _call(setup, ctx)
    assert first["success"] is False
    assert len(setup.requests) == 1
    before = setup.grants()
    setup.container.config.litellm_url = ""
    setup.container.config.model_bindings.clear()
    assert dag_node_unconfigured(setup.container)
    run = await setup.container.run_store.get_run(ctx.run_id)
    node = runner._recovery_resolver(run)(ctx.node_id, run.graph.materialize())
    with (
        bind_execution_context(
            run_id=ctx.run_id, node_run_id=ctx.node_run_id, attempt_id=ctx.attempt_id
        ),
        pytest.raises(RuntimeError, match="requires an admitted model runtime"),
    ):
        await node._execute(node.input_schema(), ctx)
    assert len(setup.requests) == 1
    assert setup.grants() == before
    invocations = await setup.container.invocation_store.list_effect(
        run_id=ctx.run_id,
        node_run_id=ctx.node_run_id,
        binding_id=_BINDING,
        effect_key="dag:model",
    )
    assert len(invocations) == 1
    assert invocations[0].status is InvocationStatus.UNKNOWN


@pytest.mark.parametrize("changed_config", [False, True])
async def test_recovery_preserves_admitted_zero_effect_mode(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, changed_config: bool
) -> None:
    from services import canonical_dag_runner as runner

    _stub_settings(monkeypatch)
    saved_url = setup.container.config.litellm_url
    saved_bindings = list(setup.container.config.model_bindings)
    setup.container.config.litellm_url = ""
    setup.container.config.model_bindings.clear()
    ctx = await _running_context(setup, dag=_dag(""), provenance={"ordinary_model_dry_run": True})
    if changed_config:
        # Restoring real configured authority must not upgrade a no-effect Run.
        setup.container.config.litellm_url = saved_url
        setup.container.config.model_bindings.extend(saved_bindings)
    run = await setup.container.run_store.get_run(ctx.run_id)
    node = runner._recovery_resolver(run)(ctx.node_id, run.graph.materialize())
    with bind_execution_context(
        run_id=ctx.run_id, node_run_id=ctx.node_run_id, attempt_id=ctx.attempt_id
    ):
        if changed_config:
            with pytest.raises(RuntimeError, match="requires an admitted model runtime"):
                await node._execute(node.input_schema(), ctx)
        else:
            output = await node._execute(node.input_schema(), ctx)
            assert json.loads(output.response)["stub"] is True
    assert setup.requests == []
    _no_invocations(setup, ctx.run_id)


@pytest.mark.parametrize("setup", [{"unconfigured": True}], indirect=True)
@pytest.mark.parametrize("initial_opt_in", [False, True])
async def test_stub_opt_in_is_pinned_at_admission_and_current_opt_out_is_honored(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, initial_opt_in: bool
) -> None:
    settings = _stub_settings(monkeypatch, allowed=initial_opt_in)
    setup.container.config.litellm_url = ""
    create_run = setup.container.run_store.create_run

    async def admit_then_change_setting(*args: Any, **kwargs: Any) -> Any:
        run = await create_run(*args, **kwargs)
        settings.allow_stub_llm = not initial_opt_in
        return run

    monkeypatch.setattr(setup.container.run_store, "create_run", admit_then_change_setting)
    result = await _execute(setup, _dag(""))
    assert result["status"] == "failed", result
    assert "ALLOW_STUB_LLM" in result["error"]
    run = await setup.container.run_store.get_run(result["run_id"])
    assert run.provenance["ordinary_model_dry_run"] is initial_opt_in
    assert setup.requests == []
    _no_invocations(setup, result["run_id"])
