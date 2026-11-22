"""The server-composed Canvas job runner (#2311, ADR-045 runner START).

Covers the composition module that starts ``CanvasJobRunner`` inside the
maistro-server process:

- the governed image client refuses calls outside canonical execution
  context, refuses an unregistered Binding, and maps the governed egress
  result onto the Canvas ``ImageData`` shape with the durable blob reference
  as the URL;
- ``refine`` is truthfully unsupported (no governed edits endpoint — faking
  one would recreate the unowned bypass the client replaces);
- the model registry fails closed: no default configured → a configuration
  error naming the variable, never a guess; an unreadable gateway list →
  nothing is registered;
- the warden adapter maps any non-clean verdict to BLOCK;
- ``start_canvas_job_runner`` registers the image Binding, builds the runtime
  through the package-owned composition seam, starts a live poll-loop task,
  and ``stop_canvas_job_runner`` stops it boundedly.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import (
    BindingDisabled,
    BindingNotFound,
    BindingScopeDenied,
)
from maistro.capabilities.image_generation import IMAGE_GENERATE_CAPABILITY
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.http import override_transport
from maistro.observability.correlation import bind_execution_context
from maistro_server.canvas_runtime import (
    CANVAS_IMAGE_BINDING_ID,
    CanvasImageBlobStore,
    CanvasRunnerHandle,
    GatewayModelRegistry,
    GovernedGatewayImageClient,
    WardenPromptScan,
    canvas_image_binding_id,
    start_canvas_job_runner,
    stop_canvas_job_runner,
)

ENDPOINT = GatewayEndpoint(base_url="http://gateway.test", api_key="key")

#: The admission scope the fakes below authorize (the runner tests' fake chat
#: admitter returns exactly this pair). Non-default on purpose: a scope that
#: happens to equal the retired fabricated values would make the scope
#: assertions in this module vacuous.
ADMISSION_WORKSPACE = "ws-default"
ADMISSION_PROJECT = "root-project"
BINDING_ID = canvas_image_binding_id(ADMISSION_WORKSPACE, ADMISSION_PROJECT)


# ─────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────


class _FakeBindings:
    """The BindingStore contract the client now goes through (#2464):
    ``resolve`` re-checks scope against the registered record instead of
    trusting a bare ``get``, mirroring ``BindingStore.resolve``."""

    def __init__(self) -> None:
        self.records: dict[str, Binding] = {}
        self.puts: list[Binding] = []

    async def put(self, binding: Binding) -> Binding:
        self.puts.append(binding)
        self.records[binding.binding_id] = binding
        return binding

    async def get(self, binding_id: str) -> Binding | None:
        return self.records.get(binding_id)

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding:
        binding = self.records.get(binding_id)
        if binding is None:
            raise BindingNotFound(f"Binding {binding_id!r} is not registered")
        if binding.disabled:
            raise BindingDisabled(f"Binding {binding_id!r} is disabled")
        if binding.workspace_id != workspace_id:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} belongs to Workspace {binding.workspace_id!r}, "
                f"not {workspace_id!r}"
            )
        if binding.project_id != project_id:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} belongs to Project {binding.project_id!r}, "
                f"not {project_id!r}"
            )
        if binding.node_id and binding.node_id != node_id:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} is restricted to Node {binding.node_id!r}"
            )
        if binding.capability != capability:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} authorizes Capability {binding.capability!r}, "
                f"not {capability!r}"
            )
        return binding


class _FakeEffects:
    def __init__(self) -> None:
        self.bindings = _FakeBindings()


class _FakeBlobStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.n = 0

    async def put(self, data: bytes, *, media_type: str) -> str:
        self.n += 1
        ref = f"blob-{self.n}"
        self.blobs[ref] = data
        return ref

    async def get(self, ref: str) -> bytes | None:
        return self.blobs.get(ref)


class _FakeEgress:
    """Records the governed call; returns canned images."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            invocation_id="inv-1",
            model=kwargs["request"].model,
            images=[b"\x89PNG fake", b"\x89PNG fake 2"],
            refs=["blob-1", "blob-2"],
        )


class _FakeWarden:
    def __init__(self, clean: bool) -> None:
        self.clean = clean
        self.scanned: list[str] = []

    async def scan(self, content: str, boundary: str) -> Any:
        self.scanned.append(content)
        return SimpleNamespace(clean=self.clean, flags=() if self.clean else ("injection",))


