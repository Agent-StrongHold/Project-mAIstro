"""EngineService — singleton that wires maistro-core into hive-conductor.

Exposes two surfaces:
  chat   — route_request() delegates to MaistroCoreBridge
  tasks  — submit_task() / get_task() / list_tasks() / iter_task_events() via
           a TaskBackend (ADR-096 / SPEC-226): MaistroServerTaskBackend calls
           maistro-server's /tasks API in production; LocalTaskBackend wraps
           an in-process TaskQueue/runner, demo mode only.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from adapters.task_backend import TaskRecord

logger = logging.getLogger("hive.engine")

if TYPE_CHECKING:
    from config import Settings

__all__ = ["EngineService", "TaskRecord", "get_engine", "start_engine", "stop_engine"]


class EngineService:
    def __init__(self) -> None:
        self._agent_port: Any = None
        self._backend: Any = None
        self._configured = False
        self._capabilities: Any = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    @property
    def capabilities(self) -> Any:
        """The CapabilityRegistry backing the API. Sourced from the core Container
        when configured, else a standalone canonical registry (stub/dev mode)."""
        if self._capabilities is None:
            from maistro.capabilities.bootstrap import default_capability_registry

            self._capabilities = default_capability_registry()
        return self._capabilities

    @property
    def episodic_store(self) -> Any:
        """The core Container's EpisodicStore, or None in stub/unconfigured mode.

        The memory-decay driver (SPEC-080126-9e42) sweeps this. None is a real
        answer, not an error: without the bridge there is no episodic memory in
        this process, so there is nothing to decay — and the driver says so.
        """
        container = getattr(self._agent_port, "container", None)
        return getattr(container, "episodic_store", None)

    async def start(self, settings: Settings) -> None:
        from adapters.maistro_core import MaistroCoreBridge, StubAgentPort

        if settings.maistro_router_api_key:
            bridge = MaistroCoreBridge()
            try:
                await bridge.start(settings)
                self._agent_port = bridge
                self._configured = True
            except Exception as exc:
                import logging

                logging.getLogger("hive.engine").warning(
                    "maistro-core bridge failed (%s) — falling back to stub", exc
                )
                self._agent_port = StubAgentPort()
        else:
            self._agent_port = StubAgentPort()

        self._wire_capabilities(settings)

        try:
            if settings.hive_mode == "demo":
                import os

                from adapters.task_backend import LocalTaskBackend

                pm_mode = (
                    os.getenv("MAISTRO_POC_MODE", os.getenv("HIVE_POC_MODE", "")).strip().lower()
                    == "pm"
                )
                if pm_mode:
                    from maistro.agents.pm_runner import run_pm_task

                    executor = run_pm_task
                    # pm_runner makes real Claude calls through the LLM gateway
                    # for LLM-reasoning capabilities and short-circuits to
                    # source='no_data' for data tools that need PATs (jira) or
                    # Chromium (browser-use) when those aren't wired yet.
                    logger.info(
                        "LocalTaskBackend (demo) using PM runner — real LLM via LLM gateway "
                        "(source='no_data' for Jira/Airtable/web until PATs set)"
                    )
                else:
                    from maistro.agents.conductor import run_task

                    executor = run_task
                    logger.info("LocalTaskBackend (demo) using engineering conductor executor")

                backend = LocalTaskBackend(executor=executor)
                await backend.start()
                self._backend = backend
                if pm_mode:
                    from maistro.agents.catalog import AgentCatalog
                    from maistro.agents.pm_fleet import register_pm_fleet

                    catalog = AgentCatalog()
                    register_pm_fleet(catalog)
                    self._pm_catalog = catalog
            else:
                from adapters.task_backend import MaistroServerTaskBackend

                self._backend = MaistroServerTaskBackend(
                    base_url=settings.maistro_base_url,
                    api_key=settings.maistro_router_api_key,
                )
                logger.info(
                    "MaistroServerTaskBackend wired — production tasks via %s",
                    settings.maistro_base_url,
                )
        except Exception as exc:
            logging.getLogger("hive.engine").warning(
                "TaskBackend setup failed (%s) — mission dispatch disabled", exc
            )

    def _wire_capabilities(self, settings: Settings) -> None:
        """Source the registry (Container when configured, else canonical) and
        register host-health providers + apply activation. Never crashes startup."""
        container = getattr(self._agent_port, "container", None)
        if container is not None and getattr(container, "capabilities", None) is not None:
            self._capabilities = container.capabilities
        else:
            from maistro.capabilities.bootstrap import default_capability_registry

            self._capabilities = default_capability_registry()

        try:
            import stores

            from services.capabilities_wiring import wire_capabilities
            from services.foundation import get_foundation

            try:
                vault = get_foundation().vault
            except Exception:
                vault = None

            wire_capabilities(
                self._capabilities,
                settings_model=stores.settings,
                config=settings,
                vault=vault,
            )
        except Exception as exc:
            logger.warning("capability wiring failed (%s) — slots use baselines/SAFE_NOOP", exc)

    async def stop(self) -> None:
        if self._backend is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await self._backend.stop()

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        intent_hint: str = "",
    ) -> dict[str, Any]:
        return await self._agent_port.route(
            messages,
            session_id=session_id,
            intent_hint=intent_hint,
        )

    async def submit_task(
        self,
        name: str,
        description: str,
        *,
        user_id: str = "",
        task_type: str | None = None,
        agent_id: str | None = None,
        capability: str | None = None,
        program_context: dict | None = None,
    ) -> TaskRecord:
        if self._backend is None:
            raise RuntimeError("TaskQueue not available")
        from maistro.agents.pm_capabilities import is_gated, normalize_capability
        from maistro.tasks.models import TaskCreate

        cap = normalize_capability(capability or "")
        pctx_probe = program_context if isinstance(program_context, dict) else {}
        if is_gated(cap) and not pctx_probe.get("confirmed"):
            raise ValueError(
                f"Capability {cap!r} must use the work-item draft flow (POST /v1/work-items/suggest → confirm)"
            )

        pctx = program_context
        if pctx is None and user_id:
            try:
                from maistro.agents.program_context import context_for_task
                from services import program_store as prog

                pctx = context_for_task(prog.get_context(user_id))
            except Exception:
                pctx = None

        rec = await self._backend.submit(
            TaskCreate(
                description=description or name,
                task_type=task_type,
                agent_id=agent_id,
                capability=capability,
                program_context=pctx,
            ),
            user_id=user_id,
        )
        logger.info(
            "task_submitted id=%s user=%s agent=%s capability=%s type=%s",
            rec.id,
            user_id or "-",
            agent_id or "-",
            capability or "-",
            task_type or "-",
        )
        return rec

    def get_task(self, task_id: str, *, user_id: str | None = None) -> TaskRecord | None:
        if self._backend is None:
            return None
        return self._backend.get(task_id, user_id=user_id)

    def list_tasks(self, *, user_id: str | None = None) -> list[TaskRecord]:
        if self._backend is None:
            return []
        return self._backend.list_tasks(user_id=user_id)

    def delete_task(self, task_id: str) -> bool:
        if self._backend is None:
            return False
        remove = getattr(self._backend, "remove", None)
        if remove is not None:
            return bool(remove(task_id))
        return False

    @property
    def supports_clear(self) -> bool:
        """Whether this deployment's backend can bulk-clear tasks.

        `MaistroServerTaskBackend` cannot: it has no `remove_where`, so
        `clear_tasks` returns 0 and a caller is told a clear succeeded that
        removed nothing. A UI that can read this can decline to offer the
        control instead of reporting "cleared 0" as a success.
        """
        return self._backend is not None and hasattr(self._backend, "remove_where")

    def clear_tasks(self, *, status: str | None = None) -> int:
        if self._backend is None:
            return 0
        remove_where = getattr(self._backend, "remove_where", None)
        if remove_where is None:
            return 0
        from maistro.tasks.models import TaskStatus

        filter_status: TaskStatus | None = None
        if status == "failed":
            filter_status = TaskStatus.FAILED
        elif status == "completed":
            filter_status = TaskStatus.COMPLETED
        return remove_where(status=filter_status)

    async def iter_task_events(
        self, task_id: str, *, user_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        if self._backend is None:
            return
        # When scoped to a user, stream only that user's own task. The backend's
        # get() enforces ownership (empty-owner tasks fail closed), so a None
        # result means "not yours / not found" — yield nothing rather than
        # leaking another principal's in-flight events.
        if user_id is not None and self._backend.get(task_id, user_id=user_id) is None:
            return
        async for event in self._backend.iter_events(task_id):
            yield event


_singleton: EngineService | None = None


def get_engine() -> EngineService:
    if _singleton is None:
        raise RuntimeError("EngineService not started — call start_engine() at app lifespan")
    return _singleton


async def start_engine(settings: Settings) -> EngineService:
    global _singleton
    _singleton = EngineService()
    await _singleton.start(settings)
    return _singleton


async def stop_engine() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.stop()
        _singleton = None
