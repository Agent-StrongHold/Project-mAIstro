"""One installed governed request, joined end to end (#1824 / #2247).

The credential-wiring tests and the Binding-resolution tests each prove half
of the installed path separately. What nothing proved is that ONE request —
admitted the way an installed deployment admits it — joins *all* the records
it must leave behind:

    Run → NodeRun → Attempt (the canonical spine)
      → the scoped `model.chat` Binding (the authorization decision)
      → the Invocation filed under that Binding and Attempt
      → the usage/provenance metadata the gateway reported

…with the physical call authenticated by the POOL-ISSUED credential the
bootstrap registered from the deployment's effective gateway key — the env
`MAISTRO_LLM_API_KEY` is a construction fallback, never a routing bypass
(#1078), so the effective-key contract (#2247) and the scoped credential
cannot disagree about who a request authenticates as.

Everything here is the production machinery: `create_container` with real
bootstrap-authorized Bindings, the canonical spine (`RunExecutionService` →
`AttemptExecutionService` → a real store), the Container's own node resolver,
and the governed Invocation boundary. Only the final transport is replaced
(`execute_model_chat`) — exactly the substitution the issue's acceptance
allows ("Positive proof uses existing bootstrap/credential routing,
replacing only final transport").

The security decision on this path is the scoped-Binding resolution itself:
the Binding the egress resolves in the requesting Workspace/Project scope is
the authorization, and its refusals (foreign scope, disabled/missing Binding,
unregistered credential reference) are durable — each leaves a FAILED Attempt
naming the refusal, recorded by the spine before any dispatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import maistro.capabilities.model_chat as model_chat
from maistro.container import build_node_resolver, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes.base import NodeContext
from maistro.graph.nodes.llm_summarize import LlmSummarizeIn
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, InMemoryRunStore, RunExecutionService
from maistro.runtime import PythonExecutionRuntime
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig
from maistro.types.errors import ConfigError

pytestmark = [pytest.mark.contract("behavioral")]

_WORKSPACE = "ws-e2e"
_PROJECT = "project-e2e"
_BINDING = "model-e2e"
_GATEWAY_KEY = "sk-effective-gateway-key"
_ENV_IMPOSTOR_KEY = "sk-env-impostor-never-dispatched"
_BASE_URL = "https://gateway.test"

#: The node spec exactly as an installed graph declares it.
_GRAPH_SPEC = {"nodes": [{"id": "summarize", "kind": "llm.summarize"}]}

#: The gateway body the fake transport answers with, usage included: the
#: usage leg of the chain must come from the *response*, not from a test
#: assertion's wish.
_GATEWAY_BODY = {
    "model": "yaml-model-2026-09",
    "choices": [{"message": {"content": "A governed summary."}}],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
}


def _provider_config(tmp_path: Path) -> str:
    path = tmp_path / "providers.yaml"
    path.write_text(
        "models:\n"
        "  - name: yaml-model\n"
        "    provider: openai\n"
        "    cost_input: 1.0\n"
        "    cost_output: 2.0\n"
        "    latency_p50_ms: 300\n",
        encoding="utf-8",
    )
    return str(path)


def _binding(project_id: str, **overrides: Any) -> dict[str, Any]:
    declaration = {
        "binding_id": _BINDING,
        "project_id": project_id,
        "provider_name": "yaml-model",
    }
    declaration.update(overrides)
    return declaration


async def _scope(*workspace_ids: str) -> tuple[Any, dict[str, str]]:
    """Real Project-scope store with one existing Project per Workspace.

    `InMemoryRunStore.create_run` refuses a Graph whose Project does not exist
    in canonical scope, so a faithful installed request runs under a Project
    the deployment actually created — and the Binding is declared in exactly
    that Project's scope."""
    project_store = InMemoryProjectScopeStore()
    project_ids: dict[str, str] = {}
    for workspace_id in workspace_ids:
        root = await project_store.create_root(workspace_id)
        project = await project_store.create(
            workspace_id=workspace_id,
            parent_project_id=root.project_id,
            name=f"Installed request ({workspace_id})",
        )
        project_ids[workspace_id] = project.project_id
    return project_store, project_ids