def _image_client(
    effects: _FakeEffects, egress: _FakeEgress | None = None
) -> GovernedGatewayImageClient:
    client = GovernedGatewayImageClient(
        effects,
        endpoint=ENDPOINT,
        blobs=CanvasImageBlobStore(_FakeBlobStore()),
        workspace_id=ADMISSION_WORKSPACE,
        project_id=ADMISSION_PROJECT,
        binding_id=BINDING_ID,
    )
    if egress is not None:
        client._egress = egress  # test seam
    return client


def _registered_binding() -> Binding:
    return Binding(
        binding_id=BINDING_ID,
        workspace_id=ADMISSION_WORKSPACE,
        project_id=ADMISSION_PROJECT,
        capability=IMAGE_GENERATE_CAPABILITY,
        credential_refs=("litellm-gateway",),
    )


# ─────────────────────────────────────────────────────────────────────
# GovernedGatewayImageClient
# ─────────────────────────────────────────────────────────────────────


class TestGovernedImageClient:
    async def test_generate_refuses_outside_canonical_execution(self) -> None:
        client = _image_client(_FakeEffects())
        with pytest.raises(RuntimeError, match="canonical execution context"):
            await client.generate(model_id="m", prompt="p", width=64, height=64, count=1)

    async def test_generate_refuses_an_unregistered_binding(self) -> None:
        effects = _FakeEffects()
        client = _image_client(effects)
        with (
            bind_execution_context(run_id="r", node_run_id="nr", attempt_id="at"),
            pytest.raises(RuntimeError, match="not registered"),
        ):
            await client.generate(model_id="m", prompt="p", width=64, height=64)

    async def test_generate_refuses_a_binding_registered_in_another_scope(self) -> None:
        """Negative path (#2464): a registered Binding whose Workspace/Project
        differ from the executing scope must fail closed BEFORE provider
        dispatch — no egress call, no Invocation, no successful-looking
        receipt. This is the mismatch the retired registration used to ship:
        a Binding under a fabricated ``default`` Project while Runs executed
        in their admission scope."""
        effects = _FakeEffects()
        await effects.bindings.put(
            Binding(
                binding_id=BINDING_ID,
                workspace_id="another-workspace",
                project_id="default",
                capability=IMAGE_GENERATE_CAPABILITY,
                credential_refs=("litellm-gateway",),
            )
        )
        egress = _FakeEgress()
        client = _image_client(effects, egress)
        with (
            bind_execution_context(run_id="r", node_run_id="nr", attempt_id="at"),
            pytest.raises(BindingScopeDenied, match="Workspace"),
        ):
            await client.generate(model_id="m", prompt="p", width=64, height=64)
        assert egress.calls == [], "a scope-mismatched Binding must never reach the provider"

    async def test_generate_refuses_when_the_run_scope_differs_from_the_composition(
        self,
    ) -> None:
        """Negative path (#2464): the executing Run's durable scope rides the
        ambient context (the Canvas executor binds it from the Run row). A
        client composed in one scope asked to generate for a Run admitted in
        another — the cross-tenant claim — must refuse before dispatch even
        though its own Binding resolves cleanly in the composition scope."""
        effects = _FakeEffects()
        await effects.bindings.put(_registered_binding())
        egress = _FakeEgress()
        client = _image_client(effects, egress)
        with (
            bind_execution_context(
                run_id="r",
                node_run_id="nr",
                attempt_id="at",
                workspace_id="tenant-b",
                project_id="tenant-b-root",
            ),
            pytest.raises(BindingScopeDenied, match="Workspace"),
        ):
            await client.generate(model_id="m", prompt="p", width=64, height=64)
        assert egress.calls == [], "a foreign-scope Run must never spend this scope's Binding"

    async def test_generate_runs_under_the_run_scope_when_bound(self) -> None:
        """The happy path resolves in the ambient scope: the same composition
        serving a Run whose durable scope matches must dispatch (the retired
        code resolved nothing and could not have told the two cases apart)."""
        effects = _FakeEffects()
        await effects.bindings.put(_registered_binding())
        egress = _FakeEgress()
        client = _image_client(effects, egress)
        with bind_execution_context(
            run_id="r",
            node_run_id="nr",
            attempt_id="at",
            workspace_id=ADMISSION_WORKSPACE,
            project_id=ADMISSION_PROJECT,
            actor_id="principal-7",
        ):
            await client.generate(model_id="m", prompt="p", width=64, height=64)
        assert len(egress.calls) == 1
        # The Run's acting principal rides to the Invocation (#2464): quota
        # and audit attribute the effect to the identity the Run acts for.
        assert egress.calls[0]["actor_id"] == "principal-7"

    async def test_generate_crosses_the_governed_boundary_with_canonical_ids(self) -> None:
        effects = _FakeEffects()
        await effects.bindings.put(_registered_binding())
        egress = _FakeEgress()
        client = _image_client(effects, egress)

        with bind_execution_context(run_id="run-1", node_run_id="node-1", attempt_id="att-1"):
            images = await client.generate(
                model_id="image-model", prompt="a castle", width=1024, height=768, count=2
            )

        call = egress.calls[0]
        assert call["binding"].binding_id == BINDING_ID
        assert call["run_id"] == "run-1"
        assert call["node_run_id"] == "node-1"
        assert call["attempt_id"] == "att-1"
        assert call["request"].model == "image-model"
        assert call["request"].size == "1024x768"
        assert call["request"].n == 2
        # The effect key is deterministic for the same logical effect, so a
        # stage retry replays the completed Invocation instead of re-billing.
        assert egress.calls[0]["effect_key"] == egress.calls[0]["effect_key"]
        with bind_execution_context(run_id="run-1", node_run_id="node-1", attempt_id="att-2"):
            again = await client.generate(
                model_id="image-model", prompt="a castle", width=1024, height=768, count=2
            )
        assert egress.calls[1]["effect_key"] == egress.calls[0]["effect_key"]
        assert again[0].url == images[0].url

        # ImageData carries the durable blob reference as the URL, plus bytes.
        assert [img.url for img in images] == ["blob-1", "blob-2"]
        assert images[0].bytes_ == b"\x89PNG fake"
        assert (images[0].width, images[0].height) == (1024, 768)

    async def test_effect_key_differs_for_different_logical_effects(self) -> None:
        effects = _FakeEffects()
        await effects.bindings.put(_registered_binding())
        egress = _FakeEgress()
        client = _image_client(effects, egress)
        with bind_execution_context(run_id="r", node_run_id="n1", attempt_id="a"):
            await client.generate(model_id="m", prompt="one", width=64, height=64)
        with bind_execution_context(run_id="r", node_run_id="n2", attempt_id="a"):
            await client.generate(model_id="m", prompt="one", width=64, height=64)
        assert egress.calls[0]["effect_key"] != egress.calls[1]["effect_key"]

    async def test_refine_is_truthfully_unsupported(self) -> None:
        client = _image_client(_FakeEffects())
        with pytest.raises(RuntimeError, match="not supported"):
            await client.refine(
                model_id="m", source_url="blob://x", prompt="p", region="full", strength=0.6
            )

    async def test_list_image_models_is_empty_not_fabricated(self) -> None:
        assert await _image_client(_FakeEffects()).list_image_models() == []

    async def test_a_client_cannot_exist_without_a_scope(self) -> None:
        """There is no representable unscoped instance (#2464): a client that
        could not name the scope it resolves its Binding against would be the
        old bare-``get`` world back again."""
        for kwargs in (
            {"workspace_id": " ", "project_id": "p"},
            {"workspace_id": "ws", "project_id": ""},
        ):
            with pytest.raises(ValueError, match="non-empty string"):
                GovernedGatewayImageClient(
                    _FakeEffects(),
                    endpoint=ENDPOINT,
                    blobs=CanvasImageBlobStore(_FakeBlobStore()),
                    binding_id=BINDING_ID,
                    **kwargs,
                )


