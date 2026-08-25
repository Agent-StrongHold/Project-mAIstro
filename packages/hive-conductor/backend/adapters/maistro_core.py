"""Adapters that implement AgentPort.

StubAgentPort  — placeholder response when maistro-core is not configured.
MaistroCoreBridge — embeds maistro-core in-process; chat routes through Container.route_request().
HttpOpenAILLMClient — thin httpx wrapper implementing maistro.protocols.llm.LLMClient.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from maistro.http import shared_client

if TYPE_CHECKING:
    from config import Settings


class StubAgentPort:
    """Returned when maistro-core is not configured. Preserves dev-mode startup."""

    async def route(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        return {
            "id": str(uuid4()),
            "model": "stub",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "(stub) Set MAISTRO_ROUTER_API_KEY and MAISTRO_LLM_BASE_URL "
                            "to route through real agents."
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
        }


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


class MaistroCoreBridge:
    """AgentPort implementation that embeds maistro-core directly (one process, one port)."""

    def __init__(self) -> None:
        self._container: Any = None

    @property
    def container(self) -> Any:
        """The wired maistro-core Container (holds the CapabilityRegistry), or None."""
        return self._container

    async def start(self, settings: Settings) -> None:
        import os

        from services.secrets import maistro_llm_api_key

        from maistro.agents.factory import create_agents
        from maistro.container import create_container
        from maistro.types.config import AgentConfig

        llm_base = (settings.maistro_llm_base_url or "").strip()
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
        )

        self._container = await create_container(config)

        llm_client = _HttpOpenAILLMClient(
            base_url=llm_base or "http://localhost:4000/v1",
            api_key=llm_key or "sk-noop",
            model=model,
        )
        # The container's, not a fresh in-memory one. Built by hand here, an
        # operator on `postgresql://` got durable learnings, outcomes and
        # sessions from `create_container` and lost every prompt on restart —
        # the stores sitting side by side in the `create_agents` call below
        # disagreed about whether this deployment has a database (#122).
        prompt_manager = self._container.prompt_manager

        agents_dir = settings.maistro_agents_dir
        if not os.path.isabs(agents_dir):
            # Resolve relative to hive-conductor backend directory
            agents_dir = os.path.join(os.path.dirname(__file__), "..", agents_dir)

        agents = await create_agents(
            agents_dir=agents_dir,
            prompt_manager=prompt_manager,
            llm=llm_client,
            context_builder=self._container.context_builder,
            warden=self._container.warden,
            sentinel=self._container.sentinel,
            learning_store=self._container.learning_store,
            learning_extractor=self._container.learning_extractor,
            outcome_store=self._container.outcome_store,
            session_store=self._container.session_store,
            quota_tracker=self._container.quota_tracker,
            tracer=None,
        )
        self._container.agents = agents

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