async def _container(
    tmp_path: Path,
    project_id: str,
    *,
    litellm_key: str = _GATEWAY_KEY,
    model_bindings: list[dict[str, Any]] | None = None,
) -> Any:
    """The Container an installed deployment builds: real bootstrap, real
    scoped credential registration, empty fail-closed Bindings otherwise."""
    return await create_container(
        AgentConfig(
            router_api_key="test-key",
            workspace_id=_WORKSPACE,
            provider_config_path=_provider_config(tmp_path),
            litellm_key=litellm_key,
            model_bindings=model_bindings if model_bindings is not None else [_binding(project_id)],
        )
    )


def _stamp_attempt_identity(attempt: Any, context: NodeContext) -> NodeContext:
    return context.model_copy(
        update={"node_run_id": attempt.node_run_id, "attempt_id": attempt.attempt_id}
    )


class _Transport:
    """The one replaced seam, recording what the physical call carried."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recording = self

        async def fake_execute_model_chat(
            provider: Any,
            payload: Any,
            *,
            endpoint: Any,
            on_chunk: Any = None,
        ) -> dict[str, Any]:
            recording.calls.append(
                {"provider": provider.name, "endpoint": endpoint, "payload": payload}
            )
            return dict(_GATEWAY_BODY)

        monkeypatch.setattr(model_chat, "execute_model_chat", fake_execute_model_chat)


class _Refused(Exception):
    """A governed refusal, raised so the spine records it as Attempt evidence."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class TestOneInstalledRequestJoinsEverything:
    async def test_spine_binding_invocation_usage_and_credential_agree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_store, project_ids = await _scope(_WORKSPACE)
        project_id = project_ids[_WORKSPACE]
        store = InMemoryRunStore(project_store=project_store)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
        container = await _container(tmp_path, project_id)
        resolver = build_node_resolver(
            effect_context=container.capability_effects,
            provider_registry=container.provider_registry,
            llm_router=container.llm_router,
        )
        transport = _Transport()
        transport.install(monkeypatch)

        # The env impostor: the effective-key contract lets an operator name
        # a deployment key in the environment, but the physical call must
        # authenticate with the credential the scoped pool registered — the
        # env var is a construction fallback, never a routing bypass (#1078).
        monkeypatch.setenv("MAISTRO_LLM_API_KEY", _ENV_IMPOSTOR_KEY)
        monkeypatch.setenv("MAISTRO_LLM_BASE_URL", _BASE_URL)

        graph = Graph(
            workspace_id=_WORKSPACE,
            project_id=project_id,
            name="Installed request",
            nodes=[Node(node_id="summarize", node_type="llm.summarize")],
        )
        run = await service.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
        inputs = {
            "text": "Long source text",
            "model": "",
            "binding_id": _BINDING,
        }
        base_context = NodeContext(
            run_id=run.run_id,
            dag_id="graph-e2e",
            node_id="summarize",
            workspace_id=_WORKSPACE,
            project_id=project_id,
        )

        async def executor(_work_item: Any, context: NodeContext) -> dict[str, Any]:
            node = resolver("summarize", _GRAPH_SPEC)
            result = await node.run(inputs, context)
            if not result.success:
                raise _Refused(result.error_code or "", result.error_message or "")
            return result.output.model_dump(mode="json")

        node_run, attempt = await service.execute_node(
            run.run_id,
            "summarize",
            {"text_length": len(inputs["text"])},
            base_context,
            executor=executor,
            executor_id="e2e-governed-request",
            context_factory=_stamp_attempt_identity,
        )

        # --- the spine legs agree ---------------------------------------
        assert node_run.run_id == run.run_id
        assert attempt.node_run_id == node_run.node_run_id
        assert attempt.status is AttemptStatus.COMPLETED
        persisted_run = await store.get_run(run.run_id)
        persisted_node_run = await store.get_node_run(node_run.node_run_id)
        persisted_attempt = await store.get_attempt(attempt.attempt_id)
        assert persisted_run is not None and persisted_run.run_id == run.run_id
        assert persisted_node_run is not None
        assert persisted_node_run.run_id == run.run_id
        assert persisted_attempt is not None
        assert persisted_attempt.node_run_id == node_run.node_run_id
        assert persisted_attempt.status is AttemptStatus.COMPLETED

        # --- the authorization decision ---------------------------------
        # The Binding the request ran under is the one the bootstrap
        # authorized for this Workspace/Project, and its credential_refs
        # were backfilled with the one reference the bootstrap registers —
        # the deployment's gateway credential (AgentConfig.litellm_key).
        from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
        from maistro.capabilities.providers.llm_gateway import (
            DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
        )

        resolved = await container.capability_effects.bindings.resolve(
            _BINDING,
            workspace_id=_WORKSPACE,
            project_id=project_id,
            node_id="summarize",
            capability=MODEL_CHAT_CAPABILITY,
        )
        assert resolved.workspace_id == _WORKSPACE
        assert resolved.provider_name == "yaml-model"
        assert resolved.credential_refs == (DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,)

        # --- the physical call ------------------------------------------
        assert len(transport.calls) == 1, "exactly one governed dispatch"
        call = transport.calls[0]
        assert call["provider"] == "yaml-model"
        assert call["endpoint"].base_url == _BASE_URL
        # POOL-ISSUED credential, not the env impostor (#1078, #2247).
        assert call["endpoint"].api_key == _GATEWAY_KEY

        # --- the Invocation joins the Attempt that produced it ----------
        node = resolver("summarize", _GRAPH_SPEC)
        invocations = await container.capability_effects.invocation_store.list_effect(
            run_id=run.run_id,
            node_run_id=node_run.node_run_id,
            binding_id=_BINDING,
            effect_key=node.logical_effect_key(LlmSummarizeIn(**inputs), base_context),
        )
        assert len(invocations) == 1
        invocation = invocations[0]
        assert invocation.run_id == run.run_id
        assert invocation.node_run_id == node_run.node_run_id
        assert invocation.attempt_id == attempt.attempt_id
        assert invocation.workspace_id == _WORKSPACE
        assert invocation.binding.binding_id == _BINDING

        # --- the usage leg ----------------------------------------------
        usage = invocation.usage
        assert usage is not None
        assert usage.input_units == 1000
        assert usage.output_units == 500
        assert usage.provider == "openai"
        assert usage.model == "yaml-model"
        assert usage.model_version == "yaml-model-2026-09"


