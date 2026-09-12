"""Adapters that implement AgentPort.

StubAgentPort  — explicit unavailable response when maistro-core is not configured.
MaistroCoreBridge — embeds maistro-core in-process; chat routes through Container.route_request().
HttpOpenAILLMClient — thin httpx wrapper implementing maistro.protocols.llm.LLMClient.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from maistro.http import shared_client

if TYPE_CHECKING:
    from config import Settings


class StubAgentPort:
    """Explicit degraded-mode port used when maistro-core is unavailable.

    This object deliberately does not manufacture an assistant completion. A
    caller may keep the process alive for diagnostics/demo support, but chat
    cannot report success when the canonical Agent runtime failed to start.
    """

    async def route(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        del messages, session_id, intent_hint
        raise RuntimeError("maistro-core Agent runtime is unavailable")


class _HttpOpenAILLMClient:
    """Concrete LLMClient (maistro.protocols.llm.LLMClient) backed by an OpenAI-compatible endpoint."""

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._model = model

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

        async with shared_client(timeout=120.0) as client:
            r = await client.post(
                f"{self._base}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            return r.json()

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        # Minimal streaming: fall back to non-streaming and yield as single chunk
        result = await self.complete(messages, model, **kwargs)
        content = ""
        with contextlib.suppress(KeyError, IndexError):
            content = result["choices"][0]["message"]["content"]
        yield content


class EmbeddedRuntime(NamedTuple):
    """What composing an embedded runtime built and must keep holding.

    ``agents`` is the roster the factory returned; ``llm`` is the client that
    roster runs on; ``preamble`` is the versioned PREAMBLE template the factory
    renders every soul behind (empty only where the manifest path never ran --
    see the read in ``_construct_runtime``). Runtime materialization (#840
    Slice 4) reuses all three so a definition materialized later stands behind
    exactly the construction and safety context the boot roster was seeded
    with.
    """

    container: Any
    agents: dict[str, Any]
    llm: Any
    preamble: str


async def _construct_runtime(settings: Settings) -> EmbeddedRuntime:
    """Compose what an embedded runtime needs: the wired Container, the
    canonical agent roster built over ``settings.maistro_agents_dir``, the LLM
    client that roster runs on, and the roster's PREAMBLE template.

    Shared by ``MaistroCoreBridge.start()`` and ``build_canonical_roster()``
    so a deployment materializing the roster without a bridge projects exactly
    the roster the bridge would have built -- one construction, one roster.
    Fail-closed by the factory's own contract: with ``require_agents=True`` a
    missing or empty roster raises rather than fabricating.
    """
    import os

    from services.secrets import maistro_llm_api_key
    from services.tool_executor import dispatch_tool

    from maistro.agents.factory import _load_preamble, create_agents
    from maistro.config.database import resolve_database_url
    from maistro.container import create_container
    from maistro.types.config import AgentConfig
    from maistro.types.errors import ConfigError

    llm_base = (settings.litellm_api_base or "").strip()
    llm_key = maistro_llm_api_key(settings) or ""
    model = settings.maistro_model

    config = AgentConfig(
        router_api_key=settings.maistro_router_api_key or "",
        litellm_url=llm_base or "http://localhost:4000",
        litellm_key=llm_key,
        agents_dir=settings.maistro_agents_dir,
        # Stated, not inherited (#158). Core defaults this to "default" too,
        # so the value is the same today — but a Hive that changed its
        # default Workspace and a core that did not would then disagree
        # about where unscoped Runs live, silently.
        workspace_id=settings.hive_default_workspace_id,
        model_bindings=settings.model_bindings,
        provider_config_path=settings.provider_config_path,
        # Without this the container took the ephemeral branch and built
        # in-memory stores, however the deployment was configured -- the
        # bridge constructs `AgentConfig` directly, so it never passed
        # through `config.loader`, which is the only other caller that
        # resolves this. Binding the container's outcome store as "durable"
        # while it was in-memory is what made the omission visible (#696).
        #
        # `resolve_database_url` rather than a new Hive setting: it is the
        # one answer to "which database" for every caller, and it already
        # reads both `DATABASE_URL` and the `DB_*` set the shipped compose
        # file passes.
        database_url=resolve_database_url(),
    )

    container = await create_container(config)

    llm_client = _HttpOpenAILLMClient(
        base_url=llm_base or "http://localhost:4000/v1",
        api_key=llm_key or "sk-noop",
        model=model,
    )
    prompt_manager = container.prompt_manager

    agents_dir = settings.maistro_agents_dir
    if not os.path.isabs(agents_dir):
        # Resolve relative to hive-conductor backend directory
        agents_dir = os.path.join(os.path.dirname(__file__), "..", agents_dir)

    agents = await create_agents(
        agents_dir=agents_dir,
        prompt_manager=prompt_manager,
        llm=llm_client,
        context_builder=container.context_builder,
        warden=container.warden,
        sentinel=container.sentinel,
        learning_store=container.learning_store,
        # ADR-091's Layer 0-4 assembly. The container has always built this
        # and nothing read it back, so the episodic memories the Conductor
        # stores never reached a prompt (#622).
        context_assembly_policy=container.context_assembly_policy,
        learning_extractor=container.learning_extractor,
        outcome_store=container.outcome_store,
        session_store=container.session_store,
        quota_tracker=container.quota_tracker,
        tracer=None,
        # The tool seam, closed (#840 Slice 5): an explicit, REAL executor
        # instead of the implicit None the bridge used to pass. The factory
        # still wires it only into agents whose identity declares tools, so
        # today's all-empty shipped manifests change nothing -- but the first
        # manifest (or materialized definition) that declares a tool executes
        # against hive's real tool functions instead of silently refusing via
        # react's un-guarded branch. ADR-082526-3ca6: the runtime that owns
        # the agents owns their delegation dependencies.
        tool_executor=dispatch_tool,
        require_agents=True,
    )
    # The template for runtime materialization. Tolerant on purpose: with
    # require_agents=True the factory just fail-closed on this exact file,
    # so a miss here cannot happen on the manifest path -- and on a future
    # DB-first roster (sa_engine + PgAgentRegistry) create_agents returns
    # before ever touching the filesystem, where a hard read would spuriously
    # fail a fully valid runtime. Empty template = souls render without the
    # safety preamble, which only the fake-seamed tests ever see.
    try:
        preamble = _load_preamble(Path(agents_dir))
    except ConfigError:
        preamble = ""
    return EmbeddedRuntime(
        container=container,
        agents=agents,
        llm=llm_client,
        preamble=preamble,
    )


async def build_canonical_roster(settings: Settings) -> dict[str, Any]:
    """The canonical agent roster, built exactly the way the embedded bridge
    builds it (``create_container`` + ``create_agents`` over
    ``settings.maistro_agents_dir``, fail-closed on a missing or empty
    roster).

    Used by the boot materializer when no bridge container exists. The
    container is constructed for its wiring dependencies and deliberately not
    retained: without a bridge there is no runtime to bind it to, which is
    exactly why materialized rows are then stamped ``dispatchable=False``
    rather than wearing the shape of an executable roster.
    """
    runtime = await _construct_runtime(settings)
    return runtime.agents


class MaistroCoreBridge:
    """AgentPort implementation that embeds maistro-core directly (one process, one port)."""

    def __init__(self) -> None:
        self._container: Any = None

    @property
    def container(self) -> Any:
        """The wired maistro-core Container (holds the CapabilityRegistry), or None."""
        return self._container

    async def start(self, settings: Settings) -> None:
        runtime = await _construct_runtime(settings)
        self._container = runtime.container
        # Mutate the dict the container wired; never rebind the attribute.
        # `create_container` initializes an empty `agents` dict and hands that
        # same object to `_wire_hierarchy`, whose `_AgentMapSource` resolves
        # through the captured dict -- the closures capture the object, not its
        # contents. Assigning a fresh dict here (the old code) would leave the
        # hierarchy reading the original empty map forever: every hierarchical
        # resolution would raise `HierarchyError("unknown local agent ...")`
        # while `container.agents` itself looked perfectly populated.
        runtime.container.agents.clear()
        runtime.container.agents.update(runtime.agents)
        # Hand the runtime to the materialization service: definitions created
        # after boot (Forge, chat tools) materialize into THIS container's map
        # behind the same construction and PREAMBLE the boot roster got.
        from services.agent_materialization import register_runtime_source

        register_runtime_source(
            container=runtime.container,
            llm=runtime.llm,
            preamble=runtime.preamble,
        )

    async def route(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        if self._container is None:
            raise RuntimeError("MaistroCoreBridge.start() was not called")
        return await self._container.route_request(
            messages,
            session_id=session_id,
            intent_hint=intent_hint,
        )