# ─────────────────────────────────────────────────────────────────────
# GatewayModelRegistry
# ─────────────────────────────────────────────────────────────────────


async def _no_gateway_list(_endpoint: Any) -> tuple[str, ...]:
    """Offline stand-in for the gateway model fetch: the registry is empty
    and admissions fail closed, which the start/stop tests are not about."""
    return ()


class TestGatewayModelRegistry:
    @pytest.fixture(autouse=True)
    def _offline_gateway(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # None of these tests are about the fetch itself; the two that are
        # patch it explicitly with their own stubs.
        import maistro_server.canvas_runtime as module

        monkeypatch.setattr(module, "_fetch_gateway_models", _no_gateway_list)

    async def test_default_draft_from_env(self) -> None:
        registry = await GatewayModelRegistry.from_gateway(
            ENDPOINT, env={"MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL": "gemini-image"}
        )
        assert registry.get_default_draft() == "gemini-image"

    async def test_unset_default_draft_refuses_to_guess(self) -> None:
        registry = await GatewayModelRegistry.from_gateway(ENDPOINT, env={})
        with pytest.raises(RuntimeError, match="MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL"):
            registry.get_default_draft()

    async def test_registry_is_fail_closed_when_the_list_cannot_be_fetched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import maistro_server.canvas_runtime as module

        async def unreachable(_endpoint: Any) -> tuple[str, ...]:
            return ()

        monkeypatch.setattr(module, "_fetch_gateway_models", unreachable)
        registry = await GatewayModelRegistry.from_gateway(
            ENDPOINT, env={"MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL": "m"}
        )
        assert registry.is_registered("m") is False
        assert registry.is_registered("anything") is False

    async def test_is_registered_answers_from_the_gateway_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import maistro_server.canvas_runtime as module

        async def fetched(_endpoint: Any) -> tuple[str, ...]:
            return ("image-a", "image-b")

        monkeypatch.setattr(module, "_fetch_gateway_models", fetched)
        registry = await GatewayModelRegistry.from_gateway(ENDPOINT, env={})
        assert registry.is_registered("image-a") is True
        assert registry.is_registered("image-c") is False


class TestGatewayModelFetch:
    """Use the real fetch/parser and shared HTTP client, not a canned model list."""

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://gateway.test",
            "http://gateway.test/",
            "http://gateway.test/v1",
            "http://gateway.test/v1/",
        ],
    )
    async def test_fetches_authenticated_models_and_filters_invalid_entries(
        self, base_url: str
    ) -> None:
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"data": [{"id": "image-a"}, {"id": "image-b"}, {}, {"id": 7}, None, "bad"]},
            )

        with override_transport(httpx.MockTransport(respond)):
            registry = await GatewayModelRegistry.from_gateway(
                GatewayEndpoint(base_url=base_url, api_key="gateway-key"),
                env={"MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL": " image-a "},
            )

        assert len(requests) == 1
        assert requests[0].method == "GET"
        assert str(requests[0].url) == "http://gateway.test/v1/models"
        assert requests[0].headers["Authorization"] == "Bearer gateway-key"
        assert registry.get_default_draft() == "image-a"
        assert registry.is_registered("image-a")
        assert registry.is_registered("image-b")
        assert not registry.is_registered("7")
        assert not registry.is_registered("bad")
        assert not registry.is_registered("not-listed")

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(httpx.Response(200, json=[]), id="not-an-object"),
            pytest.param(httpx.Response(200, json={}), id="missing-data"),
            pytest.param(httpx.Response(200, json={"data": {"id": "image-a"}}), id="not-a-list"),
            pytest.param(httpx.Response(200, content=b"not-json"), id="invalid-json"),
            pytest.param(
                httpx.Response(401, json={"data": [{"id": "image-a"}]}), id="unauthorized"
            ),
            pytest.param(httpx.Response(503, json={"data": [{"id": "image-a"}]}), id="unavailable"),
        ],
    )
    async def test_unreadable_or_unsuccessful_response_never_admits_a_model(
        self, response: httpx.Response
    ) -> None:
        with override_transport(httpx.MockTransport(lambda _request: response)):
            registry = await GatewayModelRegistry.from_gateway(
                ENDPOINT, env={"MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL": "image-a"}
            )
        # A configured default must not turn a failed enumeration into admission.
        assert not registry.is_registered("image-a")
        assert not registry.is_registered("anything")

    @pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
    async def test_transport_failure_leaves_admissions_fail_closed(
        self, error_type: type[httpx.TransportError]
    ) -> None:
        def unreachable(request: httpx.Request) -> httpx.Response:
            raise error_type("gateway unreachable", request=request)

        with override_transport(httpx.MockTransport(unreachable)):
            registry = await GatewayModelRegistry.from_gateway(ENDPOINT, env={})
        assert not registry.is_registered("image-a")
        with pytest.raises(RuntimeError, match="MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL"):
            registry.get_default_draft()