class TestCredentialRefusalsAreDurableBeforeDispatch:
    """Each missing-authorization case refuses with no gateway call, and the
    refusal itself is persisted: a FAILED Attempt naming the refusal."""

    async def _execute_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        container: Any,
        project_store: Any,
        project_id: str,
        workspace_id: str = _WORKSPACE,
        binding_id: str = _BINDING,
    ) -> dict[str, Any]:
        store = InMemoryRunStore(project_store=project_store)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
        resolver = build_node_resolver(
            effect_context=container.capability_effects,
            provider_registry=container.provider_registry,
            llm_router=container.llm_router,
        )
        transport = _Transport()
        transport.install(monkeypatch)
        monkeypatch.setenv("MAISTRO_LLM_BASE_URL", _BASE_URL)

        graph = Graph(
            workspace_id=workspace_id,
            project_id=project_id,
            name="Refused request",
            nodes=[Node(node_id="summarize", node_type="llm.summarize")],
        )
        run = await service.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
        base_context = NodeContext(
            run_id=run.run_id,
            dag_id="graph-e2e",
            node_id="summarize",
            workspace_id=workspace_id,
            project_id=project_id,
        )
        inputs = {"text": "Must not dispatch", "model": "", "binding_id": binding_id}

        async def executor(_work_item: Any, context: NodeContext) -> dict[str, Any]:
            node = resolver("summarize", _GRAPH_SPEC)
            result = await node.run(inputs, context)
            if not result.success:
                raise _Refused(result.error_code or "", result.error_message or "")
            return result.output.model_dump(mode="json")

        recorded: dict[str, Any] = {}
        try:
            await service.execute_node(
                run.run_id,
                "summarize",
                {"text_length": len(inputs["text"])},
                base_context,
                executor=executor,
                executor_id="e2e-governed-request",
                context_factory=_stamp_attempt_identity,
            )
        except _Refused as refused:
            recorded["code"] = refused.code
        recorded["calls"] = transport.calls
        recorded["store"] = store
        recorded["run_id"] = run.run_id
        return recorded

    async def test_a_foreign_scope_refuses_and_leaves_a_failed_attempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Binding is authorized in ws-e2e's Project only: the same
        binding_id requested from a foreign Workspace/Project scope is denied
        before any dispatch, and the denial is durable."""
        project_store, project_ids = await _scope(_WORKSPACE, "ws-foreign")
        container = await _container(tmp_path, project_ids[_WORKSPACE])

        recorded = await self._execute_refused(
            tmp_path,
            monkeypatch,
            container=container,
            project_store=project_store,
            workspace_id="ws-foreign",
            project_id=project_ids["ws-foreign"],
        )

        assert recorded["code"] == "BindingScopeDenied"
        assert recorded["calls"] == [], "a scope denial must never dispatch"
        attempt = await self._failed_attempt(recorded)
        assert "BindingScopeDenied" in (attempt.error or "")

    async def test_a_missing_binding_refuses_and_leaves_a_failed_attempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No declaration authorizes nothing: an undeclared binding_id is
        refused before dispatch, durably."""
        project_store, project_ids = await _scope(_WORKSPACE)
        container = await _container(tmp_path, project_ids[_WORKSPACE])

        recorded = await self._execute_refused(
            tmp_path,
            monkeypatch,
            container=container,
            project_store=project_store,
            project_id=project_ids[_WORKSPACE],
            binding_id="never-declared",
        )

        assert recorded["code"] == "BindingNotFound"
        assert recorded["calls"] == []
        attempt = await self._failed_attempt(recorded)
        assert "BindingNotFound" in (attempt.error or "")

    async def test_a_disabled_binding_refuses_and_leaves_a_failed_attempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator-disabled declaration stays registered yet authorizes
        nothing: resolution refuses before dispatch, durably."""
        project_store, project_ids = await _scope(_WORKSPACE)
        container = await _container(
            tmp_path,
            project_ids[_WORKSPACE],
            model_bindings=[_binding(project_ids[_WORKSPACE], disabled=True)],
        )

        recorded = await self._execute_refused(
            tmp_path,
            monkeypatch,
            container=container,
            project_store=project_store,
            project_id=project_ids[_WORKSPACE],
        )

        assert recorded["code"] == "BindingDisabled"
        assert recorded["calls"] == []
        attempt = await self._failed_attempt(recorded)
        assert "BindingDisabled" in (attempt.error or "")

    async def test_a_binding_with_no_registered_credential_refuses_before_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Binding resolves but the deployment registered no gateway
        credential (empty effective key): the credential router refuses
        before any model call — fail-closed, never a placeholder key."""
        project_store, project_ids = await _scope(_WORKSPACE)
        container = await _container(tmp_path, project_ids[_WORKSPACE], litellm_key="")

        recorded = await self._execute_refused(
            tmp_path,
            monkeypatch,
            container=container,
            project_store=project_store,
            project_id=project_ids[_WORKSPACE],
        )

        assert recorded["code"] == "CredentialScopeError"
        assert recorded["calls"] == []
        attempt = await self._failed_attempt(recorded)
        assert "CredentialScopeError" in (attempt.error or "")

    async def test_an_unregistrable_credential_reference_refuses_at_bootstrap(
        self, tmp_path: Path
    ) -> None:
        """A Binding naming a credential reference no production surface can
        register is refused when the Container is built — not discovered as
        a runtime CredentialScopeError on the first request."""
        _, project_ids = await _scope(_WORKSPACE)
        with pytest.raises(ConfigError, match="credential_refs"):
            await _container(
                tmp_path,
                project_ids[_WORKSPACE],
                model_bindings=[
                    _binding(project_ids[_WORKSPACE], credential_refs=("vault://creds/other",))
                ],
            )

    async def _failed_attempt(self, recorded: dict[str, Any]) -> Any:
        store: InMemoryRunStore = recorded["store"]
        node_runs = await store.list_node_runs(recorded["run_id"])
        assert len(node_runs) == 1
        attempts = await store.list_attempts(node_runs[0].node_run_id)
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.status is AttemptStatus.FAILED
        return attempt
