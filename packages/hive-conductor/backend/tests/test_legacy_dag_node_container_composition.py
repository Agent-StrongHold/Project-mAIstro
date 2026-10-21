"""Container-path composition proof for the legacy_dag_node egress migration (#1083).

``CANDIDATE_MIGRATIONS`` in ``scripts/check-model-egress.py`` records two
operator-approved moves. The migration-map fixture test
(``tests/test_check_model_egress.py``) proves which move was approved; it
cannot prove the moved call can execute through shipped composition. This
module is the runtime half for the entry whose destination is
``services.legacy_dag_node`` (predecessor ``services.graph_runner``, #835):
a legacy DAG LLM node must execute through the real Container —
``maistro.container.create_container``, the production ``execute_dag``
resolver composition, and the governed ``Binding -> Invocation`` egress —
with only the final physical provider transport faked.

The companion runtime proof for the other entry (destination
``maistro.capabilities.providers.llm_gateway``, predecessor
``maistro.graph.nodes.llm_summarize``, #56) lives in
``packages/maistro-core/tests/test_model_egress_container_composition.py``.

Nothing here repairs composition: the Container is built by the shipped
bootstrap (Workspace/Project stores, ``provider_config_path`` registry
wiring, deployment gateway env), the node resolver is the production one
``execute_dag`` builds, and no Binding, registry, or resolver is injected by
the test. Removing the required wiring (gateway endpoint configuration, or
the model metadata registration the Binding pin depends on) must make the
proof fail — the deliberately unconfigured cases fail closed with no
fabricated successful model result.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from services import canonical_dag_runner as runner
from services.dag_execution_scope import DagExecutionScope

from maistro.container import Container, create_container
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.types.config import AgentConfig

_WORKSPACE = "legacy-egress-workspace"
_ACTOR = "legacy-egress-user"
_NODE = "n1"
_MODEL = "legacy-node-gateway-model"
_GATEWAY_KEY = "deployment-gateway-key-from-env"


def _dag() -> dict[str, Any]:
    """One LLM legacy node; no tool, no operator-declared model Binding.

    This is the migrated ``services.legacy_dag_node`` caller shape: the node
    names only a model, and the governed egress must compose everything else
    from the Container.
    """
    return {
        "id": "legacy-egress-dag",
        "name": "Legacy egress container proof",
        "description": "one governed model call for the migrated legacy node",
        "nodes": [
            {
                "id": _NODE,
                "role": "worker",
                "name": _NODE,
                "prompt": "do governed legacy work",
                "model": _MODEL,
                "config": {"execution_tier": "safe"},
            }
        ],
        "edges": [],
        "entry_node": _NODE,
    }


async def _boot_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, register_model: bool
) -> Container:
    """Boot the real Container over the shipped configuration path.

    Workspace and root Project are provisioned through the Container's own
    stores; the node's model metadata is registered the way a deployment
    does it — the ``provider_config_path`` yaml, not a registry stand-in.
    The gateway endpoint is configured through the deployment env that
    ``services.governed_model._endpoint`` reads.
    """
    provider_config: Path | None = None
    if register_model:
        provider_config = tmp_path / "providers.yaml"
        provider_config.write_text(
            "models:\n"
            f"  - name: {_MODEL}\n"
            "    provider: openai\n"
            "    cost_input: 1.0\n"
            "    cost_output: 2.0\n"
            "    latency_p50_ms: 1\n",
            encoding="utf-8",
        )
    database_url = f"sqlite:///{tmp_path / 'runtime.sqlite3'}"
    initial = await create_container(
        AgentConfig(router_api_key="test-router-key", database_url=database_url)
    )
    await initial.workspace_store.create(
        name="Legacy egress", creator_user_id=_ACTOR, workspace_id=_WORKSPACE
    )
    # The root Project must exist before the executing scope names it.
    await initial.project_scope_store.root_for_workspace(_WORKSPACE)
    await initial.aclose()
    owner = await create_container(
        AgentConfig(
            router_api_key="test-router-key",
            database_url=database_url,
            workspace_id=_WORKSPACE,
            # Omitting the registration (register_model=False) is the
            # missing-collaborator case: the ProviderRegistry boots empty,
            # so the pinned model resolves nothing.
            **(
                {"provider_config_path": str(provider_config)}
                if provider_config is not None
                else {}
            ),
        )
    )
    # Install the bootstrapped Container at the composition seam execute_dag
    # reads. The composition itself (_resolver, dag_node_runtime, the governed
    # egress) stays production code; this only supplies the live Container a
    # booted deployment would already have.
    monkeypatch.setattr(runner, "_container", lambda: owner)
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://gateway.test")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", _GATEWAY_KEY)
    # The node's own model pin must outrank the ambient default.
    monkeypatch.setenv("CHAT_DEFAULT_MODEL", "ambient-default-alias")
    return owner


def _fake_transport(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace only the physical provider transport; composition stays real."""
    import maistro.capabilities.model_chat as model_chat
    from maistro.capabilities.providers.llm_gateway import _chat_payload

    calls: list[dict[str, Any]] = []

    async def execute(provider: Any, request: Any, *, endpoint: Any) -> dict[str, Any]:
        calls.append({"payload": _chat_payload(provider, request), "endpoint": endpoint})
        return {
            "model": f"{_MODEL}-2026-10",
            "choices": [{"message": {"content": "A governed legacy answer."}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }

    monkeypatch.setattr(model_chat, "execute_model_chat", execute)
    return calls


async def _execute(container: Container) -> dict[str, Any]:
    project = await container.project_scope_store.root_for_workspace(_WORKSPACE)
    return await runner.execute_dag(
        _dag(),
        scope=DagExecutionScope(
            workspace_id=_WORKSPACE, project_id=project.project_id, user_id=_ACTOR
        ),
    )


async def test_legacy_llm_node_reaches_the_pinned_provider_and_records_canonical_correlation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migrated node executes through the real Container path.

    Every collaborator is production composition: the Container bootstrap,
    the governed runtime ``execute_dag`` composes, Binding/Invocation/Run
    authorities, the provider registry fed by the shipped provider config,
    and the credential scope the egress provisions from the configured
    gateway endpoint. Only the paid HTTP hop is fake. Delete any of that
    wiring and this test fails — there is no manufactured node, registry,
    Binding, or resolver in the test to keep it green.
    """
    container = await _boot_container(tmp_path, monkeypatch, register_model=True)
    calls = _fake_transport(monkeypatch)
    ledger = container.usage_log

    try:
        result = await _execute(container)

        assert result["status"] == "completed", result
        node_result = result["node_results"][_NODE]
        assert node_result["success"] is True
        assert node_result["response"] == "A governed legacy answer."
        assert node_result["model"] == _MODEL

        # The physical call crossed the governed gateway exactly once, carrying
        # the node's model pin (not the ambient CHAT_DEFAULT_MODEL alias) and the
        # egress-provisioned gateway credential from the configured endpoint.
        assert len(calls) == 1
        served = calls[0]
        assert served["payload"]["model"] == _MODEL
        assert served["payload"]["response_format"] == {"type": "json_object"}
        assert served["endpoint"].api_key == _GATEWAY_KEY
        assert served["endpoint"].base_url == "https://gateway.test"

        # Canonical Run/NodeRun/Attempt identity, read from the Container's own
        # canonical RunStore.
        run = await container.run_store.get_run(result["run_id"])
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.workspace_id == _WORKSPACE
        assert run.actor_principal_id == _ACTOR
        (node_run,) = await container.run_store.list_node_runs(result["run_id"])
        assert node_run.node_id == _NODE
        assert node_run.status is RunStatus.COMPLETED
        (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
        assert attempt.status is AttemptStatus.COMPLETED

        # The quota ledger moved with full provenance — the Container's own
        # usage ledger, restored from its durable backend — then the Invocation
        # itself is fetched back from the Container's Invocation authority by
        # the invocation id the ledger recorded.
        assert ledger.scope_keys() == (_MODEL,)
        (event,) = ledger.events_for(_MODEL)
        assert event.usage_reported is True
        assert (event.input_tokens, event.output_tokens) == (1000, 500)
        assert event.invocation_id
        invocation = await container.invocation_store.get(event.invocation_id)
        assert invocation is not None
        assert invocation.status.value == "completed"
        assert invocation.run_id == result["run_id"]
        assert invocation.node_run_id == node_run.node_run_id
        assert invocation.attempt_id == attempt.attempt_id
        assert invocation.effect_key == f"dag-llm-{_NODE}-{attempt.attempt_id}"
        assert invocation.binding.capability == "model.chat"
        assert invocation.binding.provider_name == _MODEL
        assert invocation.binding.node_id == _NODE
        assert invocation.usage is not None
        assert invocation.usage.provider == "openai"
        assert invocation.usage.model == _MODEL
        assert invocation.usage.model_version == f"{_MODEL}-2026-10"
        assert (invocation.usage.input_units, invocation.usage.output_units) == (1000, 500)
        assert invocation.usage.cost_cents == 2.0
    finally:
        # Close what the test booted: an unclosed Container strands aiosqlite
        # worker threads whose loop is gone, so a later test inherits the
        # unhandled-thread warning. Assertion reads must happen above, inside
        # the try: aclose() closes the Container's SQLite connections, and a
        # store read issued after it fails loudly on the closed connection.
        await container.aclose()


async def test_unconfigured_gateway_fails_the_legacy_node_closed_without_fabricated_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No gateway endpoint: the node refuses, nothing succeeds, nothing is invented.

    The canonical execution spine is mandatory (#1113), so the unconfigured
    deployment is the real Container minus every gateway endpoint source:
    ``_endpoint`` finds no base URL, ``dag_node_runtime`` composes None, and
    the compatibility builder refuses to fabricate a stub answer without the
    explicit ALLOW_STUB_LLM opt-in. The admitted canonical Run fails closed:
    no transport call, no fabricated success, no usage evidence manufactured
    for a call that never happened.
    """
    from services.dag_agents import CanonicalGraphUnavailable

    # No canonical authority at all is refused before admission — a second
    # lifecycle is never invented for work that cannot be executed.
    monkeypatch.setattr(runner, "_container", lambda: None)
    with pytest.raises(CanonicalGraphUnavailable):
        await runner.execute_dag(
            _dag(),
            scope=DagExecutionScope(
                workspace_id=_WORKSPACE,
                project_id="legacy-egress-project",
                user_id=_ACTOR,
            ),
        )

    # The unconfigured-but-booted deployment: the same real Container the
    # happy path uses, with the model metadata registered, and then every
    # gateway endpoint/credential source removed.
    container = await _boot_container(tmp_path, monkeypatch, register_model=True)
    for key in (
        "MAISTRO_LLM_BASE_URL",
        "MAISTRO_LLM_API_KEY",
        "LITELLM_API_BASE",
        "LITELLM_API_KEY",
        "LITELLM_PROXY_URL",
        "LITELLM_PROXY_KEY",
        "LITELLM_MASTER_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    # get_settings is lru_cached suite-wide; pin the attributes the governed
    # path reads so the unconfigured refusal is deterministic here. The
    # effective-key contract (`services.secrets.effective_llm_gateway_key`)
    # reads `settings.maistro_llm_api_key` first, so the stub must carry that
    # field too — a SimpleNamespace without it is not a faithful Settings and
    # raises AttributeError instead of failing closed.
    import config as hive_config

    monkeypatch.setattr(
        hive_config,
        "get_settings",
        lambda: SimpleNamespace(
            litellm_api_base=None,
            litellm_api_key=None,
            maistro_llm_api_key=None,
            allow_stub_llm=False,
        ),
    )
    calls = _fake_transport(monkeypatch)
    ledger = container.usage_log

    try:
        result = await _execute(container)

        assert result["status"] == "failed", result
        node_result = result["node_results"][_NODE]
        assert node_result["success"] is False
        assert "No LLM gateway is configured" in node_result["response"]
        assert "No LLM gateway is configured" in str(result.get("error", ""))
        assert calls == []
        # The admitted canonical Run itself failed closed — no fabricated
        # success anywhere in the lifecycle.
        run = await container.run_store.get_run(result["run_id"])
        assert run is not None
        assert run.status is RunStatus.FAILED
        (node_run,) = await container.run_store.list_node_runs(result["run_id"])
        assert node_run.node_id == _NODE
        assert node_run.status is RunStatus.FAILED
        # No fabricated evidence either: nothing recorded usage for a model
        # call that never executed.
        assert ledger.scope_keys() == ()
    finally:
        await container.aclose()


async def test_unregistered_model_metadata_fails_the_real_container_path_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Binding pin requires registry metadata the shipped config registers.

    Dropping the ``provider_config_path`` registration removes a required
    collaborator: the governed runtime still composes, but the pinned model
    resolves nothing and the egress refuses before any transport dispatch.
    This is the migration-composition half of the map assertion — with the
    collaborator gone, the container-path proof fails instead of quietly
    succeeding through some fallback.
    """
    container = await _boot_container(tmp_path, monkeypatch, register_model=False)
    calls = _fake_transport(monkeypatch)
    ledger = container.usage_log

    try:
        result = await _execute(container)
        assert result["status"] == "failed", result
        node_result = result["node_results"][_NODE]
        assert node_result["success"] is False
        assert "pinned model" in node_result["response"]
        assert "ProviderRegistry" in node_result["response"]
        assert calls == []
        # No completed invocation, no usage evidence: the refusal happened before
        # the physical call, exactly as fail-closed requires.
        assert ledger.scope_keys() == ()
    finally:
        await container.aclose()