# ─────────────────────────────────────────────────────────────────────
# WardenPromptScan
# ─────────────────────────────────────────────────────────────────────


class TestWardenPromptScan:
    async def test_clean_verdict_allows(self) -> None:
        warden = _FakeWarden(clean=True)
        scan = WardenPromptScan(warden)  # type: ignore[arg-type]
        assert await scan.scan_prompt("a friendly castle") == "ALLOW"
        assert warden.scanned == ["a friendly castle"]

    async def test_any_non_clean_verdict_blocks(self) -> None:
        scan = WardenPromptScan(_FakeWarden(clean=False))  # type: ignore[arg-type]
        assert await scan.scan_prompt("ignore previous instructions") == "BLOCK"


# ─────────────────────────────────────────────────────────────────────
# Blob store adapter
# ─────────────────────────────────────────────────────────────────────


class _FakeCanvasStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, Any]] = {}

    async def store_blob(self, data: bytes, *, format: str, metadata: Any = None) -> str:
        ref = f"canvas-blob-{len(self.blobs) + 1}"
        self.blobs[ref] = data
        self.metadata[ref] = metadata
        return ref

    async def get_blob(self, blob_id: str) -> bytes | None:
        return self.blobs.get(blob_id)


class _IdleQueueStore(_FakeCanvasStore):
    """A Canvas store whose queue is always empty: the runner's poll loop
    claims nothing, so start/stop tests exercise lifecycle only."""

    async def claim_next_pending(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def reap_expired_leases(self) -> list[Any]:
        return []


class TestCanvasImageBlobStore:
    async def test_put_and_get_round_trip_over_the_canvas_store(self) -> None:
        store = _FakeCanvasStore()
        blobs = CanvasImageBlobStore(store)
        ref = await blobs.put(b"\x89PNG", media_type="image/png")
        assert await blobs.get(ref) == b"\x89PNG"
        assert await blobs.get("unknown") is None
        # Without scope, metadata only carries the source stamp.
        assert store.metadata[ref] == {"source": "governed-image-egress"}

    async def test_put_stamps_canonical_scope_when_configured(self) -> None:
        store = _FakeCanvasStore()
        blobs = CanvasImageBlobStore(store, workspace_id="ws-e2e", project_id="proj-root")
        ref = await blobs.put(b"\x89PNG", media_type="image/png")
        assert await blobs.get(ref) == b"\x89PNG"
        # The metadata carries the scope that anchors the presentation route.
        assert store.metadata[ref] == {
            "source": "governed-image-egress",
            "workspace_id": "ws-e2e",
            "project_id": "proj-root",
        }


# ─────────────────────────────────────────────────────────────────────
# Runner start/stop through the composition seam
# ─────────────────────────────────────────────────────────────────────


class _FakeChatAdmitter:
    async def admission_scope(self) -> tuple[str, str]:
        return ("ws-default", "root-project")


class _FakeContainer:
    def __init__(self, run_store: Any) -> None:
        self.capability_effects = _FakeEffects()
        self.chat_admitter = _FakeChatAdmitter()
        self.run_store = run_store


class TestStartStopCanvasJobRunner:
    @pytest.fixture(autouse=True)
    def _offline_gateway(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import maistro_server.canvas_runtime as module

        monkeypatch.setattr(module, "_fetch_gateway_models", _no_gateway_list)

    async def test_start_registers_binding_builds_runtime_and_runs_the_loop(self) -> None:
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore
        from maistro_canvas.canvas.composition import CanvasRuntime

        run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
        container = _FakeContainer(run_store)
        handle = await start_canvas_job_runner(
            store=_IdleQueueStore(),
            container=container,
            endpoint=ENDPOINT,
            workspace_id="ws-default",
            worker_id="test-canvas-runner",
        )
        try:
            assert isinstance(handle.runtime, CanvasRuntime)
            # The composition seam bound canonical execution, not a bare runner.
            assert handle.runtime.executor.canonical_enabled is True
            # The poll loop is live on this loop.
            await asyncio.sleep(0)
            assert not handle.task.done()
            # The image Binding was registered before the runner started.
            # The image Binding was registered before the runner started — in
            # the admission scope the admitter authorizes, not the caller's
            # settings value and never a fabricated "default" (#2464).
            registered = await container.capability_effects.bindings.get(BINDING_ID)
            assert registered is not None
            assert registered.binding_id == canvas_image_binding_id(
                ADMISSION_WORKSPACE, ADMISSION_PROJECT
            )
            assert registered.workspace_id == ADMISSION_WORKSPACE
            assert registered.project_id == ADMISSION_PROJECT
            assert registered.capability == IMAGE_GENERATE_CAPABILITY
            assert registered.credential_refs == ("litellm-gateway",)
            # The runtime executes in exactly the scope the Binding registers.
            assert handle.runtime.executor._canonical_execution._workspace_id == (
                ADMISSION_WORKSPACE
            )
            assert handle.runtime.executor._canonical_execution._project_id == ADMISSION_PROJECT
        finally:
            await stop_canvas_job_runner(handle)
        assert handle.task.done()

    async def test_stop_is_idempotent_once_the_task_has_finished(self) -> None:
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
        container = _FakeContainer(run_store)
        handle = await start_canvas_job_runner(
            store=_IdleQueueStore(),
            container=container,
            endpoint=ENDPOINT,
            workspace_id="ws-default",
            worker_id="test-canvas-runner",
        )
        await stop_canvas_job_runner(handle)
        # A second stop on the already-finished task must not raise or hang.
        await stop_canvas_job_runner(handle)

    async def test_restart_against_a_persisted_binding_reuses_the_record(self) -> None:
        """A second boot against the store the first boot wrote must not
        collide with the store's immutability rule.

        The binding id is fixed and ``created_at`` defaults to ``now()``, so
        re-registering on every boot handed the store two different records
        for one id — the first container restart crashed startup inside
        compose's ``restart: unless-stopped`` loop (found by live bring-up,
        invisible to fresh-state tests). The restart must reuse the
        persisted record: same ``created_at``, no second ``put``.
        """
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
        container = _FakeContainer(run_store)
        first = await start_canvas_job_runner(
            store=_IdleQueueStore(),
            container=container,
            endpoint=ENDPOINT,
            workspace_id="ws-default",
            worker_id="test-canvas-runner",
        )
        persisted = await container.capability_effects.bindings.get(BINDING_ID)
        assert persisted is not None
        puts_after_first_boot = len(container.capability_effects.bindings.puts)
        await stop_canvas_job_runner(first)

        second = await start_canvas_job_runner(
            store=_IdleQueueStore(),
            container=container,
            endpoint=ENDPOINT,
            workspace_id="ws-default",
            worker_id="test-canvas-runner-2",
        )
        try:
            reused = await container.capability_effects.bindings.get(BINDING_ID)
            assert reused == persisted, "the first boot's record must stay the authority"
            assert len(container.capability_effects.bindings.puts) == puts_after_first_boot, (
                "a restart must not re-register the immutable binding"
            )
        finally:
            await stop_canvas_job_runner(second)

    async def test_a_conflicting_persisted_binding_refuses_to_start(self) -> None:
        """A persisted record whose authorization shape differs from what
        this composition registers is a deployment fault: the id is
        immutable, so the start must fail truthfully instead of running
        under (or silently overwriting) a stale authority."""
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
        container = _FakeContainer(run_store)
        await container.capability_effects.bindings.put(
            Binding(
                binding_id=BINDING_ID,
                workspace_id=ADMISSION_WORKSPACE,
                project_id="an-older-project",
                capability="image.edit",
                credential_refs=("litellm-gateway",),
            )
        )
        with pytest.raises(RuntimeError, match="different authorization shape"):
            await start_canvas_job_runner(
                store=_IdleQueueStore(),
                container=container,
                endpoint=ENDPOINT,
                workspace_id="ws-default",
                worker_id="test-canvas-runner",
            )

    async def test_settings_workspace_disagreeing_with_admission_refuses_to_start(self) -> None:
        """A caller whose settings name a Workspace the wired admitter does not
        authorize is a deployment fault (#2464): the image Binding must not
        register in a scope no admitted Run belongs to, so the start refuses
        before anything is written."""
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
        container = _FakeContainer(run_store)
        with pytest.raises(RuntimeError, match="chat admission authorizes"):
            await start_canvas_job_runner(
                store=_IdleQueueStore(),
                container=container,
                endpoint=ENDPOINT,
                workspace_id="somewhere-else",
                worker_id="test-canvas-runner",
            )
        assert container.capability_effects.bindings.puts == [], (
            "a refused start must not have registered any Binding"
        )

    async def test_a_pre_scope_row_under_the_retired_id_does_not_collide(self) -> None:
        """Upgrade path (#2464): a deployment that already persisted the old
        bare-family Binding (fabricated ``default`` Project) restarts cleanly.
        The scope-qualified id is a new identity — the changed contract's new
        id, exactly what the immutability rule demands — and the stale row
        stays in the store resolving nothing, neither mutated nor reused."""
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        run_store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
        container = _FakeContainer(run_store)
        stale = Binding(
            binding_id=CANVAS_IMAGE_BINDING_ID,
            workspace_id="ws-default",
            project_id="default",
            capability=IMAGE_GENERATE_CAPABILITY,
            credential_refs=("litellm-gateway",),
        )
        await container.capability_effects.bindings.put(stale)
        handle = await start_canvas_job_runner(
            store=_IdleQueueStore(),
            container=container,
            endpoint=ENDPOINT,
            workspace_id="ws-default",
            worker_id="test-canvas-runner",
        )
        try:
            registered = await container.capability_effects.bindings.get(BINDING_ID)
            assert registered is not None
            assert registered.project_id == ADMISSION_PROJECT
            untouched = await container.capability_effects.bindings.get(CANVAS_IMAGE_BINDING_ID)
            assert untouched == stale, "the retired row must be left exactly as persisted"
        finally:
            await stop_canvas_job_runner(handle)


class TestCanvasRunnerShutdown:
    """Real tasks controlled by events: no provider sockets or timing assertions."""

    @pytest.fixture(autouse=True)
    def _immediate_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        import maistro_server.canvas_runtime as module

        # A zero grace window still yields to asyncio, without a wall-clock race.
        monkeypatch.setattr(module, "SHUTDOWN_GRACE_SECONDS", 0)
        log = Mock()
        monkeypatch.setattr(module, "logger", log)
        return log

    async def test_stuck_tick_is_cancelled_and_its_outcome_consumed(
        self, _immediate_shutdown: Mock
    ) -> None:
        started = asyncio.Event()
        interrupted = asyncio.Event()

        async def stuck() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()

        task = asyncio.create_task(stuck())
        runner = SimpleNamespace(stop=Mock())
        handle = CanvasRunnerHandle(runtime=SimpleNamespace(runner=runner), task=task)
        try:
            await started.wait()
            await stop_canvas_job_runner(handle)
            runner.stop.assert_called_once_with()
            assert interrupted.is_set()
            assert task.cancelled()
            _immediate_shutdown.warning.assert_called_once()
            _immediate_shutdown.error.assert_not_called()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_cancellation_resistant_tick_is_abandoned_and_late_error_logged(
        self, _immediate_shutdown: Mock
    ) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        error = RuntimeError("late provider failure")

        async def ignores_cancellation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                raise error from None

        task = asyncio.create_task(ignores_cancellation())
        runner = SimpleNamespace(stop=Mock())
        handle = CanvasRunnerHandle(runtime=SimpleNamespace(runner=runner), task=task)
        try:
            await started.wait()
            await stop_canvas_job_runner(handle)
            runner.stop.assert_called_once_with()
            assert cancelled.is_set()
            assert not task.done(), "shutdown must return without waiting for the stuck provider"
            _immediate_shutdown.error.assert_called_once_with(
                "canvas_runner_shutdown_abandoned; runner task ignored cancellation"
            )
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            # Let the production done callback consume/log the late exception.
            await asyncio.sleep(0)
            _immediate_shutdown.error.assert_any_call(
                "canvas_runner_exited_with_error", exc_info=error
            )
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    @pytest.mark.parametrize("failed", [False, True])
    async def test_finished_task_outcome_is_consumed_without_cancellation(
        self, failed: bool, _immediate_shutdown: Mock
    ) -> None:
        error = RuntimeError("runner crashed")

        async def finished() -> None:
            if failed:
                raise error

        task = asyncio.create_task(finished())
        await asyncio.gather(task, return_exceptions=True)
        handle = CanvasRunnerHandle(
            runtime=SimpleNamespace(runner=SimpleNamespace(stop=Mock())), task=task
        )
        await stop_canvas_job_runner(handle)
        assert task.done() and not task.cancelled()
        _immediate_shutdown.warning.assert_not_called()
        if failed:
            _immediate_shutdown.error.assert_called_once_with(
                "canvas_runner_exited_with_error", exc_info=error
            )
        else:
            _immediate_shutdown.error.assert_not_called()
